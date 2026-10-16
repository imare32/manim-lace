"""Face-based planar arrangement backend (the half-edge side of SPEC FR-054).

The Boolean backend cuts ribbons: it removes the overlap at every crossing from the
ribbon that is under, and section overlaps plus painter order handle the cases a single
band cannot express. This backend does not cut anything. It builds the planar
arrangement of all ribbon boundaries (GEOS nodes them, then ``polygonize`` extracts the
faces), decides for every face which strand is visible there, and unions the faces of
each strand.

The consequences are the ones a planar embedding is supposed to have:

- regions never overlap, so ``region_area_sum == painted_area`` exactly;
- the visible arrangement is decided per face by the crossing assignments, not by paint
  order, so an under strand simply does not own the overlap and its cut appears as a real
  boundary of its region;
- every point of the ribbon union belongs to exactly one owner, so
  ``painted_area == union_area`` holds even where several crossings share one point.

What is left to decide rather than compute is reported: a face covered by strands that do
not cross there (parallel overlap), or by crossings whose assignments contradict each
other at the same point, is resolved deterministically by the path order and reported as
``REGION-CONFLICTING-OVERLAP`` / ``REGION-OFF-CROSSING-OVERLAP``.

Shapely is imported inside the entry point, so the core stays importable without the
optional ``geometry`` extra.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CapStyle, CrossingEvent, JoinStyle, PolylinePath, WeaveTopology
from ..tracing import BoundedRecords
from .order import paint_order
from .regions import (
    RegionRenderResult,
    RegionRing,
    RibbonRegion,
    _arm_strip,
    _covered_area,
    _cut_lines,
    _hole_roles,
    _local_lens,
    _polygons,
    _require_shapely,
    _ring_points,
    _StripBuilder,
    build_bands,
    build_sections,
    mark_flush_edges,
)

__all__ = ["render_arrangement_regions"]


def _cells(
    geometries: dict[str, Any], line_class: Any, polygonize: Any, unary_union: Any, tolerance: float
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """Faces of the arrangement of the given ribbon boundaries.

    Every geometry contributes its rings, and section boundaries are included next to the
    whole-band boundaries: that is what puts a real edge through the overlap of a
    self-crossing, where the band silhouette alone has none.

    ``polygonize`` returns one polygon per noded ring, so nested rings overlap by
    construction: a face is reduced here to the part that is not covered by the smaller
    faces inside it, which turns an annulus back into a face with a hole. Faces smaller
    than ``tolerance`` are slivers and are returned separately.

    The third return value counts what this walk did, for the fine-grained trace:
    ``raw_face_count`` faces came out of ``polygonize``, ``sliver_count`` of them were too
    small to keep, ``collapsed_count`` became empty after subtracting the smaller faces
    nested inside them, and ``subtraction_count`` differences were actually computed.
    """
    boundaries = []
    for geometry in geometries.values():
        for polygon in _polygons(geometry):
            boundaries.append(line_class(polygon.exterior.coords))
            for ring in polygon.interiors:
                boundaries.append(line_class(ring.coords))
    stats: dict[str, Any] = {
        "raw_face_count": 0,
        "sliver_count": 0,
        "sliver_area": 0.0,
        "collapsed_count": 0,
        "subtraction_count": 0,
    }
    if not boundaries:
        return [], [], stats
    faces = sorted(polygonize(unary_union(boundaries)), key=lambda face: -face.area)
    stats["raw_face_count"] = len(faces)
    cells: list[Any] = []
    slivers: list[Any] = []
    for index, face in enumerate(faces):
        if face.area <= tolerance:
            slivers.append(face)
            stats["sliver_count"] += 1
            stats["sliver_area"] += float(face.area)
            continue
        cell = face
        for smaller in faces[index + 1:]:
            if cell.is_empty:
                break
            if not _boxes_meet(cell.bounds, smaller.bounds):
                continue
            if cell.contains(smaller.representative_point()):
                cell = cell.difference(smaller)
                stats["subtraction_count"] += 1
        if cell.is_empty or cell.area <= tolerance:
            stats["collapsed_count"] += 1
            continue
        cells.append(cell)
    return cells, slivers, stats


def _boxes_meet(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    return not (
        second[2] < first[0] or second[0] > first[2]
        or second[3] < first[1] or second[1] > first[3]
    )


def _node_geometry(faces: list[Any], unary_union: Any) -> Any:
    """One geometry for a node's faces, keeping every one of them.

    The faces of a planar arrangement are interior-disjoint, so their union has
    exactly the sum of their areas. The overlay engine does not always deliver
    that: a face that only *touches* another along an edge can be dropped, and
    which of the two survives depends on the operand order. Measured on a
    crossing whose two cut chords meet on a band's lateral edge (``n = 7`` CA):
    the union lost a 2.3e-3 face and left a hole in the painted ribbon, while the
    same faces unioned in the other order kept it.

    The area check catches the loss. When the union cannot be trusted the faces
    are kept as they are, and the renderer draws them as the separate regions
    they are — their shared edge is interior to one colour and gets marked flush
    like any other section boundary, so nothing is stroked that should not be.
    """
    from shapely.geometry import MultiPolygon

    if len(faces) == 1:
        return faces[0]
    expected = float(sum(float(face.area) for face in faces))
    merged = unary_union(faces)
    if abs(float(merged.area) - expected) <= 1e-9 * max(expected, 1.0):
        return merged
    return MultiPolygon(faces)


def render_arrangement_regions(
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
    """Build ribbon regions from the planar arrangement of the ribbon boundaries.

    The arguments mean exactly what they mean for the Boolean backend, so the two can be
    compared on the same input; ``render_mode='ribbon'`` picks between them with
    ``ribbon_backend``.
    """
    if not np.isfinite(offset) or offset <= 0:
        raise ValueError("offset must be positive and finite")
    if cap_style not in ("butt", "round", "square"):
        raise ValueError("cap_style must be 'butt', 'round' or 'square'")
    if join not in ("miter", "bevel", "round"):
        raise ValueError("join must be 'miter', 'bevel' or 'round'")
    if not np.isfinite(miter_limit) or miter_limit <= 0:
        raise ValueError("miter_limit must be positive and finite")
    if not np.isfinite(area_tolerance) or area_tolerance < 0:
        raise ValueError("area_tolerance must be finite and non-negative")
    LineString, Point, _Polygon, unary_union, _make_valid, orient = _require_shapely()
    from shapely.ops import polygonize

    diagnostics: list[Diagnostic] = []
    bands, source_hole_areas = build_bands(
        paths, offset=offset, cap_style=cap_style, join=join,
        miter_limit=miter_limit, diagnostics=diagnostics,
    )
    weavable = [crossing for crossing in crossings if crossing.kind == "transverse"]
    self_crossings = [crossing for crossing in weavable if crossing.path_a == crossing.path_b]
    sections = build_sections(
        paths, bands, self_crossings, offset=offset, cap_style=cap_style, join=join,
        miter_limit=miter_limit, line_class=LineString, point_class=Point,
        polygon_class=_Polygon, unary_union=unary_union,
    )

    # A node is what a face can be owned by: a whole path, or one section when the path
    # crosses itself (its two passes must stay separate owners).
    node_band: dict[str, Any] = {}
    node_path: dict[str, str] = {}
    for path in paths:
        band = bands.get(path.path_id)
        if band is None:
            continue
        group = sections.get(path.path_id)
        if group:
            for strip in group:
                node_band[strip.strip_id] = strip.band
                node_path[strip.strip_id] = path.path_id
        else:
            node_band[path.path_id] = band
            node_path[path.path_id] = path.path_id

    path_edges: list[tuple[str, str]] = []
    for crossing in weavable:
        if crossing.path_a == crossing.path_b:
            continue
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            continue
        under = crossing.path_a if assignment.under_side == "a" else crossing.path_b
        over = crossing.path_b if assignment.under_side == "a" else crossing.path_a
        path_edges.append((under, over))
    # A cyclic over/under relation has no consistent painter order, but this backend does
    # not need one: every face belongs to exactly one owner, so nothing depends on the
    # draw order. The layer numbers stay available for renderers that want them.
    # Congestion is reported but, unlike in the Boolean backend, it cannot change the
    # result here: ownership is decided per face instead of by paint order.
    layers, congested = paint_order([path.path_id for path in paths], path_edges)

    # The lens of a crossing is the local footprint of the over ribbon; a face inside it
    # is owned by the strand on top, which is exactly what the assignment says. A
    # self-crossing has no second path to name, so the over side is named by its sections
    # instead: the ones that meet the path at the over arc. Handing the lens to whichever
    # section sorts first can give it to the under pass, which reverses the weave there
    # and strokes the notch on the ribbon that is supposed to be on top.
    lenses: dict[str, Any | None] = {}
    over_sections_of: dict[str, tuple[str, ...]] = {}
    over_path_of: dict[str, str] = {}
    approximated = 0
    for crossing in weavable:
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            continue
        over = crossing.path_b if assignment.under_side == "a" else crossing.path_a
        under = crossing.path_a if assignment.under_side == "a" else crossing.path_b
        over_path_of[crossing.crossing_id] = over
        if crossing.path_a == crossing.path_b:
            path = {item.path_id: item for item in paths}[crossing.path_a]
            over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
            over_sections_of[crossing.crossing_id] = tuple(
                strip.strip_id for strip in _StripBuilder.adjacent(
                    sections.get(crossing.path_a, []), over_arc,
                    closed=path.closed, length=float(path.length),
                )
            )
            window = min(
                4.0 * offset / max(abs(crossing.sin_angle), 0.05) + 4.0 * offset,
                float(path.length) / 2.0,
            )
            strips = [
                _arm_strip(
                    path, arc, window, offset=offset, join=join,
                    miter_limit=miter_limit, line_class=LineString,
                )
                for arc in (
                    crossing.s_a if assignment.under_side == "a" else crossing.s_b,
                    crossing.s_b if assignment.under_side == "a" else crossing.s_a,
                )
            ]
            lens = _local_lens(strips[0], strips[1], crossing.point, Point)
            expected = 4.0 * offset * offset / max(abs(crossing.sin_angle), 1e-6)
            if lens is not None and abs(float(lens.area) - expected) > 0.1 * expected:
                approximated += 1
            lenses[crossing.crossing_id] = lens
            continue
        first, second = bands.get(under), bands.get(over)
        lenses[crossing.crossing_id] = (
            _local_lens(first, second, crossing.point, Point)
            if first is not None and second is not None else None
        )

    union_area = _covered_area(list(bands.values()))
    tolerance = max(area_tolerance * max(union_area, 1.0), 1e-18)
    cells, slivers, cell_stats = _cells(node_band, LineString, polygonize, unary_union, tolerance)

    walk = BoundedRecords()
    owners: dict[str, list[Any]] = {}
    conflicting = 0
    off_crossing = 0
    uncovered = 0
    single_owner_count = 0
    lens_decided_count = 0
    for cell in cells:
        probe = cell.representative_point()
        covering = [
            node_id for node_id, band in node_band.items()
            if band.contains(probe) or band.covers(probe) or band.distance(probe) <= tolerance
        ]
        if not covering:
            uncovered += 1  # a face of the arrangement that no ribbon covers
            walk.add({"kind": "face", "decision": "uncovered", "owner": None,
                      "area": float(cell.area), "covering_count": 0})
            continue
        decision = "single"
        if len(covering) == 1:
            owner = covering[0]
            single_owner_count += 1
        else:
            decisions: list[str] = []
            for crossing in weavable:
                lens = lenses.get(crossing.crossing_id)
                if lens is None or not lens.contains(probe):
                    continue
                over_sections = over_sections_of.get(crossing.crossing_id)
                if over_sections:
                    # A self-crossing: the over side is the set of sections that meet the
                    # path at the over arc, exactly the passes the Boolean backend leaves
                    # whole there. Only when none of them covers this face (a window too
                    # short for the overlap) does the choice fall back to the path order.
                    decisions.extend(node for node in covering if node in over_sections)
                    continue
                over = over_path_of[crossing.crossing_id]
                decisions.extend(node for node in covering if node_path[node] == over)
            if decisions:
                distinct = sorted(set(decisions))
                # Two sections of the same path are the same strand for this decision:
                # only genuinely different paths make the face contradictory.
                contradictory = len({node_path[node] for node in distinct}) > 1
                if contradictory:
                    conflicting += 1
                owner = min(distinct, key=lambda node: (-layers[node_path[node]], node))
                decision = "conflicting-lens" if contradictory else "lens"
                lens_decided_count += 1
            else:
                if len({node_path[node] for node in covering}) > 1:
                    off_crossing += 1
                owner = min(covering, key=lambda node: (-layers[node_path[node]], node))
                decision = "off-crossing"
        walk.add({"kind": "face", "decision": decision, "owner": owner,
                  "area": float(cell.area), "covering_count": len(covering)})
        owners.setdefault(owner, []).append(cell)
    for face in slivers:
        walk.add({"kind": "sliver", "decision": "dropped", "owner": None, "area": float(face.area)})

    regions: list[RibbonRegion] = []
    for node_id, faces in owners.items():
        geometry = _node_geometry(faces, unary_union)
        path_id = node_path[node_id]
        for index, polygon in enumerate(_polygons(geometry)):
            polygon = orient(polygon, 1.0)
            holes = [
                RegionRing(points=_ring_points(ring), role=role)
                for ring, role in zip(
                    polygon.interiors,
                    _hole_roles(polygon, source_hole_areas.get(path_id, [])),
                    strict=True,
                )
            ]
            regions.append(RibbonRegion(
                region_id=f"{node_id}.region{index}",
                path_id=path_id,
                exterior=RegionRing(points=_ring_points(polygon.exterior), role="exterior"),
                holes=holes,
                area=float(polygon.area),
                draw_index=layers.get(path_id, 0),
            ))
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    for index, region in enumerate(ordered):
        region.draw_index = index

    # The faces are interior-disjoint, so their sum *is* the painted area. Summing
    # keeps the accounting honest where the overlay engine would drop a face that
    # only touches another along an edge (see :func:`_node_geometry`).
    painted_area = (
        float(sum(float(face.area) for faces in owners.values() for face in faces))
        if owners else 0.0
    )
    region_area_sum = float(sum(region.area for region in regions))
    if slivers:
        diagnostics.append(Diagnostic(
            code="REGION-DROPPED-SLIVER",
            severity=Severity.INFO,
            message=(
                f"平面剖分产生了 {len(slivers)} 个面积小于容差的碎片面，已忽略"
                "（通常是两条丝带近乎相切造成的）。"
            ),
            details={"count": len(slivers), "total_area": float(sum(f.area for f in slivers))},
            hints=("减小 offset 或提高采样密度可减少相切碎片。",),
        ))
    if conflicting:
        diagnostics.append(Diagnostic(
            code="REGION-CONFLICTING-OVERLAP",
            severity=Severity.WARNING,
            message=(
                f"{conflicting} 个面同时落在多个上下关系相反的交叉内（通常是多个交叉共点）；"
                "这些面按路径顺序确定性归给其中一条股线。"
            ),
            details={"face_count": conflicting},
            hints=("移动几何让交叉不再共点；布尔后端在这种情况下会出现面积不守恒。",),
        ))
    if off_crossing:
        diagnostics.append(Diagnostic(
            code="REGION-OFF-CROSSING-OVERLAP",
            severity=Severity.INFO,
            message=(
                f"{off_crossing} 个面被多条丝带覆盖但附近没有交叉（平行或近乎平行重叠）；"
                "按路径顺序确定性归给其中一条。"
            ),
            details={"face_count": off_crossing},
        ))
    if approximated:
        diagnostics.append(Diagnostic(
            code="REGION-LENS-APPROXIMATION",
            severity=Severity.INFO,
            message=(
                f"{approximated} 个自交的重叠区与理论值偏差超过 10%：该处理的局部窗口"
                "不足以完整覆盖重叠（浅角或分段过短），面归属可能不精确。"
            ),
            details={"crossing_count": approximated},
            hints=("提高采样密度或减小 offset 可让窗口完整包含重叠区。",),
        ))
    if abs(painted_area - union_area) > tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-AREA-MISMATCH",
            severity=Severity.WARNING,
            message="面归属后总面积与丝带并集面积不一致；剖分结果不完整。",
            details={
                "painted_area": painted_area,
                "union_area": union_area,
                "difference": painted_area - union_area,
                "tolerance": tolerance,
            },
        ))
    covered_lenses = [lens for lens in lenses.values() if lens is not None]
    hidden_area = _covered_area(covered_lenses)
    weave_edges: list[tuple[np.ndarray, np.ndarray]] = []
    for lens in covered_lenses:
        for polygon in (lens.geoms if lens.geom_type != "Polygon" else [lens]):
            ring = np.asarray(polygon.exterior.coords, dtype=float)[:, :2]
            for start, end in zip(ring[:-1], ring[1:], strict=False):
                weave_edges.append((start, end))
    flush_edge_count = mark_flush_edges(
        regions,
        cuts=_cut_lines(paths, sections, offset=offset),
        weave=weave_edges,
        node_bands=node_band,
    )
    return RegionRenderResult(
        regions=regions,
        diagnostics=diagnostics,
        removed_area=hidden_area,
        band_area=float(sum(band.area for band in bands.values())),
        union_area=union_area,
        painted_area=painted_area,
        region_area_sum=region_area_sum,
        face_walk={
            "backend": "arrangement",
            # The walk visits the faces of the planar arrangement, not path bands.
            "node_kind": "face",
            "node_count": len(node_band),
            "band_count": len(bands),
            "section_count": sum(len(group) for group in sections.values()),
            "crossing_count": len(weavable),
            "congested": bool(congested),
            "face_count": sum(len(faces) for faces in owners.values()),
            "owner_count": len(owners),
            "removed_area": float(hidden_area),
            "single_owner_count": single_owner_count,
            "lens_decided_count": lens_decided_count,
            "conflicting_count": conflicting,
            "off_crossing_count": off_crossing,
            "uncovered_count": uncovered,
            "flush_edge_count": flush_edge_count,
            **cell_stats,
            **walk.as_payload("steps"),
        },
    )
