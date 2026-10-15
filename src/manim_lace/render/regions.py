"""Planar-region ribbon backend (SPEC FR-052, FR-053, FR-054, FR-055, FR-057, FR-058).

The stroke backend cuts centerlines with a heuristic radius. This backend builds the
actual ribbon areas instead and removes, at every woven crossing, the exact Boolean
intersection of the two ribbons: no radius, no shallow-angle clamp, no cap compensation.
The removed lens is precisely the footprint of the ribbon that is over, which is what
"the over strand hides the under strand" means geometrically.

Each path's band is cut at the crossings it takes part in, so the two passes of a
self-crossing become *sections* that can be over and under each other — a single band
cannot be both. Sections meet exactly on the split line, so their union is the whole
band again and no seam is introduced.

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
from ..tracing import BoundedRecords
from .order import paint_order

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
    """The visible area of one path, or of one section of a self-crossing path.

    ``draw_index`` orders the regions: a region of an under strand always comes before
    the regions over it. Overlaps only occur between sections of one self-crossing
    path, where the paint order is what shows which strand is on top.
    """

    region_id: str
    path_id: str
    exterior: RegionRing
    holes: list[RegionRing] = field(default_factory=list)
    area: float = 0.0
    draw_index: int = 0

    @property
    def rings(self) -> list[RegionRing]:
        return [self.exterior, *self.holes]


@dataclass(slots=True)
class RegionRenderResult:
    """Regions plus the accounting that makes them checkable (SPEC FR-059).

    ``painted_area`` is the union of the visible regions, i.e. what a renderer shows
    when it honours ``draw_index``; ``region_area_sum`` is the plain sum, which is
    larger wherever sections of one self-crossing path overlap. The invariant to check
    is ``painted_area == union_area`` (the ribbon that was built), and
    ``union_area == band_area`` for everything that was not divided into sections.

    ``face_walk`` describes the traversal that produced these regions (the M5
    fine-grained trace). Both backends use the same key scheme
    (``backend``, ``node_kind``, ``node_count``, ``band_count``, ``section_count``,
    ``crossing_count``, ``owner_count``, ``congested``, ``removed_area`` and the
    bounded ``steps`` list), and each adds the counters its own walk produced:
    ``region_polygon_count`` plus the cut accounting for the Boolean backend,
    ``face_count`` plus the face and ownership counters for the arrangement one.
    """

    regions: list[RibbonRegion]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    removed_area: float = 0.0
    band_area: float = 0.0
    union_area: float = 0.0
    painted_area: float = 0.0
    region_area_sum: float = 0.0
    face_walk: dict[str, Any] = field(default_factory=dict)

    @property
    def covered_area(self) -> float:
        """The painted area, i.e. the union of the regions."""
        return self.painted_area

    @property
    def holes(self) -> list[RegionRing]:
        """Every hole ring of every region, for adapters that paint them separately."""
        return [ring for region in self.regions for ring in region.holes]

    def ordered_regions(self) -> list[RibbonRegion]:
        """Regions in the deterministic paint order (see ``RibbonRegion.draw_index``)."""
        return sorted(self.regions, key=lambda region: (region.draw_index, region.region_id))

    def regions_for(self, path_id: str) -> list[RibbonRegion]:
        return [region for region in self.regions if region.path_id == path_id]


@dataclass(frozen=True, slots=True)
class _Strip:
    """One ribbon section of a path, between two of the crossings it takes part in.

    Sections are needed only where a single band cannot answer the question: the two
    passes of a self-crossing share one band, and a band cannot be both over and under
    itself. Elsewhere the whole band stays one geometry, which keeps the exact
    subtraction of the current crossing independent of every other one.
    """

    strip_id: str
    path_id: str
    start_arc: float
    end_arc: float
    band: Any


def _require_shapely() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Import the optional Boolean engine, with the install hint when it is missing."""
    try:
        from shapely.geometry import LineString, Point, Polygon
        from shapely.geometry.polygon import orient
        from shapely.ops import unary_union
        from shapely.validation import make_valid
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "render_mode='ribbon' 需要可选依赖 shapely：pip install 'manim-lace[geometry]'"
        ) from exc
    return LineString, Point, Polygon, unary_union, make_valid, orient


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


def _local_lens(
    under_region: Any, over_region: Any, point: tuple[float, float], point_class: Any
) -> Any | None:
    """The overlap component that belongs to one crossing, and only that one.

    Two ribbons can meet more than once, and intersecting them as whole geometries
    returns every overlap they share. Subtracting all of it would cut the under ribbon
    at the other crossings too, so the component that contains this crossing point —
    the exact local footprint of the over ribbon — is selected instead. No radius or
    angle heuristic is involved.
    """
    intersection = under_region.intersection(over_region)
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
    scale = max(abs(float(under_region.bounds[2] - under_region.bounds[0])), 1.0)
    return nearest if nearest.distance(probe) <= 1e-9 * scale else None


def _point_at(path: PolylinePath, arc: float) -> np.ndarray:
    return _arc_frame(path, arc)[0]


def _arc_points(path: PolylinePath, start: float, end: float) -> np.ndarray:
    """The polyline of a path between two arcs; closed paths may wrap past the seam."""
    length = float(path.length)
    cumulative = path.cumulative_lengths
    inner: list[float] = []
    if path.closed:
        base = cumulative[:-1]
        low = int(np.floor(start / max(length, 1e-30))) - 1
        high = int(np.ceil(end / max(length, 1e-30))) + 1
        for step in range(low, high + 1):
            inner.extend((base + step * length).tolist())
    else:
        inner = cumulative.tolist()
    sequence = [start, *[value for value in inner if start + 1e-10 < value < end - 1e-10], end]
    points = [_point_at(path, value) for value in sequence]
    compact = [points[0]]
    for point in points[1:]:
        if float(np.linalg.norm(point - compact[-1])) > 1e-12:
            compact.append(point)
    if len(compact) == 1:
        compact.append(compact[0].copy())
    return np.asarray(compact)


def _arc_frame(path: PolylinePath, arc: float) -> tuple[np.ndarray, np.ndarray]:
    """Point and unit tangent at an arc length, wrapped or clamped like the path."""
    length = float(path.length)
    if path.closed and length > 0:
        value = float(arc) % length
    else:
        value = float(np.clip(arc, 0.0, length))
    cumulative = path.cumulative_lengths
    index = int(np.clip(np.searchsorted(cumulative, value, side="right") - 1, 0, len(cumulative) - 2))
    segment = path.points[index + 1] - path.points[index]
    norm = float(np.linalg.norm(segment))
    if norm <= 0:
        return path.points[index].copy(), np.array([1.0, 0.0])
    ratio = (value - float(cumulative[index])) / norm
    return path.points[index] + ratio * segment, segment / norm


def _half_plane(point: np.ndarray, tangent: np.ndarray, extent: float, polygon_class: Any) -> Any:
    """A large box covering the forward side of the line through ``point``.

    The box edge lies exactly on that line, which is what makes the two sides of a
    split meet without a gap or an overlap.
    """
    normal = np.array([-tangent[1], tangent[0]])
    across = normal * extent
    along = tangent * extent
    return polygon_class([
        point - across, point + along - across, point + along + across, point + across,
    ])


def _split_arcs(path: PolylinePath, arcs: list[float]) -> list[float]:
    """Sorted, de-duplicated split positions that actually divide the path."""
    length = float(path.length)
    tolerance = 1e-9 * max(length, 1.0)
    unique: list[float] = []
    for arc in sorted(float(value) % length if path.closed else float(value) for value in arcs):
        if unique and arc - unique[-1] <= tolerance:
            continue
        unique.append(arc)
    if not path.closed:
        # The two path ends are already boundaries of the band.
        unique = [arc for arc in unique if tolerance < arc < length - tolerance]
    return unique


class _StripBuilder:
    """Builds and looks up the ribbon sections of the paths that need them.

    A path needs sections only when it crosses itself: its two passes share one band,
    and one band cannot be both over and under. Everywhere else the whole band stays a
    single geometry, so the exact subtraction at one crossing stays independent of all
    the others.
    """

    def __init__(
        self,
        *,
        offset: float,
        cap_style: CapStyle,
        join: JoinStyle,
        miter_limit: float,
        point_class: Any,
        polygon_class: Any,
        line_class: Any,
        unary_union: Any,
    ) -> None:
        self.offset = float(offset)
        self.cap_style = cap_style
        self.miter_limit = float(miter_limit)
        self.join_style = _JOIN_STYLES[join]
        self.point_class = point_class
        self.polygon_class = polygon_class
        self.line_class = line_class
        self.unary_union = unary_union
        self._cache: dict[str, list[_Strip]] = {}

    def _cap_shape(self, point: np.ndarray, tangent: np.ndarray, *, forward: bool) -> Any | None:
        """The paint the configured cap adds beyond a path end, as its own geometry."""
        if self.cap_style == "butt":
            return None
        direction = tangent if forward else -tangent
        if self.cap_style == "square":
            along = direction * self.offset
            across = np.array([-direction[1], direction[0]]) * self.offset
            return self.polygon_class([
                point - across, point + along - across, point + along + across, point + across,
            ])
        disc = self.point_class(point[0], point[1]).buffer(self.offset)
        return disc.intersection(_half_plane(point, direction, 2.0 * self.offset, self.polygon_class))

    def _band(self, path: PolylinePath, start_arc: float, end_arc: float, *, at_start: bool, at_end: bool) -> Any:
        strip = self.line_class(_arc_points(path, start_arc, end_arc)).buffer(
            self.offset, cap_style="flat", join_style=self.join_style,
            mitre_limit=self.miter_limit,
        )
        shapes = [strip]
        for arc, forward, wanted in ((0.0, False, at_start), (float(path.length), True, at_end)):
            if not wanted or path.closed:
                continue
            point, tangent = _arc_frame(path, arc)
            cap = self._cap_shape(point, tangent, forward=forward)
            if cap is not None and not cap.is_empty:
                shapes.append(cap)
        return strip if len(shapes) == 1 else self.unary_union(shapes)

    def for_path(self, path: PolylinePath, arcs: list[float]) -> list[_Strip]:
        """The sections of one path, built once and cached."""
        if path.path_id in self._cache:
            return self._cache[path.path_id]
        length = float(path.length)
        strips: list[_Strip] = []
        if arcs:
            if path.closed:
                for index, start in enumerate(arcs):
                    wraps = index + 1 == len(arcs)
                    end = arcs[(index + 1) % len(arcs)] + (length if wraps else 0.0)
                    strips.append(_Strip(
                        strip_id=f"{path.path_id}#{index}", path_id=path.path_id,
                        start_arc=start, end_arc=end,
                        band=self._band(path, start, end, at_start=False, at_end=False),
                    ))
            else:
                boundaries = [0.0, *arcs, length]
                for index in range(len(boundaries) - 1):
                    strips.append(_Strip(
                        strip_id=f"{path.path_id}#{index}", path_id=path.path_id,
                        start_arc=boundaries[index], end_arc=boundaries[index + 1],
                        band=self._band(
                            path, boundaries[index], boundaries[index + 1],
                            at_start=index == 0, at_end=index == len(boundaries) - 2,
                        ),
                    ))
        self._cache[path.path_id] = strips
        return strips

    @staticmethod
    def adjacent(strips: list[_Strip], arc: float, *, closed: bool, length: float) -> list[_Strip]:
        """Sections that meet the path at ``arc``: there the under/over strand lives."""
        tolerance = 1e-9 * max(length, 1.0)
        targets = [arc, arc + length] if closed else [arc]
        found: list[_Strip] = []
        for strip in strips:
            if any(
                abs(strip.start_arc - target) <= tolerance or abs(strip.end_arc - target) <= tolerance
                for target in targets
            ):
                found.append(strip)
        return found


def _nodes_for(
    path_id: str, arc: float, strips: dict[str, list[_Strip]], geometry_by_id: dict[str, PolylinePath]
) -> list[str]:
    """Paint-order nodes that represent a path at one crossing.

    A divided path is represented by the sections that meet the crossing; everything
    else by the path itself.
    """
    group = strips.get(path_id)
    path = geometry_by_id.get(path_id)
    if not group or path is None:
        return [path_id]
    found = _StripBuilder.adjacent(
        group, arc, closed=path.closed, length=float(path.length)
    )
    return [strip.strip_id for strip in found] or [path_id]


def build_bands(
    paths: list[PolylinePath],
    *,
    offset: float,
    cap_style: CapStyle,
    join: JoinStyle,
    miter_limit: float,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """One offset band per path, plus the interior-ring areas it started with.

    Shared by both region backends so that "the ribbon" means the same thing in each.
    """
    LineString, _Point, _Polygon, _union, make_valid, orient = _require_shapely()
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
    return bands, source_hole_areas


def build_sections(
    paths: list[PolylinePath],
    bands: dict[str, Any],
    self_crossings: list[CrossingEvent],
    *,
    offset: float,
    cap_style: CapStyle,
    join: JoinStyle,
    miter_limit: float,
    line_class: Any,
    point_class: Any,
    polygon_class: Any,
    unary_union: Any,
) -> dict[str, list[_Strip]]:
    """Sections of the paths that cross themselves, keyed by path ID."""
    split_arcs: dict[str, list[float]] = {path_id: [] for path_id in bands}
    for crossing in self_crossings:
        split_arcs[crossing.path_a].extend((crossing.s_a, crossing.s_b))
    builder = _StripBuilder(
        offset=offset, cap_style=cap_style, join=join, miter_limit=miter_limit,
        point_class=point_class, polygon_class=polygon_class,
        line_class=line_class, unary_union=unary_union,
    )
    sections: dict[str, list[_Strip]] = {}
    for path in paths:
        if path.path_id not in bands or not split_arcs.get(path.path_id):
            continue
        sections[path.path_id] = builder.for_path(
            path, _split_arcs(path, split_arcs[path.path_id])
        )
    return sections


def _boxes_overlap(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    return not (
        second[2] < first[0] or second[0] > first[2]
        or second[3] < first[1] or second[1] > first[3]
    )


def _subtract_from_strips(strips: list[_Strip], visible: dict[str, Any], lens: Any) -> float:
    """Remove one lens from the sections it actually overlaps."""
    removed = 0.0
    for strip in strips:
        current = visible[strip.strip_id]
        if current.is_empty or not _boxes_overlap(current.bounds, lens.bounds):
            continue
        before = float(current.area)
        visible[strip.strip_id] = current.difference(lens)
        removed += before - float(visible[strip.strip_id].area)
    return removed


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

    Every path becomes one offset band (``offset`` is the ribbon half-width), cut into
    sections at the crossings it takes part in. At each woven crossing the sections of
    the under strand lose the intersection with the sections of the over strand that
    are local to that crossing — exactly the area the over ribbon covers there.
    ``join`` selects the offset connection strategy (``miter`` obeys ``miter_limit``);
    ``cap_style`` has the same meaning as in the stroke backend, but here the caps are
    real geometry rather than a widened heuristic gap.

    A crossing whose under or over arc cannot be located in the section structure is
    reported as ``REGION-CROSSING-SKIPPED`` instead of being woven wrongly.
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
    LineString, Point, Polygon, unary_union, make_valid, orient = _require_shapely()

    diagnostics: list[Diagnostic] = []
    bands, source_hole_areas = build_bands(
        paths, offset=offset, cap_style=cap_style, join=join,
        miter_limit=miter_limit, diagnostics=diagnostics,
    )
    geometry_by_id = {path.path_id: path for path in paths}

    # A path is cut into sections only when it crosses itself: its two passes share one
    # band, and one band cannot be over and under itself. Everything else keeps the
    # whole band, which is what makes an ordinary crossing exactly local.
    weavable = [crossing for crossing in crossings if crossing.kind == "transverse"]
    self_crossings = [crossing for crossing in weavable if crossing.path_a == crossing.path_b]
    strips = build_sections(
        paths, bands, self_crossings, offset=offset, cap_style=cap_style, join=join,
        miter_limit=miter_limit, line_class=LineString, point_class=Point,
        polygon_class=Polygon, unary_union=unary_union,
    )
    visible_band: dict[str, Any] = dict(bands)
    visible_strip: dict[str, Any] = {
        strip.strip_id: strip.band for group in strips.values() for strip in group
    }
    removed_area = 0.0
    walk = BoundedRecords()
    missing_assignment_count = 0
    self_crossing_count = 0
    empty_band_count = 0
    lens_miss_count = 0
    cut_count = 0
    section_cut_count = 0
    for crossing in weavable:
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            missing_assignment_count += 1
            walk.add({"kind": "skip", "reason": "missing_assignment",
                      "crossing_id": crossing.crossing_id})
            diagnostics.append(Diagnostic(
                code="REGION-MISSING-ASSIGNMENT",
                severity=Severity.WARNING,
                message="交叉缺少上下关系，因此该处没有切除任何区域。",
                path_ids=(crossing.path_a, crossing.path_b),
                crossing_id=crossing.crossing_id,
                point=crossing.point,
            ))
            continue
        if crossing.path_a == crossing.path_b:
            # One path: both passes are sections of the same ribbon, and the sections
            # already overlap at the crossing. Painting the over section after the under
            # one shows the same result as cutting, without removing area that belongs
            # to the strand on top.
            self_crossing_count += 1
            walk.add({"kind": "skip", "reason": "self_crossing_order",
                      "crossing_id": crossing.crossing_id})
            continue
        under_id = crossing.path_a if assignment.under_side == "a" else crossing.path_b
        over_id = crossing.path_b if assignment.under_side == "a" else crossing.path_a
        current = visible_band.get(under_id)
        over_band = bands.get(over_id)
        if current is None or over_band is None or current.is_empty:
            empty_band_count += 1
            walk.add({"kind": "skip", "reason": "empty_under_band",
                      "crossing_id": crossing.crossing_id, "under": under_id})
            continue
        lens = _local_lens(current, over_band, crossing.point, Point)
        if lens is None:
            lens_miss_count += 1
            walk.add({"kind": "skip", "reason": "no_local_overlap",
                      "crossing_id": crossing.crossing_id, "under": under_id, "over": over_id})
            continue
        if under_id in strips:
            # A divided path is cut section by section; the lens is local, so the
            # bounding boxes keep this to the one or two sections it touches.
            removed = _subtract_from_strips(strips[under_id], visible_strip, lens)
            removed_area += removed
            cut_count += 1
            section_cut_count += 1
            walk.add({"kind": "weave", "crossing_id": crossing.crossing_id,
                      "under": under_id, "over": over_id, "target": "section",
                      "lens_area": float(lens.area), "removed_area": float(removed)})
            continue
        before = float(current.area)
        visible_band[under_id] = current.difference(lens)
        removed = before - float(visible_band[under_id].area)
        removed_area += removed
        cut_count += 1
        walk.add({"kind": "weave", "crossing_id": crossing.crossing_id,
                  "under": under_id, "over": over_id, "target": "band",
                  "lens_area": float(lens.area), "removed_area": float(removed)})

    path_position = {path.path_id: index for index, path in enumerate(paths)}
    node_of: dict[str, str] = {}
    order_nodes: list[str] = []
    for path in paths:
        if strips.get(path.path_id):
            for strip in strips[path.path_id]:
                node_of[strip.strip_id] = path.path_id
                order_nodes.append(strip.strip_id)
        elif path.path_id in bands:
            node_of[path.path_id] = path.path_id
            order_nodes.append(path.path_id)
    order_edges: list[tuple[str, str]] = []
    for crossing in weavable:
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            continue
        under_id = crossing.path_a if assignment.under_side == "a" else crossing.path_b
        over_id = crossing.path_b if assignment.under_side == "a" else crossing.path_a
        under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
        over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
        under_nodes = _nodes_for(under_id, under_arc, strips, geometry_by_id)
        over_nodes = _nodes_for(over_id, over_arc, strips, geometry_by_id)
        order_edges.extend((under, over) for under in under_nodes for over in over_nodes)
    layers, congested = paint_order(order_nodes, order_edges)
    ordered = sorted(order_nodes, key=lambda node: (layers[node], path_position[node_of[node]], node))
    draw_index = {node: index for index, node in enumerate(ordered)}
    if congested and strips:
        diagnostics.append(Diagnostic(
            code="REGION-DRAW-ORDER-CYCLE",
            severity=Severity.INFO,
            message=(
                "过／欠关系存在环，且其中有路径被拆成分段（自交必须靠绘制顺序解决）；"
                "顺序按节点顺序确定性打破，可能有个别交叉的上下关系与几何期望相反。"
            ),
            details={"constraints": [[under, over] for under, over in congested]},
            hints=("两条股线交叉偶数次时该环必然出现；不透明填充顺序仍需遵守 draw_index。",),
        ))
    overlapping_paths = sorted({
        crossing.path_a for crossing in self_crossings
        if topology.assignment_for(crossing.crossing_id) is not None
    })
    if overlapping_paths:
        diagnostics.append(Diagnostic(
            code="REGION-OVERLAPPING-SECTIONS",
            severity=Severity.INFO,
            message=(
                "自交路径按分段输出互相重叠的面域，重叠处（交叉）由 draw_index 决定谁在上，"
                "因此区域面积之和会大于可见面积。"
            ),
            path_ids=tuple(overlapping_paths),
            details={"path_ids": overlapping_paths},
            hints=("填充时按 RibbonRegion.draw_index 递增绘制；可见面积请用 painted_area。",),
        ))
    coincident: dict[tuple[float, float], list[str]] = {}
    for crossing in weavable:
        key = (round(float(crossing.point[0]), 9), round(float(crossing.point[1]), 9))
        coincident.setdefault(key, []).append(crossing.crossing_id)
    groups = [ids for ids in coincident.values() if len(ids) > 1]
    if groups:
        diagnostics.append(Diagnostic(
            code="REGION-COINCIDENT-CROSSINGS",
            severity=Severity.WARNING,
            message=(
                "多个交叉落在同一点上：各交叉各自扣除的重叠区会互相抵消，"
                "该方法在这种退化配置下无法保证覆盖面积相等。"
            ),
            details={"crossing_ids": sorted(cid for ids in groups for cid in ids)},
            hints=("把丝带错开、减小 offset，或改用描边后端（它按中心线切口，不受该限制）。",),
        ))

    ribbon_parts: list[Any] = [
        strip.band for group in strips.values() for strip in group if not strip.band.is_empty
    ]
    ribbon_parts.extend(
        band for path_id, band in bands.items() if path_id not in strips and not band.is_empty
    )
    painted_parts: list[Any] = [
        visible_strip[strip.strip_id] for group in strips.values() for strip in group
        if not visible_strip[strip.strip_id].is_empty
    ]
    painted_parts.extend(
        band for path_id, band in visible_band.items()
        if path_id not in strips and not band.is_empty
    )
    regions: list[RibbonRegion] = []
    owners: set[str] = set()
    hole_count_total = 0
    for path in paths:
        if strips.get(path.path_id):
            parts = [
                (strip.strip_id, visible_strip[strip.strip_id]) for strip in strips[path.path_id]
                if not visible_strip[strip.strip_id].is_empty
            ]
        else:
            band = visible_band.get(path.path_id)
            parts = [(path.path_id, band)] if band is not None and not band.is_empty else []
        for node, geometry in parts:
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
                label = path.path_id if node == path.path_id else node
                owners.add(node)
                hole_count_total += len(holes)
                regions.append(RibbonRegion(
                    region_id=f"{label}.region{index}",
                    path_id=path.path_id,
                    exterior=RegionRing(points=_ring_points(polygon.exterior), role="exterior"),
                    holes=holes,
                    area=float(polygon.area),
                    draw_index=draw_index.get(node, 0),
                ))

    band_area = float(sum(band.area for band in bands.values()))
    union_area = float(unary_union(ribbon_parts).area) if ribbon_parts else 0.0
    painted_area = float(unary_union(painted_parts).area) if painted_parts else 0.0
    region_area_sum = float(sum(region.area for region in regions))
    tolerance = max(area_tolerance * max(union_area, 1.0), 1e-12)
    whole_union = float(unary_union(list(bands.values())).area) if bands else 0.0
    if strips and abs(union_area - whole_union) > tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-SECTION-SEAM",
            severity=Severity.INFO,
            message=(
                "分段并集与整条丝带并集有差异：某个切分点落在折线顶点上，两段之间少了"
                "拐角连接的面积。"
            ),
            details={"section_area": union_area, "band_area": whole_union},
            hints=("提高采样密度让交叉落在段中，或减小 offset，可让差异消失。",),
        ))
    if ribbon_parts and abs(painted_area - union_area) > tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-AREA-MISMATCH",
            severity=Severity.WARNING,
            message=(
                "可见区域总面积与丝带并集面积不一致：某处被切除的区域没有被上方丝带覆盖"
                "（通常是三条以上丝带在非交叉点处互相重叠）。"
            ),
            details={
                "painted_area": painted_area,
                "union_area": union_area,
                "difference": painted_area - union_area,
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
        painted_area=painted_area,
        region_area_sum=region_area_sum,
        face_walk={
            "backend": "boolean",
            # This backend walks path bands (and the sections of a self-crossing path),
            # not the faces of a planar arrangement: ``node_kind`` says which it is.
            "node_kind": "band",
            "node_count": len(order_nodes),
            "band_count": len(bands),
            "section_count": sum(len(group) for group in strips.values()),
            "crossing_count": len(weavable),
            "cut_count": cut_count,
            "section_cut_count": section_cut_count,
            "missing_assignment_count": missing_assignment_count,
            "self_crossing_count": self_crossing_count,
            "empty_band_count": empty_band_count,
            "lens_miss_count": lens_miss_count,
            "congested": bool(congested),
            "hole_count": hole_count_total,
            # This backend's traversal unit is a band (or a section), so it counts the
            # region polygons it produced rather than arrangement faces.
            "region_polygon_count": len(regions),
            "owner_count": len(owners),
            "removed_area": float(removed_area),
            **walk.as_payload("steps"),
        },
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
