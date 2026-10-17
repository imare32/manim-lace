"""Experimental hybrid ribbon backend.

The Boolean backend has the right occlusion model: later painted sections cover
earlier fills and strokes, so a long boundary that is physically underneath another
pass stays hidden.  Its weakness is local: a narrow section window can leave a small
piece of a lens side uncovered.  The arrangement backend computes those local lens
boundaries more directly, but its faces are interior-disjoint; strokes cannot be
hidden by a later fill, so the same boundary can show as a long line through a ribbon.

This backend keeps the Boolean regions as the visible layer and uses the arrangement
only as a source of conservative local repairs:

* a *visible Boolean open end* — a stroke end that stops inside the ribbon rather than
  joining another stroke or sitting under a later fill — is linked to the next Boolean
  boundary it meets along a straight segment, but only when the arrangement's visible
  edges cover that whole segment end to end (within a hairline normal band).  The link
  is emitted as a top-layer ``outline_edges`` bridge, so it closes the V-shaped notches
  the Boolean cut leaves without ever promoting a full arrangement ring;
* Boolean ``outline_edges`` that are sub-pixel *and* sit inside a Boolean fill are
  dropped: they are the isolated black specks the Boolean overlay draws on top of its own
  fill, and the hybrid exists to remove exactly those;
* when the Boolean union really does not cover the arrangement union, the missing
  arrangement faces are returned as fill-only patches below the Boolean layer.

It is deliberately experimental.  The Boolean region's ``flush_edges`` and paint order
remain the authority for occlusion; the hybrid layer never promotes a full arrangement
region ring to an outline.  The only Boolean ink it removes is the sub-pixel interior
speck above -- the flush-seam spurs are already gone from ``Boolean.outline_edges``,
filtered by ``missing_weave_outlines`` itself.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CapStyle, CrossingEvent, JoinStyle, PolylinePath, WeaveTopology
from .arrangement import render_arrangement_regions
from .regions import (
    OutlineEdge,
    RegionRenderResult,
    RegionRing,
    RibbonRegion,
    _polygons,
    _require_shapely,
    render_region_geometry,
)

__all__ = ["render_hybrid_regions"]


def _polygon(region: RibbonRegion, polygon_class: Any) -> Any:
    return polygon_class(
        np.asarray(region.exterior.points, dtype=float),
        [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
    )


def _outward(strokes: list[Any], index: int, vertex: np.ndarray) -> np.ndarray | None:
    """The direction a stroke leaves ``vertex`` in."""
    _region_id, _edge_index, start, end = strokes[index]
    other = end if float(np.hypot(*(start - vertex))) <= float(np.hypot(*(end - vertex))) else start
    direction = other - vertex
    span = float(np.hypot(*(direction)))
    return direction / span if span > 1e-12 else None


def _boolean_open_ends(
    boolean: RegionRenderResult,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[Any], Any]:
    """Visible stroke ends that stop inside the Boolean ribbon.

    This is intentionally the same local rule as ``benchmarks.weave_audit.dangling_ends``:
    a duplicate copy of the same outgoing line is not a join, a different outgoing line or
    a stroke passing through the vertex is one, and an end buried under a later fill is
    invisible. The returned ``(point, outward)`` pairs are the gaps a repair may close.
    """
    from shapely.geometry import LineString, Point, Polygon
    from shapely.strtree import STRtree

    strokes: list[tuple[str, int, np.ndarray, np.ndarray]] = []
    for region in boolean.regions:
        points = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index, (start, end) in enumerate(zip(points[:-1], points[1:], strict=False)):
            if index in flush:
                continue
            if float(np.hypot(*(end - start))) > 1e-12:
                strokes.append((region.region_id, index, start, end))
    lines = [LineString([tuple(start), tuple(end)]) for _id, _index, start, end in strokes]
    stroke_tree = STRtree(lines)

    fills = {
        region.region_id: Polygon(
            region.exterior.points,
            [hole.points for hole in region.holes] or None,
        )
        for region in boolean.regions
    }
    ordered = sorted(boolean.regions, key=lambda region: (region.draw_index, region.region_id))
    index_of = {region.region_id: index for index, region in enumerate(ordered)}
    fill_tree = STRtree([fills[region.region_id] for region in ordered])

    def topmost(point: Point) -> int | None:
        best: int | None = None
        for index in fill_tree.query(point):
            if fills[ordered[index].region_id].intersects(point):
                best = index if best is None else max(best, index)
        return best

    endings: dict[tuple[float, float], list[int]] = {}
    for index, (_id, _edge_index, start, end) in enumerate(strokes):
        for vertex in (start, end):
            key = (round(float(vertex[0]), 12), round(float(vertex[1]), 12))
            endings.setdefault(key, []).append(index)

    open_ends: list[tuple[np.ndarray, np.ndarray]] = []
    for key, owners in endings.items():
        vertex = np.asarray(key, dtype=float)
        point = Point(float(vertex[0]), float(vertex[1]))
        candidates = [
            index for index in stroke_tree.query(point.buffer(1e-4))
            if index not in owners
        ]
        if any(lines[index].distance(point) <= 1e-4 for index in candidates):
            continue
        for owner in owners:
            if strokes[owner][0] == "__outline__":
                continue
            outward = _outward(strokes, owner, vertex)
            if outward is None:
                continue
            joined = False
            for other in owners:
                if other == owner:
                    continue
                other_outward = _outward(strokes, other, vertex)
                if other_outward is not None and float(np.dot(outward, other_outward)) <= 0.999:
                    joined = True
                    break
            if joined:
                continue
            normal = np.array([-outward[1], outward[0]])
            outer = topmost(Point(*(vertex + normal * 2e-4)))
            inner = topmost(Point(*(vertex - normal * 2e-4)))
            our = index_of[strokes[owner][0]]
            if (
                outer is not None
                and inner is not None
                and min(outer, inner) > our
            ):
                continue
            if not any(float(np.hypot(*(vertex - found[0]))) <= 1e-9 for found in open_ends):
                open_ends.append((vertex, outward))
    return open_ends, lines, stroke_tree


def _arrangement_bridge_edges(
    boolean: RegionRenderResult,
    arrangement: RegionRenderResult,
    *,
    offset: float,
    tolerance: float,
) -> tuple[list[OutlineEdge], int]:
    """Close a Boolean open end along an arrangement-supported boundary.

    This is the actual hybrid rule.  Start at a visible, unjoined Boolean stroke end,
    walk in the direction opposite the existing stroke, and find the first Boolean
    boundary that direction reaches.  The straight connector is only accepted when
    arrangement centerlines cover it end to end (within a small normal tolerance); the
    repair is then emitted as one straight connection between the two Boolean boundaries.

    The walk is a hairline *band*, not an ideal ray: the stroke direction at an open end
    and the arrangement boundary continuing it can differ by a fraction of a degree,
    which is invisible at the stroke scale but, over a connector a few percent of an
    offset long, is enough for an ideal ray to slip past the next Boolean stroke and
    report no bridge at all.  The band turns that miss into a hit while still rejecting
    any stroke whose nearest point is not ahead of the open end and inside the band.

    In particular, an arrangement edge is never added because it merely happens to be
    short.  Such an edge is how the first hybrid draft produced isolated black dots.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points

    open_ends, stroke_lines, stroke_tree = _boolean_open_ends(boolean)
    if not open_ends:
        return [], 0
    arrangement_segments: list[tuple[np.ndarray, np.ndarray]] = []
    for region in arrangement.regions:
        points = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index, (start, end) in enumerate(zip(points[:-1], points[1:], strict=False)):
            if index in flush:
                continue
            if float(np.hypot(*(end - start))) > 1e-12:
                arrangement_segments.append((start, end))
    if not arrangement_segments:
        return [], 0

    max_bridge = 0.5 * offset
    normal_tolerance = max(tolerance, 0.02 * offset)
    line_class = LineString
    bridges: list[OutlineEdge] = []
    used_ends: set[int] = set()

    # A pair of open ends a fraction of a pixel apart is an internal seam, not a
    # silhouette. Boolean already carries an explicit overlay there, and drawing it
    # after the fills produces the short black spur this backend is meant to remove.
    # Mark the pair as handled so it is not ray-bridged, but do not emit ink for it.
    for first_index, (first_start, first_outward) in enumerate(open_ends):
        for second_index in range(first_index + 1, len(open_ends)):
            second_start, second_outward = open_ends[second_index]
            delta = second_start - first_start
            span = float(np.hypot(*(delta)))
            if span <= tolerance or span > 0.05 * offset:
                continue
            direction_between = delta / span
            if float(np.dot(first_outward, direction_between)) > -0.95:
                continue
            if float(np.dot(second_outward, -direction_between)) > -0.95:
                continue
            used_ends.update((first_index, second_index))

    for open_index, (start, outward) in enumerate(open_ends):
        if open_index in used_ends:
            continue
        direction = -outward
        normal = np.array([-direction[1], direction[0]])
        end = start + direction * max_bridge
        ray = line_class([tuple(start), tuple(end)])
        # The stroke direction at an open end and the arrangement boundary that continues
        # it can differ by a fraction of a degree. That is invisible at the stroke scale,
        # but over a bridge a few percent of an offset long it is enough for an ideal ray
        # to slip past the next Boolean stroke and report no bridge at all. Search a
        # hairline band instead, and accept a stroke only when its nearest point really
        # lies ahead of the open end and within that band. Strokes incident at the open
        # end are the end's own ink and never count as the far side.
        here = Point(float(start[0]), float(start[1]))
        incident = {
            index
            for index in stroke_tree.query(here.buffer(tolerance))
            if stroke_lines[index].distance(here) <= tolerance
        }
        band = ray.buffer(normal_tolerance, cap_style=2)
        hits: list[tuple[float, np.ndarray]] = []
        for index in stroke_tree.query(band):
            if index in incident:
                continue
            line = stroke_lines[index]
            if line.intersection(band).is_empty:
                continue
            point = np.asarray(nearest_points(line, ray)[0].coords[0], dtype=float)
            delta = point - start
            along = float(np.dot(delta, direction))
            if along <= 1e-7 or along > max_bridge + tolerance:
                continue
            if abs(float(np.dot(delta, normal))) > normal_tolerance + tolerance:
                continue
            hits.append((along, point))
        if not hits:
            continue
        distance_to_boundary, boundary_point = min(hits, key=lambda item: item[0])
        if distance_to_boundary <= tolerance:
            continue
        intervals: list[tuple[float, float]] = []
        for first, second in arrangement_segments:
            if abs(float(np.dot(first - start, normal))) > normal_tolerance:
                continue
            if abs(float(np.dot(second - start, normal))) > normal_tolerance:
                continue
            segment = second - first
            span = float(np.hypot(*(segment)))
            if span <= tolerance:
                continue
            if abs(float(np.dot(segment / span, direction))) < 0.995:
                continue
            low = max(min(float(np.dot(first - start, direction)),
                          float(np.dot(second - start, direction))), 0.0)
            high = min(max(float(np.dot(first - start, direction)),
                           float(np.dot(second - start, direction))), distance_to_boundary)
            if high > low + tolerance:
                intervals.append((low, high))
        if not intervals:
            continue
        intervals.sort()
        merged: list[tuple[float, float]] = []
        for low, high in intervals:
            if merged and low <= merged[-1][1] + normal_tolerance:
                merged[-1] = (merged[-1][0], max(merged[-1][1], high))
            else:
                merged.append((low, high))
        # The arrangement must carry the boundary from the open end all the way to
        # the next Boolean boundary. A two-percent shortfall is allowed only for the
        # final numerical intersection; a real hole in the evidence rejects the ray.
        if merged[0][0] > normal_tolerance:
            continue
        if merged[-1][1] < distance_to_boundary - normal_tolerance:
            continue
        if merged[-1][1] - merged[0][0] < 0.80 * distance_to_boundary:
            continue
        first = (float(start[0]), float(start[1]))
        second = (
            float(boundary_point[0]),
            float(boundary_point[1]),
        )
        key = (first, second) if first <= second else (second, first)
        if any(
            (edge.start, edge.end) == key or (edge.end, edge.start) == key
            for edge in bridges
        ):
            continue
        bridges.append(OutlineEdge(first, second))

    return bridges, len(arrangement_segments)


def _hybrid_outline_edges(
    boolean: RegionRenderResult,
    arrangement: RegionRenderResult,
    *,
    offset: float,
    tolerance: float,
) -> tuple[list[OutlineEdge], int, int]:
    """Boolean overlays minus its specks, plus the open-end bridges.

    Returns the overlay edges, the bridge count and the arrangement visible-edge count.
    """
    from shapely.geometry import Point, Polygon

    polygons = [
        Polygon(
            region.exterior.points,
            [hole.points for hole in region.holes] or None,
        )
        for region in boolean.regions
    ]
    subpixel_limit = 0.05 * offset
    base: list[OutlineEdge] = []
    for edge in boolean.outline_edges:
        start = np.asarray(edge.start, dtype=float)
        end = np.asarray(edge.end, dtype=float)
        length = float(np.hypot(*(end - start)))
        midpoint = Point(*(0.5 * (start + end)))
        if (
            length <= subpixel_limit
            and any(polygon.contains(midpoint) for polygon in polygons)
        ):
            continue
        base.append(edge)
    bridges, arrangement_edge_count = _arrangement_bridge_edges(
        boolean,
        arrangement,
        offset=offset,
        tolerance=tolerance,
    )
    base.extend(bridges)
    return base, len(bridges), arrangement_edge_count


def _missing_patches(
    arrangement: RegionRenderResult,
    boolean: RegionRenderResult,
    *,
    area_tolerance: float,
) -> tuple[list[RibbonRegion], float]:
    """Arrangement-owned faces that the Boolean union genuinely missed."""
    from shapely.errors import GEOSException
    from shapely.strtree import STRtree

    _LineString, _Point, Polygon, _unary, make_valid, _orient = _require_shapely()

    def valid(geometry: Any) -> Any:
        return geometry if geometry.is_valid else make_valid(geometry)

    boolean_polygons = [valid(_polygon(region, Polygon)) for region in boolean.regions]
    if not boolean_polygons:
        return [], 0.0
    covered_tree = STRtree(boolean_polygons)
    union_area = max(float(arrangement.union_area), 1.0)
    minimum = max(float(area_tolerance) * union_area, 1e-12)
    patches: list[RibbonRegion] = []
    total = 0.0

    def difference(first: Any, second: Any) -> Any:
        """A conservative difference that survives a local invalid-hole report."""
        try:
            return first.difference(second)
        except GEOSException:
            return valid(first).buffer(0).difference(valid(second).buffer(0))

    for region in arrangement.ordered_regions():
        missing = valid(_polygon(region, Polygon))
        # Subtracting the Boolean faces one at a time is slower than one `unary_union`,
        # but it avoids GEOS's all-at-once hole assignment failure on random-walk
        # networks with hundreds of touching pieces. The spatial index keeps that
        # pairwise path to the faces whose bounds actually meet this arrangement face.
        for index in covered_tree.query(missing):
            if missing.is_empty:
                break
            missing = difference(missing, boolean_polygons[index])
        for index, polygon in enumerate(_polygons(missing)):
            if polygon.is_empty or float(polygon.area) <= minimum:
                continue
            holes = [RegionRing(points=np.asarray(ring.coords), role="occlusion")
                     for ring in polygon.interiors]
            patches.append(RibbonRegion(
                region_id=f"hybrid:{region.region_id}.patch{index}",
                path_id=region.path_id,
                exterior=RegionRing(
                    points=np.asarray(polygon.exterior.coords, dtype=float),
                    role="exterior",
                ),
                holes=holes,
                area=float(polygon.area),
                draw_index=region.draw_index,
            ))
            total += float(polygon.area)
    return patches, total


def render_hybrid_regions(
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
    """Build the experimental Boolean-occlusion + arrangement-repair result."""
    boolean = render_region_geometry(
        paths,
        crossings,
        topology,
        offset=offset,
        cap_style=cap_style,
        join=join,
        miter_limit=miter_limit,
        area_tolerance=area_tolerance,
    )
    arrangement = render_arrangement_regions(
        paths,
        crossings,
        topology,
        offset=offset,
        cap_style=cap_style,
        join=join,
        miter_limit=miter_limit,
        area_tolerance=area_tolerance,
    )
    tolerance = max(float(area_tolerance), 1e-9)
    patches, patch_area = _missing_patches(
        arrangement, boolean, area_tolerance=float(area_tolerance)
    )
    outline_edges, bridge_count, arrangement_edge_count = (
        _hybrid_outline_edges(
            boolean,
            arrangement,
            offset=offset,
            tolerance=tolerance,
        )
    )
    diagnostics = [
        *boolean.diagnostics,
        *arrangement.diagnostics,
        Diagnostic(
            code="REGION-HYBRID-EXPERIMENTAL",
            severity=Severity.INFO,
            message=(
                "实验性 hybrid 后端：填充与主要遮挡沿用 boolean 后端的绘制顺序，"
                "平面剖分只提供 Boolean 断头到下一段 Boolean 边界的连续接合证据，"
                "以及布尔并集缺失面的局部补丁。"
            ),
            details={
                "boolean_outline_edges": len(boolean.outline_edges),
                "arrangement_visible_edges": arrangement_edge_count,
                "bridge_edges": bridge_count,
                "patch_count": len(patches),
                "patch_area": patch_area,
            },
            hints=(
                "该后端仍是实验性接口；需要稳定的互斥默认结果时请使用 boolean。",
                "若桥接仍误画长线，请把 arrangement_visible_edges 和 bridge_edges 交给人眼审查。",
            ),
        ),
    ]
    return RegionRenderResult(
        regions=boolean.regions,
        diagnostics=diagnostics,
        removed_area=boolean.removed_area,
        band_area=boolean.band_area,
        union_area=max(float(boolean.union_area), float(arrangement.union_area)),
        painted_area=float(arrangement.painted_area),
        region_area_sum=float(boolean.region_area_sum + patch_area),
        face_walk={
            **boolean.face_walk,
            "backend": "hybrid",
            "base_backend": "boolean",
            "repair_backend": "arrangement",
            "hybrid_outline_edge_count": len(outline_edges),
            "hybrid_bridge_edge_count": bridge_count,
            "hybrid_patch_count": len(patches),
            "hybrid_patch_area": patch_area,
        },
        outline_edges=outline_edges,
        fill_underlay=patches,
    )
