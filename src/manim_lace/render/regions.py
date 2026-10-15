"""Planar-region ribbon backend (SPEC FR-052, FR-053, FR-054, FR-055, FR-057, FR-058).

The stroke backend cuts centerlines with a heuristic radius. This backend builds the
actual ribbon areas instead and removes, at every woven crossing, the exact Boolean
intersection of the two ribbons: no radius, no shallow-angle clamp, no cap
compensation. The removed lens is precisely the footprint of the ribbon that is over,
which is what "the over strand hides the under strand" means geometrically.

Regions are extracted with a validated Boolean engine (Shapely), as SPEC FR-054
requires, instead of a cycle-basis polygon heuristic. Ring roles are reported
explicitly so a renderer never has to guess which ring is a source contour and which
one is a gap created by the weave (SPEC FR-058).

This module does not import Manim, and it imports Shapely only inside the entry point,
so the core stays importable without the optional ``geometry`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CapStyle, CrossingEvent, JoinStyle, PolylinePath, WeaveTopology

__all__ = [
    "RegionRenderResult",
    "RegionRing",
    "RibbonRegion",
    "RibbonRegionRenderer",
    "render_region_geometry",
]

#: Shapely's name for each cap and join strategy the geometry layer exposes.
_CAP_STYLES = {"butt": "flat", "round": "round", "square": "square"}
_JOIN_STYLES = {"miter": "mitre", "bevel": "bevel", "round": "round"}
#: Ring roles, so an adapter never has to infer them from ring size (SPEC FR-058):
#: ``exterior`` is the visible outline, ``source_contour`` is an interior hole the
#: source shape already had, ``occlusion`` is a gap the weave itself created.
RingRole = Literal["exterior", "source_contour", "occlusion"]


def _shoelace(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


@dataclass(frozen=True, slots=True)
class RegionRing:
    """One closed boundary ring: the first point is repeated as the last point.

    Exteriors follow the counter-clockwise convention and holes the clockwise one, so
    a consumer can rely on orientation instead of ring size (SPEC FR-057, FR-058).
    """

    points: np.ndarray
    role: RingRole

    @property
    def area(self) -> float:
        return abs(_shoelace(self.points))

    @property
    def counter_clockwise(self) -> bool:
        return _shoelace(self.points) > 0


@dataclass(slots=True)
class RibbonRegion:
    """The visible area of one path after the weave has been applied."""

    region_id: str
    path_id: str
    exterior: RegionRing
    holes: list[RegionRing] = field(default_factory=list)
    area: float = 0.0

    @property
    def rings(self) -> list[RegionRing]:
        return [self.exterior, *self.holes]


@dataclass(slots=True)
class RegionRenderResult:
    """Regions plus the accounting that makes them checkable (SPEC FR-059)."""

    regions: list[RibbonRegion]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    removed_area: float = 0.0
    band_area: float = 0.0
    union_area: float = 0.0

    @property
    def covered_area(self) -> float:
        return float(sum(region.area for region in self.regions))

    @property
    def holes(self) -> list[RegionRing]:
        """Every hole ring of every region, for adapters that paint them separately."""
        return [ring for region in self.regions for ring in region.holes]

    def regions_for(self, path_id: str) -> list[RibbonRegion]:
        return [region for region in self.regions if region.path_id == path_id]


def _require_shapely() -> tuple[Any, Any, Any, Any, Any]:
    """Import the optional Boolean engine, with the install hint when it is missing."""
    try:
        from shapely.geometry import LineString, Point
        from shapely.geometry.polygon import orient
        from shapely.ops import unary_union
        from shapely.validation import make_valid
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "render_mode='ribbon' 需要可选依赖 shapely：pip install 'manim-lace[geometry]'"
        ) from exc
    return LineString, Point, unary_union, make_valid, orient


def _ring_points(ring: Any) -> np.ndarray:
    coords = np.asarray(ring.coords, dtype=float)[:, :2]
    if len(coords) < 2 or not np.allclose(coords[0], coords[-1]):
        coords = np.vstack((coords, coords[0]))
    return coords


def _ring_area(ring: Any) -> float:
    return abs(_shoelace(_ring_points(ring)))


def _polygons(geometry: Any) -> list[Any]:
    kind = getattr(geometry, "geom_type", "")
    if kind == "Polygon":
        return [] if geometry.is_empty else [geometry]
    if kind in ("MultiPolygon", "GeometryCollection"):
        polygons: list[Any] = []
        for part in geometry.geoms:
            polygons.extend(_polygons(part))
        return polygons
    return []


def _repair(
    geometry: Any, make_valid: Any, path: PolylinePath, diagnostics: list[Diagnostic]
) -> Any:
    """Validate an offset outline and repair it out loud (SPEC FR-055, FR-057)."""
    if geometry.is_valid:
        return geometry
    diagnostics.append(Diagnostic(
        code="REGION-INVALID-OUTLINE",
        severity=Severity.WARNING,
        message=(
            f"路径 {path.path_id} 的偏移轮廓无效（自交或塌缩），已用受控修复重建；"
            "修复结果可能与理想轮廓有细微差别。"
        ),
        path_ids=(path.path_id,),
        hints=("减小 offset、改用 bevel/round 连接策略或提高采样密度可避免该情形。",),
    ))
    return make_valid(geometry)


def _hole_roles(polygon: Any, source_hole_areas: list[float]) -> list[RingRole]:
    """Classify each interior ring as an original contour hole or a weave gap."""
    roles: list[RingRole] = []
    for ring in polygon.interiors:
        area = _ring_area(ring)
        known = any(
            abs(area - reference) <= 1e-6 * max(reference, 1.0) for reference in source_hole_areas
        )
        roles.append("source_contour" if known else "occlusion")
    return roles


def _local_lens(under_band: Any, over_band: Any, point: tuple[float, float], point_class: Any) -> Any | None:
    """The overlap component that belongs to one crossing, and only that one.

    Two bands meet once per crossing, but intersecting them as whole geometries
    returns every overlap the two ribbons share. Subtracting all of it would cut the
    under ribbon at the other crossings too, so the component that contains this
    crossing point — the exact local footprint of the over ribbon — is selected
    instead. No radius or angle heuristic is involved.
    """
    intersection = under_band.intersection(over_band)
    if intersection.is_empty:
        return None
    probe = point_class(point[0], point[1])
    candidates = _polygons(intersection)
    if not candidates:
        return None
    containing = [
        polygon for polygon in candidates
        if polygon.contains(probe) or polygon.touches(probe)
    ]
    if containing:
        return max(containing, key=lambda polygon: polygon.area)
    nearest = min(candidates, key=lambda polygon: polygon.distance(probe))
    scale = max(abs(float(under_band.bounds[2] - under_band.bounds[0])), 1.0)
    return nearest if nearest.distance(probe) <= 1e-9 * scale else None


def render_region_geometry(
    paths: list[PolylinePath],
    crossings: list[CrossingEvent],
    topology: WeaveTopology,
    *,
    offset: float,
    cap_style: CapStyle = "butt",
    join: JoinStyle = "miter",
    miter_limit: float = 5.0,
    area_tolerance: float = 1e-6,
) -> RegionRenderResult:
    """Build area-based ribbon regions and weave them by exact Boolean subtraction.

    Every path becomes one offset band (``offset`` is the ribbon half-width). At each
    woven crossing the *under* band loses the intersection with the *over* band, which
    is exactly the area the over ribbon covers there. ``join`` selects the offset
    connection strategy (``miter`` obeys ``miter_limit``); ``cap_style`` has the same
    meaning as in the stroke backend, but here the caps are real geometry rather than a
    widened heuristic gap.

    Two situations are reported instead of guessed: a self-crossing, whose two passes
    share one band (splitting a band per pass is a separate step), and a crossing
    without an assignment, which cannot be woven at all.
    """
    if not np.isfinite(offset) or offset <= 0:
        raise ValueError("offset must be positive and finite")
    if cap_style not in _CAP_STYLES:
        raise ValueError("cap_style must be 'butt', 'round' or 'square'")
    if join not in _JOIN_STYLES:
        raise ValueError("join must be 'miter', 'bevel' or 'round'")
    if not np.isfinite(miter_limit) or miter_limit <= 0:
        raise ValueError("miter_limit must be positive and finite")
    if not np.isfinite(area_tolerance) or area_tolerance < 0:
        raise ValueError("area_tolerance must be finite and non-negative")
    LineString, Point, unary_union, make_valid, orient = _require_shapely()

    diagnostics: list[Diagnostic] = []
    bands: dict[str, Any] = {}
    source_hole_areas: dict[str, list[float]] = {}
    for path in paths:
        if path.length <= 0:
            diagnostics.append(Diagnostic(
                code="REGION-EMPTY-RIBBON",
                severity=Severity.INFO,
                message=f"路径 {path.path_id} 没有长度，因此不产生区域。",
                path_ids=(path.path_id,),
            ))
            continue
        band = LineString(np.asarray(path.points, dtype=float)).buffer(
            offset,
            cap_style=_CAP_STYLES[cap_style],
            join_style=_JOIN_STYLES[join],
            mitre_limit=float(miter_limit),
        )
        band = _repair(band, make_valid, path, diagnostics)
        if getattr(band, "geom_type", "") == "Polygon":
            band = orient(band, 1.0)
        if band.is_empty:
            diagnostics.append(Diagnostic(
                code="REGION-EMPTY-RIBBON",
                severity=Severity.INFO,
                message=f"路径 {path.path_id} 的偏移区域为空，没有可见面。",
                path_ids=(path.path_id,),
            ))
            continue
        bands[path.path_id] = band
        source_hole_areas[path.path_id] = [
            _ring_area(ring) for polygon in _polygons(band) for ring in polygon.interiors
        ]

    visible = dict(bands)
    removed_area = 0.0
    for crossing in crossings:
        if crossing.kind != "transverse":
            continue
        if crossing.path_a == crossing.path_b:
            diagnostics.append(Diagnostic(
                code="REGION-SELF-CROSSING-UNSUPPORTED",
                severity=Severity.WARNING,
                message=(
                    f"自交 {crossing.crossing_id} 的两次经过属于同一条带，区域后端尚不能"
                    "把它们拆成两个面，因此该处未做切除（丝带保持完整）。"
                ),
                path_ids=(crossing.path_a,),
                crossing_id=crossing.crossing_id,
                point=crossing.point,
                hints=("需要按经过把中心线拆成子带；在那之前该事件不会被静默处理。",),
            ))
            continue
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            diagnostics.append(Diagnostic(
                code="REGION-MISSING-ASSIGNMENT",
                severity=Severity.WARNING,
                message="交叉缺少上下关系，因此该处没有切除任何区域。",
                path_ids=(crossing.path_a, crossing.path_b),
                crossing_id=crossing.crossing_id,
                point=crossing.point,
            ))
            continue
        under_id = crossing.path_a if assignment.under_side == "a" else crossing.path_b
        over_id = crossing.path_b if assignment.under_side == "a" else crossing.path_a
        under_band, over_band = visible.get(under_id), bands.get(over_id)
        if under_band is None or over_band is None or under_band.is_empty:
            continue
        lens = _local_lens(under_band, over_band, crossing.point, Point)
        if lens is None:
            continue
        before = float(under_band.area)
        visible[under_id] = under_band.difference(lens)
        removed_area += before - float(visible[under_id].area)

    regions: list[RibbonRegion] = []
    for path in paths:
        geometry = visible.get(path.path_id)
        if geometry is None or geometry.is_empty:
            continue
        for index, polygon in enumerate(_polygons(geometry)):
            polygon = orient(polygon, 1.0)
            holes = [
                RegionRing(points=_ring_points(ring), role=role)
                for ring, role in zip(
                    polygon.interiors,
                    _hole_roles(polygon, source_hole_areas.get(path.path_id, [])),
                    strict=True,
                )
            ]
            regions.append(RibbonRegion(
                region_id=f"{path.path_id}.region{index}",
                path_id=path.path_id,
                exterior=RegionRing(points=_ring_points(polygon.exterior), role="exterior"),
                holes=holes,
                area=float(polygon.area),
            ))

    band_area = float(sum(band.area for band in bands.values()))
    union_area = float(unary_union(list(bands.values())).area) if bands else 0.0
    covered = float(sum(region.area for region in regions))
    tolerance = max(area_tolerance * max(union_area, 1.0), 1e-12)
    if bands and abs(covered - union_area) > tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-AREA-MISMATCH",
            severity=Severity.WARNING,
            message=(
                "可见区域总面积与丝带并集面积不一致：某处被切除的区域没有被上方丝带覆盖"
                "（通常是三条以上丝带在非交叉点处互相重叠）。"
            ),
            details={
                "covered_area": covered,
                "union_area": union_area,
                "difference": covered - union_area,
                "tolerance": tolerance,
            },
            hints=("检查是否有三条以上丝带在同一区域重叠；必要时减小 offset 或改回描边后端。",),
        ))
    return RegionRenderResult(
        regions=regions,
        diagnostics=diagnostics,
        removed_area=removed_area,
        band_area=band_area,
        union_area=union_area,
    )


class RibbonRegionRenderer:
    """The region backend behind the ``render_mode='ribbon'`` seam."""

    def render(
        self,
        paths: list[PolylinePath],
        crossings: list[CrossingEvent],
        topology: WeaveTopology,
        *,
        offset: float,
        cap_style: CapStyle = "butt",
        join: JoinStyle = "miter",
        miter_limit: float = 5.0,
    ) -> RegionRenderResult:
        return render_region_geometry(
            paths, crossings, topology,
            offset=offset, cap_style=cap_style, join=join, miter_limit=miter_limit,
        )
