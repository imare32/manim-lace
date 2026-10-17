"""Verify the rosette-ribbon outline fix across many rosette weaves.

For every configuration it renders both ribbon backends (boolean and arrangement)
the way the gallery card does, and audits the produced regions for two signatures:

* the defect signature — a stroked edge that lies inside the painted ribbon, same
  strand on both sides, and on no lens boundary (a line across the middle of a
  strand), plus the opposite one, a hidden edge on the silhouette;
* ``notch gaps`` — pieces of a crossing's lens boundary that no stroke covers, where
  the visible material does change across the line. This is the signature the plain
  defect walk cannot see: a notch that ends in the middle of the ribbon
  (``docs/ROSETTE_RIBBON_OUTLINE_TICKS.md`` §9).

Comparison figures with a zoom on the worst spot go to ``media/verify_*.png`` (in the
git-ignored media tree).

Usage (from the repository root):

    .venv/Scripts/python.exe benchmarks/weave_audit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from manim_lace import Lace
from manim_lace.render import arrangement as arrangement_module
from manim_lace.render import regions as regions_module
from manim_lace.style.palette import get_palette

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

from scene_rosette import _loops_as_mobjects, rosette_loops  # noqa: E402

#: What ``mark_flush_edges`` was called with, captured by the spy below.
CAPTURED: dict = {}

_ORIGINAL_MARK = regions_module.mark_flush_edges


def _overlay_segments(edges):
    """Normalise the engine's explicit outline layer for the audit walks."""
    segments = []
    for edge in edges or ():
        if hasattr(edge, "start") and hasattr(edge, "end"):
            start, end = edge.start, edge.end
        else:
            start, end = edge
        segments.append((np.asarray(start, dtype=float), np.asarray(end, dtype=float)))
    return segments


def _spy(regions, *, cuts, weave=(), node_bands=None, **kwargs):
    CAPTURED.clear()
    CAPTURED.update(cuts=cuts, weave=weave, node_bands=node_bands, regions=list(regions))
    return _ORIGINAL_MARK(regions, cuts=cuts, weave=weave, node_bands=node_bands, **kwargs)


regions_module.mark_flush_edges = _spy
arrangement_module.mark_flush_edges = _spy

SUPERSAMPLE = 2
PANEL = 700


def notch_gaps(regions, overlay_edges=(), tolerance=1e-6):
    """Pieces of a crossing's lens boundary that no stroke covers.

    The weave notch — where the pass on top crosses the one below — has to be stroked
    along the whole of that footprint boundary. A piece left unstroked ends in the
    middle of the strand: that is the "stroke pokes into the ribbon" signature the
    defect audit cannot see, because such a piece is two-sided-covered but on a lens
    boundary, which its own rule excuses.

    Each recorded lens edge is compared against the strokes the regions emit: the
    strokes' intervals along it are merged and whatever is left is a gap. Only gaps
    whose midpoint is inside the ribbon (both sides covered, and the visible strand
    changes across the line) are counted.

    A lens edge a ring itself carries as a *flush* edge is not a gap either. ``flush`` is
    the region walk's verdict that the piece must not be stroked -- a section-cut seam, a
    side another strand covers, an interior boundary that is not weave -- so the ring
    covering it is the answer, not a defect. Counting those made this audit the advocate
    of precisely the lines ``missing_weave_outlines`` must not draw: ``docs/REVIEW.md``
    §206 recorded the case where following a named gap painted a 44 px tick across the
    strand. Two measured consequences on the review page: ``spec-self-intersecting``
    reports 0 either way (without this clause the matching guard in
    ``missing_weave_outlines`` re-opens it at 2), and the arrangement channel of
    ``index-random-walks-6`` / ``index-random-walks-12`` / ``ros-n5-ca-l2-o12`` stops
    naming 7 / 22 / 1 segments as gaps because those segments lie on flush ring edges.
    Read that as the rule refusing to call a seam a missing line, not as the dense random
    walks getting healthier.
    """
    weave = CAPTURED.get("weave") or ()
    fills = {
        region.region_id: Polygon(
            np.asarray(region.exterior.points, dtype=float),
            [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
        )
        for region in regions
    }
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    from shapely.strtree import STRtree

    fill_tree = STRtree([fills[region.region_id] for region in ordered])

    def owner(point):
        best = None
        for index in fill_tree.query(point):
            if fills[ordered[index].region_id].intersects(point):
                best = index if best is None else max(best, index)
        return None if best is None else ordered[best].region_id

    strokes = []
    seams = []
    for region in regions:
        points = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index in range(len(points) - 1):
            start, end = points[index], points[index + 1]
            if float(np.hypot(*(end - start))) <= 1e-9:
                continue
            if index in flush:
                seams.append((start, end))
            else:
                strokes.append((start, end))
    strokes.extend(_overlay_segments(overlay_edges))
    # A flush ring edge is the walk's "do not stroke this", so it covers the recorded
    # lens edge it lies on just as a stroke does. ``drawn_at`` below still asks about
    # strokes only: it is the weaker "some line is drawn near here" fallback.
    covering = [*strokes, *seams]

    def drawn_at(point, direction):
        """Is a stroke passing through ``point`` roughly along ``direction``?"""
        for s_start, s_end in strokes:
            span = float(np.hypot(*(s_end - s_start)))
            if span <= 1e-9:
                continue
            if float(np.hypot(*(0.5 * (s_start + s_end) - point))) > 0.2:
                continue
            along = (s_end - s_start) / span
            if abs(float(np.dot(along, direction))) < 0.9:
                continue
            if float(LineString([s_start, s_end]).distance(Point(*point))) <= 1e-4:
                return True
        return False

    gaps = 0
    total = 0.0
    for start, end in weave:
        span = float(np.hypot(*(end - start)))
        if span <= 1e-9:
            continue
        direction = (end - start) / span
        normal = np.array([-direction[1], direction[0]])
        intervals = []
        for s_start, s_end in covering:
            if abs(float(np.dot(s_start - start, normal))) > tolerance:
                continue
            if abs(float(np.dot(s_end - start, normal))) > tolerance:
                continue
            low = float(np.dot(s_start - start, direction))
            high = float(np.dot(s_end - start, direction))
            low, high = max(min(low, high), 0.0), min(max(low, high), span)
            if high - low > 1e-9:
                intervals.append((low, high))
        intervals.sort()
        merged: list[tuple[float, float]] = []
        for low, high in intervals:
            if merged and low <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], high))
                continue
            merged.append((low, high))
        uncovered = []
        cursor = 0.0
        for low, high in merged:
            if low - cursor > 1e-6:
                uncovered.append((cursor, low))
            cursor = max(cursor, high)
        if span - cursor > 1e-6:
            uncovered.append((cursor, span))
        for low, high in uncovered:
            middle = start + direction * (0.5 * (low + high))
            outer = owner(Point(*(middle + normal * 1e-6)))
            inner = owner(Point(*(middle - normal * 1e-6)))
            if outer is None or inner is None or outer == inner:
                continue
            if drawn_at(middle, direction):
                continue  # the line is drawn, just not exactly on this record of it
            gaps += 1
            total += high - low
    return gaps, total


def dangling_ends(regions, overlay_edges=()):
    """Stroke ends that stop inside the ribbon instead of at a boundary.

    A stroke may end where it meets another stroke (a T-junction or a corner) or on the
    silhouette; if it ends anywhere else — both sides painted, nothing to join — the line
    just stops in the middle of the strand, which is what a reader sees as a stray mark
    (``docs/ROSETTE_RIBBON_OUTLINE_TICKS.md`` §9). Joining is judged at 1e-4: strands that
    meet to within a hair of each other read as joined (the Boolean's own cuts can leave
    that much), while a stroke that stops in open fill is 0.01 and up away from anything.
    One entry per *visual* end: the two regions a boundary separates each stroke it, so the
    same end arrives twice and is counted once (``spec-self-intersecting``: 47 stroke ends
    on the Boolean panel are 24 a reader can see).

    "Two strokes meet here" is *not* enough to call an end joined. Two regions that share a
    boundary both stroke the same segment, so at such a vertex the only other stroke leaves
    in the *same* direction: that is one line ending, not a junction. The rule that excused
    it — any second stroke at the vertex meant "joined" — hid the class the human review
    found by eye, on ``spec-self-intersecting``: the arrangement backend's arm stops at
    ``(0.6472, 0.0530)``, in the middle of the ribbon, because its continuation is a section
    seam. An end is joined only if some other stroke leaves the vertex in a direction of its
    own — the continuation of the line, a corner, or a T-junction — or if a stroke passes
    *through* the vertex without ending there.

    A stroke a later fill paints over is not reported either: the strand it belongs to is
    under everything there, so the end reads as nothing at all. With that filter and the
    one-per-end count together, the `n = 7` CA card reports 0 on both panels where the first
    version reported 4 on the Boolean's, and the `n = 5` CA card's Boolean panel 17 where it
    reported 28.
    """
    from shapely.strtree import STRtree

    fills = {
        region.region_id: Polygon(
            np.asarray(region.exterior.points, dtype=float),
            [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
        )
        for region in regions
    }
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    index_of = {region.region_id: index for index, region in enumerate(ordered)}
    order_tree = STRtree([fills[region.region_id] for region in ordered])

    def topmost(point):
        """Index in ``ordered`` of the last-painted region that covers ``point``, or None.

        Asked region by region, like ``mark_flush_edges`` does: the overlay engine can drop
        a part that only touches its neighbours along an edge.
        """
        best = None
        for index in order_tree.query(point):
            if fills[ordered[index].region_id].intersects(point) and (best is None or index > best):
                best = index
        return best

    strokes: list[tuple[str, int, np.ndarray, np.ndarray]] = []
    for region in regions:
        ring = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index in range(len(ring) - 1):
            if index in flush:
                continue
            if float(np.hypot(*(ring[index + 1] - ring[index]))) <= 1e-9:
                continue
            strokes.append((region.region_id, index, ring[index], ring[index + 1]))
    for index, (start, end) in enumerate(_overlay_segments(overlay_edges)):
        if float(np.hypot(*(end - start))) <= 1e-9:
            continue
        strokes.append(("__outline__", -1 - index, start, end))
    lines = [LineString([start, end]) for _, _, start, end in strokes]
    stroke_tree = STRtree(lines) if lines else None

    endings: dict[tuple[float, float], list[int]] = {}
    for position, (_, _, start, end) in enumerate(strokes):
        for vertex in (start, end):
            key = (round(float(vertex[0]), 9), round(float(vertex[1]), 9))
            endings.setdefault(key, []).append(position)

    def outward(position: int, vertex: np.ndarray) -> np.ndarray | None:
        """The direction the stroke leaves ``vertex`` in, or None for a null edge."""
        _, _, start, end = strokes[position]
        start_distance = float(np.hypot(*(np.asarray(start) - vertex)))
        end_distance = float(np.hypot(*(np.asarray(end) - vertex)))
        other = end if end_distance >= start_distance else start
        span = float(np.hypot(*(np.asarray(other) - vertex)))
        if span <= 1e-9:
            return None
        return (np.asarray(other, dtype=float) - vertex) / span

    dangling = []
    seen: set[tuple[float, float]] = set()
    for key, owners in endings.items():
        vertex = np.array(key)
        point = Point(*vertex)
        # The stroke's own line runs through its end, so it must not count as the
        # neighbour this end joins; the query is buffered because a bare point query is
        # a bounding-box test and a stroke a hair away (3e-6 on the `n = 10` PA card)
        # can be outside the box of a point that is not exactly on it.
        candidates = (
            [] if stroke_tree is None
            else [index for index in stroke_tree.query(point.buffer(1e-4)) if index not in owners]
        )
        # A stroke that passes through without ending here carries the boundary on, whatever
        # direction it runs in.
        if any(float(lines[index].distance(point)) <= 1e-4 for index in candidates):
            continue
        for owner in owners:
            if strokes[owner][0] == "__outline__":
                continue
            direction = outward(owner, vertex)
            if direction is None:
                continue
            # Another stroke leaving this vertex in a direction of its own is a join: the
            # reverse of this one continues the line, any other angle is a corner or a T.
            # A stroke leaving in the *same* direction is the same line drawn twice.
            joined = False
            for other in owners:
                if other == owner:
                    continue
                other_direction = outward(other, vertex)
                if other_direction is not None and float(np.dot(direction, other_direction)) <= 0.999:
                    joined = True
                    break
            if joined:
                continue
            normal = np.array([-direction[1], direction[0]])
            outer = topmost(Point(*(vertex + normal * 2e-4)))
            inner = topmost(Point(*(vertex - normal * 2e-4)))
            if outer is None or inner is None:
                continue  # ends on the ribbon's outline
            # A stroke a later fill paints over is invisible: the strand it belongs to is
            # under everything there, so the end reads as nothing at all. Only the ends a
            # reader can see are defects, and the arm of a weave notch is visible on its own
            # side of the line (the over pass covers the other side).
            our_index = index_of[strokes[owner][0]]
            if min(outer, inner) > our_index:
                continue  # buried under a later strand
            if key in seen:
                continue  # the same visual end, drawn twice by the two regions it separates
            seen.add(key)
            dangling.append((strokes[owner][0], float(vertex[0]), float(vertex[1])))
    return dangling


def audit(regions):
    """Find stroked edges that draw a line inside the painted ribbon.

    The signature of the defect (``docs/ROSETTE_RIBBON_OUTLINE_TICKS.md`` §2): an
    exterior edge a renderer strokes, both of whose sides are covered by the painted
    union with the same strand on top, and which is on no lens boundary — i.e. it is
    not a weave notch, so nothing visible happens along it.
    """
    fills = {
        region.region_id: Polygon(
            np.asarray(region.exterior.points, dtype=float),
            [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
        )
        for region in regions
    }
    weave = CAPTURED.get("weave") or ()
    weave_geometry = (
        unary_union([LineString([tuple(a), tuple(b)]) for a, b in weave]) if weave else None
    )
    node_bands = CAPTURED.get("node_bands") or {}
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    probe = 1e-6
    tolerance = 1e-6
    from shapely.strtree import STRtree

    fill_tree = STRtree([fills[region.region_id] for region in ordered]) if fills else None

    def covered(point):
        """Is the point inside any painted region? Asked region by region: a union of
        them all can drop a part that only touches its neighbours along an edge."""
        if fill_tree is None:
            return False
        return any(fills[ordered[index].region_id].intersects(point)
                   for index in fill_tree.query(point))

    def topmost_path(point):
        best = None
        for region in ordered:
            if fills[region.region_id].intersects(point):
                best = region
        return None if best is None else best.path_id

    violations = []
    over_marked = []
    for region in regions:
        if region.area <= 1e-12:
            continue  # a zero-area region paints nothing
        points = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index in range(len(points) - 1):
            start, end = points[index], points[index + 1]
            if float(np.hypot(*(end - start))) <= 1e-9:
                continue  # a degenerate edge draws nothing
            middle = 0.5 * (start + end)
            direction = (end - start) / float(np.linalg.norm(end - start))
            normal = np.array([-direction[1], direction[0]])
            outer = Point(*(middle + normal * probe))
            inner = Point(*(middle - normal * probe))
            if not (covered(outer) and covered(inner)):
                if index in flush:
                    over_marked.append((region.region_id, index, start, end))
                continue
            if topmost_path(outer) != topmost_path(inner):
                continue  # a colour boundary between two strands: real outline
            if index in flush:
                continue  # correctly hidden
            on_weave = (
                weave_geometry is not None
                and weave_geometry.distance(Point(*middle)) <= tolerance
            )
            if on_weave:
                continue  # a weave notch: the outline a renderer owes there
            node = region.region_id.rsplit(".region", 1)[0]
            band = node_bands.get(node)
            on_band = band is not None and band.boundary.distance(Point(*middle)) <= tolerance
            violations.append((region.region_id, index, start, end, on_band))
    return violations, over_marked


def _hex(color) -> tuple[int, int, int]:
    text = str(color)
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 6:
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
    return (128, 128, 128)


def render_panel(
    regions, colors, title, violations, overlay_edges=(), centre=None, span=None
):
    """One backend's regions as the renderer draws them: fills, holes, outline strokes."""
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    all_points = np.vstack([np.asarray(r.exterior.points, dtype=float) for r in ordered])
    if centre is None:
        low, high = all_points.min(axis=0), all_points.max(axis=0)
        centre = 0.5 * (low + high)
        span = float(max(np.ptp(all_points, axis=0))) * 1.12
    scale = PANEL * SUPERSAMPLE / span
    size = PANEL * SUPERSAMPLE
    image = Image.new("RGB", (size, size), "#ffffff")
    draw = ImageDraw.Draw(image)

    def to_pixel(point):
        return (
            (point[0] - centre[0]) * scale + size / 2,
            size / 2 - (point[1] - centre[1]) * scale,
        )

    for region in ordered:
        ring = np.asarray(region.exterior.points, dtype=float)
        draw.polygon([to_pixel(point) for point in ring], fill=_hex(colors[region.path_id]))
    for region in ordered:  # holes are painted after every fill, like the renderer's groups
        for hole in region.holes:
            ring = np.asarray(hole.points, dtype=float)
            draw.polygon([to_pixel(point) for point in ring], fill="#ffffff")
    for region in ordered:
        points = np.asarray(region.exterior.points, dtype=float)
        flush = set(region.flush_edges)
        for index in range(len(points) - 1):
            start, end = points[index], points[index + 1]
            if float(np.hypot(*(end - start))) <= 0.0 or index in flush:
                continue
            draw.line([to_pixel(start), to_pixel(end)], fill="#111111", width=SUPERSAMPLE)
    for start, end in _overlay_segments(overlay_edges):
        draw.line([to_pixel(start), to_pixel(end)], fill="#111111", width=SUPERSAMPLE)
    for region_id, index, start, end, on_band in violations:
        draw.line([to_pixel(start), to_pixel(end)], fill="#ff0000", width=4 * SUPERSAMPLE)
        draw.ellipse(
            [to_pixel(start)[0] - 4, to_pixel(start)[1] - 4,
             to_pixel(start)[0] + 4, to_pixel(start)[1] + 4],
            fill="#ff0000",
        )
    return image.resize((PANEL, PANEL), Image.LANCZOS), title


def zoom_target(regions, violations):
    if violations:
        points = [point for _, _, start, end, _ in violations for point in (start, end)]
        centre = np.mean(np.asarray(points), axis=0)
        span = max(0.22, 5.0 * float(np.max(np.ptp(np.asarray(points), axis=0))))
        return centre, span
    points = np.vstack([
        np.asarray(r.exterior.points, dtype=float) for r in regions
    ])
    return 0.5 * (points.min(axis=0) + points.max(axis=0)), 0.85


def run(configs):
    palette = get_palette("ayame")
    colours = [palette.color(index) for index in range(len(palette))]
    rows = []
    for name, loops, offset in configs:
        source = _loops_as_mobjects(loops)
        panels = []
        for backend in ("boolean", "arrangement"):
            kwargs = dict(offset=offset, render="ribbon", palette="ayame",
                          stroke_color="#000000", stroke_width_px=2.0,
                          fill_opacity=1.0, hole_color="#ffffff")
            if backend == "arrangement":
                kwargs["ribbon_backend"] = "arrangement"
            lace = Lace(source, **kwargs)
            regions = lace.result.pieces
            overlay_edges = getattr(lace.result, "outline_edges", ())
            paths = sorted({region.path_id for region in regions})
            region_colors = {path: colours[index % len(colours)] for index, path in enumerate(paths)}
            violations, over_marked = audit(regions)
            gaps, gap_length = notch_gaps(regions, overlay_edges)
            dangling = dangling_ends(regions, overlay_edges)
            rows.append((name, backend, len(regions), len(violations), len(over_marked),
                         gaps, gap_length, len(dangling)))
            verdict = f"defects={len(violations)}" if violations else "clean"
            full, _ = render_panel(
                regions, region_colors, f"{backend}: {len(regions)} faces", violations,
                overlay_edges=overlay_edges,
            )
            centre, span = zoom_target(regions, violations)
            zoom, _ = render_panel(
                regions, region_colors, f"{backend} zoom ({verdict})", violations,
                overlay_edges=overlay_edges, centre=centre, span=span,
            )
            panels.extend((full, zoom))
        header = Image.new("RGB", (2 * PANEL + 30, 46), "#ffffff")
        header_draw = ImageDraw.Draw(header)
        header_draw.text((12, 14), f"{name}  offset={offset}  red = defect signature "
                                   f"(stroke inside ribbon, off every lens boundary)",
                         fill="#111111")
        sheet = Image.new("RGB", (2 * PANEL + 30, 2 * PANEL + 30 + 46), "#ffffff")
        sheet.paste(header, (0, 0))
        sheet.paste(panels[0], (0, 46))
        sheet.paste(panels[1], (PANEL + 30, 46))
        sheet.paste(panels[2], (0, PANEL + 76))
        sheet.paste(panels[3], (PANEL + 30, PANEL + 76))
        target = ROOT / "media" / f"verify_{name.replace(' ', '_').replace('+', 'p')}.png"
        sheet.save(target)
        print(f"[image] {target}")
    print()
    print(f"{'config':<24}{'backend':<14}{'faces':>7}{'defects':>9}{'over-hidden':>12}"
          f"{'notch gaps':>12}{'gap length':>12}{'dangling':>10}")
    for name, backend, count, bad, hidden, gaps, gap_length, dangling in rows:
        print(f"{name:<24}{backend:<14}{count:>7}{bad:>9}{hidden:>12}"
              f"{gaps:>12}{gap_length:>12.4f}{dangling:>10}")


CONFIGS = [
    ("n10 PA L1p2 o08", rosette_loops(10, 1, "PA") + rosette_loops(10, 2, "PA"), 0.08),
    ("n10 PA L2 o08", rosette_loops(10, 2, "PA"), 0.08),
    ("n8 PA L1p2 o06", rosette_loops(8, 1, "PA") + rosette_loops(8, 2, "PA"), 0.06),
    ("n12 PO L2 o05", rosette_loops(12, 2, "PO"), 0.05),
    ("n9 PR L2 o08", rosette_loops(9, 2, "PR"), 0.08),
    ("n7 CA L2 o10", rosette_loops(7, 2, "CA"), 0.10),
    ("n11 CR L2 o07", rosette_loops(11, 2, "CR"), 0.07),
    ("n10 PA L1p2 o05", rosette_loops(10, 1, "PA") + rosette_loops(10, 2, "PA"), 0.05),
    ("n5 CA L2 o12", rosette_loops(5, 2, "CA"), 0.12),
    ("n6 PA L2 o09", rosette_loops(6, 2, "PA"), 0.09),
    ("n13 PO L2 o06", rosette_loops(13, 2, "PO"), 0.06),
    ("n8 CR L2 o08", rosette_loops(8, 2, "CR"), 0.08),
    ("n9 CA L1p2 o07", rosette_loops(9, 1, "CA") + rosette_loops(9, 2, "CA"), 0.07),
    ("n11 PA L2 o06", rosette_loops(11, 2, "PA"), 0.06),
    ("n12 PR L2 o05", rosette_loops(12, 2, "PR"), 0.05),
    ("n7 PR L2 o11", rosette_loops(7, 2, "PR"), 0.11),
    ("n10 CR L2 o06", rosette_loops(10, 2, "CR"), 0.06),
    ("n6 CA L2 o10", rosette_loops(6, 2, "CA"), 0.10),
    ("n5 PO L2 o12", rosette_loops(5, 2, "PO"), 0.12),
    ("n13 CA L2 o05", rosette_loops(13, 2, "CA"), 0.05),
    ("n8 PO L2 o08", rosette_loops(8, 2, "PO"), 0.08),
    ("n12 CA L2 o05", rosette_loops(12, 2, "CA"), 0.05),
    ("n9 PO L2 o07", rosette_loops(9, 2, "PO"), 0.07),
    ("n11 PA L1p2 o06", rosette_loops(11, 1, "PA") + rosette_loops(11, 2, "PA"), 0.06),
]

if __name__ == "__main__":
    run(CONFIGS)
