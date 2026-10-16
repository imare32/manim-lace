"""Planar-region ribbon backend (SPEC FR-052, FR-053, FR-054, FR-055, FR-057, FR-058).

The stroke backend cuts centerlines with a heuristic radius. This backend builds the
actual ribbon areas instead and removes, at every woven crossing, the exact Boolean
intersection of the two ribbons: no radius, no shallow-angle clamp, no cap compensation.
The removed lens is precisely the footprint of the ribbon that is over, which is what
"the over strand hides the under strand" means geometrically.

Each path's band is cut at the crossings it takes part in, so the two passes of a
self-crossing become *sections* that can be over and under each other — a single band
cannot be both. Sections meet exactly on the split line, so their union is the whole
band again; the split line itself is a straight chord across the strand with the same
material on either side, and every such chord is marked as flush so a renderer does not
stroke it as if the strand had been cut there (:func:`mark_flush_edges`). Marking is done
from the cut chords themselves, not from pairs of shared edges: on a self-crossing the cut
the under pass shows lies exactly on the other pass's outline, so a shared-edge rule cannot
tell the weave from a seam.

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
    #: Indices of ``exterior.points`` whose edge to the next point is a seam of the section
    #: split — a straight chord across the strand with the same material on both sides, not
    #: an outline of the strand. Stroking it would draw a short tick across the ribbon
    #: (SPEC FR-057). Filled in by :func:`mark_flush_edges` from the section cut chords; a
    #: renderer should skip exactly those edges and stroke every other one.
    flush_edges: tuple[int, ...] = ()

    @property
    def rings(self) -> list[RegionRing]:
        return [self.exterior, *self.holes]


def _section_boundary_arcs(path: PolylinePath, group: list[_Strip]) -> list[float]:
    """The arcs at which a sectioned path was divided, without its own ribbon ends.

    An open path's two ends are boundaries of the ribbon itself, not seams of a split, so
    they stay out: stroking them is what draws the cut end of the strand.
    """
    length = float(path.length)
    if length <= 0.0:
        return []
    tolerance = 1e-9 * max(length, 1.0)
    arcs: list[float] = []
    for strip in group:
        for arc in (strip.start_arc, strip.end_arc):
            value = float(arc) % length if path.closed else float(arc)
            if not path.closed and (value <= tolerance or value >= length - tolerance):
                continue
            if any(abs(value - kept) <= tolerance for kept in arcs):
                continue
            arcs.append(value)
    return sorted(arcs)


def _cut_lines(
    paths: list[PolylinePath],
    sections: dict[str, list[_Strip]],
    *,
    offset: float,
) -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    """The cross-section chords where each path was divided into sections.

    A section is a buffered sub-path, so both of its ends are flat caps: straight chords
    through a split point, across the strand. Those chords — and only those — are the seams
    of the split. The sides of a section are the strand's own outline and stay drawable even
    where they happen to coincide with another pass's outline: that coincidence is exactly
    the cut the under pass shows at a crossing.
    """
    by_id = {path.path_id: path for path in paths}
    lines: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for path_id, group in sections.items():
        path = by_id.get(path_id)
        if path is None:
            continue
        length = float(path.length)
        probe = 1e-9 * max(length, 1.0)
        reach = 4.0 * offset
        chords: list[tuple[np.ndarray, np.ndarray]] = []
        for arc in _section_boundary_arcs(path, group):
            point, _ = _arc_frame(path, arc)
            # A split point can land on a path vertex, where the section before and the
            # section after have caps of different directions: both are real seams.
            for direction in (arc - probe, arc + probe):
                _, tangent = _arc_frame(path, direction)
                normal = np.array([-tangent[1], tangent[0]])
                chords.append((point - normal * reach, point + normal * reach))
        if chords:
            lines[path_id] = chords
    return lines


def _open_occlusion_holes(
    geometry: Any,
    *,
    path: PolylinePath,
    crossings: list[CrossingEvent],
    source_hole_areas: list[float],
    offset: float,
) -> tuple[list[Any], list[tuple[np.ndarray, np.ndarray]]]:
    """Split a piece along the cut chord of every *occlusion* hole it still carries.

    An occlusion hole is the over strand's footprint inside this band: the region's
    exterior ring still encloses it, and Manim fills an exterior ring solid, so the
    adapter has to paint the hole in the background colour to show the cut. That only
    works while the piece covering the footprint is painted *later* — and the painter
    order cannot always arrange it, because two strands that cross more than twice
    alternate their over/under into a cycle the order has to break. Where it breaks, the
    hole paints over the strand that is on top and bites a background-coloured notch out
    of the pattern.

    Splitting the piece along the crossing's cut chord removes the need for that paint:
    the hole becomes a notch on the piece's own boundary, so the fill itself stops at the
    cut, and the over strand's region — which always covers its own footprint — is what
    shows through, whichever order the two are painted in. The split chord is returned so
    the caller can mark it flush (a seam, not a strand boundary).

    ``source_contour`` holes are left alone: they are genuine gaps in the strand (the
    inside of a closed loop) and the region really is an annulus there.
    """
    _line, _point, Polygon, union, _make_valid, _orient = _require_shapely()
    chords: list[tuple[np.ndarray, np.ndarray]] = []
    pieces = [polygon for polygon in _polygons(geometry) if polygon.geom_type == "Polygon"]
    # Bound the passes. One hole is normally removed by one cut, but a piece can carry
    # several (a band with several near-tangent crossings does), so the halves are
    # re-examined until none is left. That re-examination cannot be trusted to terminate
    # on its own: a chord that fails to remove its hole (see ``_split_along_cut``) would
    # leave it in one half and every pass would only double the pieces — measured on
    # ``random_walks_6``, where one piece with a single hole passed 320k splits without
    # ending. The pass count is therefore capped. A hole that survives the cap is kept,
    # which is exactly the behaviour this pass was introduced to improve on: the adapter
    # paints it in the background colour and it only shows when the paint order allows it.
    budget = 2 + len(pieces)
    for _ in range(budget):
        opened: list[Any] = []
        resplit = False
        for polygon in pieces:
            occlusions = [
                ring for ring, role in zip(
                    polygon.interiors,
                    _hole_roles(polygon, source_hole_areas),
                    strict=True,
                )
                if role == "occlusion"
            ]
            if not occlusions:
                opened.append(polygon)
                continue
            split_pieces: list[Any] = [polygon]
            for ring in occlusions:
                # The whole boundary of the bite is a seam in the same sense as the split
                # chord, so nothing may be stroked along it either. Half of it lies on the
                # *over* strand's side — the strand on top draws that silhouette itself — and
                # the other half lies on the under strand's own side, which is simply hidden
                # under the strand above it, not ended. Left strokeable, those hidden-side
                # edges poke a black line about half a band width into the ribbon (they used
                # to be part of an interior ring, which is never stroked).
                ring_points = np.asarray(ring.coords, dtype=float)
                for start, end in zip(ring_points[:-1], ring_points[1:], strict=True):
                    chords.append((start, end))
                next_pieces: list[Any] = []
                for piece in split_pieces:
                    next_pieces.extend(_split_along_cut(
                        piece, ring=ring, path=path, crossings=crossings,
                        offset=offset, chords=chords, polygon_class=Polygon,
                    ))
                split_pieces = next_pieces
            opened.extend(split_pieces)
            resplit = True
        pieces = opened
        if not resplit:
            break
    if not pieces:
        # The geometry carries no polygon at all: a near-tangent ``difference`` can leave
        # a zero-area ``MultiLineString`` / ``GeometryCollection`` behind. There is then
        # nothing to paint, and returning the raw geometry would reach the caller as a
        # non-polygon and crash when it reads ``.interiors``. Return no pieces instead.
        return [], chords
    # Deliberately *not* merged into one geometry: the pieces must stay separate, or the
    # shared chord is dissolved back into the interior and the hole comes straight back.
    return pieces, chords


def _split_along_cut(
    polygon: Any,
    *,
    ring: Any,
    path: PolylinePath,
    crossings: list[CrossingEvent],
    offset: float,
    chords: list[tuple[np.ndarray, np.ndarray]],
    polygon_class: Any,
) -> list[Any]:
    """One occlusion hole: cut ``polygon`` along that crossing's cut chord."""
    hole = polygon_class(ring)
    centre = np.array([hole.centroid.x, hole.centroid.y])
    candidates = [
        crossing for crossing in crossings
        if crossing.path_a == path.path_id or crossing.path_b == path.path_id
    ]
    if not candidates:
        return [polygon]
    crossing = min(
        candidates,
        key=lambda item: float(np.sum((np.array(item.point) - centre) ** 2)),
    )
    arc = crossing.s_a if crossing.path_a == path.path_id else crossing.s_b
    _, tangent = _arc_frame(path, float(arc))
    # Centre the chord on the hole it has to remove, not on the crossing point. For a
    # single clean crossing the two coincide, but a hole can be the footprint of several
    # near-tangent crossings, or wider than the window of the crossing nearest to it, and
    # a chord through that crossing's point can then miss the hole. The hole survives in
    # one half, the pass loop re-splits that half, and — each split only doubling the
    # pieces — it does not terminate (measured on ``random_walks_6``: one piece with a
    # single hole passed 320k splits). A chord through the centroid always separates the
    # hole it was aimed at, which is what lets the loop below finish.
    point = centre
    normal = np.array([-tangent[1], tangent[0]])
    # The half-planes and the chord have to cover the piece, not just the strand width:
    # the cut chord of a miter corner is wider than 2 * offset, and ``_on_cut`` only marks
    # an edge flush when the whole edge lies inside the chord.
    bounds = polygon.bounds
    diagonal = float(np.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1]))
    span = 2.0 * max(diagonal, 4.0 * offset, 1.0)
    chords.append((point - normal * span, point + normal * span))
    halves: list[Any] = []
    for sign in (1.0, -1.0):
        step = tangent * span * sign
        halves.append(polygon_class([
            point - normal * span, point + normal * span,
            point + normal * span + step, point - normal * span + step,
        ]))
    result: list[Any] = []
    for half in halves:
        cut = polygon.intersection(half)
        result.extend(
            part for part in _polygons(cut)
            if part.geom_type == "Polygon" and part.area > 1e-12
        )
    return result or [polygon]


def _on_cut(
    first: np.ndarray,
    second: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    tolerance: float,
) -> bool:
    """True when the segment lies on the cut chord from ``start`` to ``end``."""
    chord = end - start
    span = float(np.dot(chord, chord))
    if span <= 0.0:
        return False
    normal = np.array([-chord[1], chord[0]]) / float(np.sqrt(span))
    if abs(float(np.dot(first - start, normal))) > tolerance:
        return False
    if abs(float(np.dot(second - start, normal))) > tolerance:
        return False
    first_along = float(np.dot(first - start, chord)) / span
    second_along = float(np.dot(second - start, chord)) / span
    slack = tolerance / float(np.sqrt(span))
    return min(first_along, second_along) >= -slack and max(first_along, second_along) <= 1.0 + slack


def mark_flush_edges(
    regions: list[RibbonRegion],
    *,
    cuts: dict[str, list[tuple[np.ndarray, np.ndarray]]],
    weave: list[tuple[np.ndarray, np.ndarray]] = (),
    node_bands: dict[str, Any] | None = None,
    tolerance: float = 1e-6,
    probe: float = 1e-6,
) -> int:
    """Mark the exterior edges a renderer must not stroke, and return how many.

    Three families of exterior edge carry no visible boundary:

    * **Seams.** Cutting a self-crossing needs the path divided into sections (and, for
      the Boolean backend, into windows around each pass), which leaves a chord across
      the strand where the material simply continues: the two sides are one strand, one
      colour, one region. Nothing visible happens along such a chord, so stroking it
      draws a tick across the ribbon and makes the strand look cut when it is not. The
      chords are known exactly — they are the caps of the section bands, see
      :func:`_cut_lines` — so they are handed in instead of being guessed from pairs of
      shared edges. Guessing cannot work on a self-crossing: the *cut* the under pass
      shows there lies exactly on the other pass's outline, because the subtracted lens
      is bounded by it, so a shared-edge test marks the weave itself as a seam. A cut
      edge therefore stays unmarked and keeps the weave readable.
    * **Covered sides.** A side of a region's own band that another strand (or another
      section of the same strand) covers: the fill continues across it in one colour, so
      the only outline a renderer owes there is the one of the strand on top. This is the
      "a line runs across the middle of the ribbon" signature.
    * **Interior edges that are not weave.** Where two sections of one path overlap away
      from a crossing, the boundary between their territories is interior to the painted
      ribbon and belongs to no lens.

    What must stay is the **weave notch**: the edge where the under pass of a crossing
      stops against the over pass's lateral edge. It is interior to the painted ribbon
    too — the over strand covers the lens — but it is the boundary a renderer has to
    stroke, and marking it is what drew ticks across the ribbon. A notch is told apart
    from a covered side by the band it belongs to: a notch cuts *across* the region's own
    band, while a covered side lies *on* it.

    ``weave`` are the lens boundaries (the local footprint of every crossing that was
    actually cut) and ``node_bands`` maps each region's node — its strip for a sectioned
    path, else the path — to the band that node was built from. Both are what tells the
    three interior families apart; without them only the chords can be marked.

    An edge can be part seam, part notch and part covered side, so the exterior ring is
    split where its status changes (at every crossing with a region boundary, a weave
    edge or a node band) and each piece is judged on its own. The fill is unchanged —
    inserted vertices are collinear, and a corner the join folds away is collinear to
    within the marking tolerance.
    """
    from shapely.strtree import STRtree

    LineString, Point, Polygon, unary_union, _make_valid, _orient = _require_shapely()
    ordered = sorted(regions, key=lambda item: (item.draw_index, item.region_id))
    fills = {
        region.region_id: Polygon(
            np.asarray(region.exterior.points, dtype=float),
            [np.asarray(hole.points, dtype=float) for hole in region.holes] or None,
        )
        for region in ordered
    }
    # The lens footprints stay individual segments in an STRtree instead of being unioned
    # into one geometry. The only question asked of them is "is this point within
    # ``tolerance`` of one of them" (see ``is_hidden``), and answering that with a union
    # makes the overlay engine node every pair of overlapping segments first: measured on
    # ``adp-arc-overlapping``, whose retraced ``Arc(3π)`` produces ~13k weave edges, that
    # one ``unary_union`` cost 65 s of a 78 s render.
    weave_lines = [LineString([tuple(start), tuple(end)]) for start, end in weave]
    weave_tree = STRtree(weave_lines) if weave_lines else None
    # An edge's status can only change where it crosses another region's boundary, a
    # weave edge or its own node's band, so those are the split points to look for.
    segments: list[Any] = []
    for region in ordered:
        points = np.asarray(region.exterior.points, dtype=float)
        for start, end in zip(points[:-1], points[1:], strict=False):
            if float(np.hypot(*(end - start))) > 0.0:
                segments.append(LineString([tuple(start), tuple(end)]))
    for start, end in weave:
        segments.append(LineString([tuple(start), tuple(end)]))
    for band in (node_bands or {}).values():
        if band is not None and not band.is_empty:
            segments.append(band.boundary)
    tree = STRtree(segments) if segments else None
    fill_tree = STRtree([fills[region.region_id] for region in ordered]) if fills else None

    def topmost(point: Point) -> int | None:
        """Index in ``ordered`` of the last-painted region that covers ``point``.

        Asked region by region rather than of a union of them all: the overlay engine
        can drop a part that only touches its neighbours along an edge (see
        :func:`_covered_area`), and a part dropped from that union would make the
        edges around it look like the silhouette of the painted ribbon.
        """
        if fill_tree is None:
            return None
        best: int | None = None
        for index in fill_tree.query(point):
            if fills[ordered[index].region_id].intersects(point):
                if best is None or index > best:
                    best = index
        return best

    def split_parameters(start: np.ndarray, end: np.ndarray) -> list[float]:
        if tree is None:
            return [0.0, 1.0]
        edge = LineString([tuple(start), tuple(end)])
        parameters = {0.0, 1.0}
        for candidate in tree.query(edge):
            hit = segments[candidate].intersection(edge)
            stack = [hit] if not hit.is_empty else []
            while stack:
                item = stack.pop()
                kind = getattr(item, "geom_type", "")
                if kind == "Point":
                    coordinates = [item.coords[0]]
                elif kind in ("MultiPoint", "GeometryCollection", "MultiLineString"):
                    stack.extend(item.geoms)
                    continue
                elif kind == "LineString":
                    coordinates = list(item.coords)
                else:
                    continue
                for coordinate in coordinates:
                    delta = np.asarray(coordinate, dtype=float) - start
                    span = float(np.dot(end - start, end - start))
                    if span <= 0.0:
                        continue
                    parameter = float(np.dot(delta, end - start)) / span
                    if -1e-9 <= parameter <= 1.0 + 1e-9:
                        parameters.add(min(max(parameter, 0.0), 1.0))
        return sorted(parameters)

    def is_hidden(
        start: np.ndarray, end: np.ndarray, low: float, high: float, band: Any,
        region_id: str,
    ) -> bool:
        """Does this piece of edge carry no visible boundary of its own?"""
        middle = start + (end - start) * (0.5 * (low + high))
        direction = (end - start) / float(np.linalg.norm(end - start))
        normal = np.array([-direction[1], direction[0]])
        outer = topmost(Point(*(middle + normal * probe)))
        inner = topmost(Point(*(middle - normal * probe)))
        if outer is None or inner is None:
            return False  # the silhouette of the painted ribbon
        if ordered[outer].path_id != ordered[inner].path_id:
            return False  # a colour boundary between two strands
        if weave_tree is not None and len(weave_tree.query(
            Point(*middle), predicate="dwithin", distance=tolerance
        )):
            # The weave notch: the edge is on the footprint boundary of the pass on top,
            # so the visible material changes here — exactly the boundary a renderer has
            # to stroke. Asked *before* the band test, because the over pass's own lateral
            # edge is a notch where it crosses the under pass; hiding it as a covered side
            # leaves a hole in the notch wherever the under pass's own sections do not
            # carry that piece (measured on `n = 7` CA: 0.088 of a lens edge stayed
            # unstroked and the notch ended in the middle of the ribbon).
            if outer != inner and region_id in (
                ordered[outer].region_id, ordered[inner].region_id
            ):
                return False
            return True  # hidden under a later strand, whose own outline is owed
        if band is not None and band.boundary.distance(Point(*middle)) <= tolerance:
            return True  # a side of this region's own band, covered by something else
        return True  # interior, one colour, no weave

    # The seam test asks "does this edge lie on one of the path's cut chords", and a
    # sectioned path carries one chord per section cap: measured on ``adp-arc-overlapping``
    # (an ``Arc(3π)`` whose last half-turn retraces the first) that is 1965 chords against
    # 3730 edges, i.e. 7.3M containment tests and 17 s of a 41 s render — while nearly
    # every pair is disjoint. The chords go into an STRtree so an edge only asks about the
    # chords its bounding box meets, the same structure ``split_parameters`` already uses
    # for its split points. The test itself is unchanged: a seam is still a seam.
    seam_index: dict[str, tuple[tuple[tuple[np.ndarray, np.ndarray], ...], Any]] = {}

    def seams_along(path_id: str, edge: Any) -> Any:
        """The cut chords whose bounding box meets ``edge`` — a superset of the seams."""
        entry = seam_index.get(path_id)
        if entry is None:
            chords = tuple(cuts.get(path_id, ()))
            lines = [LineString([tuple(start), tuple(end)]) for start, end in chords]
            entry = (chords, STRtree(lines) if lines else None)
            seam_index[path_id] = entry
        chords, seam_tree = entry
        if seam_tree is None:
            return ()
        return (chords[index] for index in seam_tree.query(edge))

    marked = 0
    for region in regions:
        has_cuts = bool(cuts.get(region.path_id))
        node = region.region_id.rsplit(".region", 1)[0]
        band = (node_bands or {}).get(node)
        points = np.asarray(region.exterior.points, dtype=float)
        # The ring is rebuilt as a list of (start, end, hidden) pieces, so that an edge
        # can be part hidden and part outline, and so that pieces the renderer would
        # draw as one edge are joined back into one.
        pieces: list[tuple[np.ndarray, np.ndarray, bool]] = []
        for start, end in zip(points[:-1], points[1:], strict=False):
            if float(np.hypot(*(end - start))) <= 0.0:
                continue
            if has_cuts and any(
                _on_cut(start, end, chord_start, chord_end, tolerance)
                for chord_start, chord_end in seams_along(
                    region.path_id, LineString([tuple(start), tuple(end)])
                )
            ):
                pieces.append((start, end, True))  # a seam: the material continues
                continue
            parameters = split_parameters(start, end)
            for low, high in zip(parameters[:-1], parameters[1:], strict=False):
                if high - low <= 1e-12:
                    continue
                hidden = is_hidden(start, end, low, high, band, region.region_id)
                if low == 0.0 and high == 1.0:
                    # The whole edge is one piece: keep the ring's own points, so a ring
                    # nothing happened to stays exactly what it was.
                    pieces.append((start, end, hidden))
                else:
                    pieces.append((start + (end - start) * low, start + (end - start) * high, hidden))
        joined: list[tuple[np.ndarray, np.ndarray, bool]] = []
        for piece in pieces:
            previous = joined[-1] if joined else None
            if (
                previous is not None
                and previous[2] == piece[2]
                and _collinear(previous[0], previous[1], piece[1], tolerance)
            ):
                joined[-1] = (previous[0], piece[1], previous[2])
                continue
            joined.append(piece)
        flags = [piece[2] for piece in joined]
        if len(joined) >= 3:
            region.flush_edges = tuple(index for index, flag in enumerate(flags) if flag)
            # The indices above address the joined ring, so the ring has to become the
            # joined one whenever the two differ — by a split vertex as much as by a
            # merged corner. Comparing point counts is not enough: one edge can be split
            # while another pair of near-collinear edges is joined, and the two cancel
            # out, which would leave the original ring wearing flush indices that
            # address a different ring.
            ring = [joined[0][0], *(piece[1] for piece in joined)]
            if len(ring) != len(points) or any(
                not np.array_equal(candidate, original)
                for candidate, original in zip(ring, points)
            ):
                region.exterior = RegionRing(
                    points=np.array(ring, dtype=float), role=region.exterior.role
                )
        elif joined:
            # A ring that joins into fewer than three runs encloses no area — every one
            # of its corners is collinear — so the original ring stays and its edges are
            # told apart by that single run: all of them are seams, or none is.
            region.flush_edges = tuple(range(len(points) - 1)) if flags[0] else ()
        else:
            region.flush_edges = ()
        marked += len(region.flush_edges)
    return marked


def _collinear(start: np.ndarray, middle: np.ndarray, end: np.ndarray, tolerance: float) -> bool:
    """Do three points run straight on from one to the next?

    The test is relative on purpose: a vertex the polygonisation left on a straight run
    has a cross product at the level of floating-point noise, while a real corner — even
    the corner of a sliver the ring walk kept — does not.
    """
    first = middle - start
    second = end - middle
    cross = abs(float(first[0] * second[1] - first[1] * second[0]))
    scale = float(np.linalg.norm(first)) * float(np.linalg.norm(second))
    return scale > 0.0 and cross <= tolerance * scale


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


#: A folded vertex whose triangle is this small (world units²) is numeric noise from the
#: polygon boolean rather than shape: it encloses no area at all, so dropping it cannot
#: change what the ring covers. Compare with ``_FOLD_AREA_TOLERANCE`` usage in
#: :func:`_drop_folds`.
_FOLD_AREA_TOLERANCE = 1e-12


def _drop_folds(points: np.ndarray, *, area_tolerance: float = _FOLD_AREA_TOLERANCE) -> np.ndarray:
    """Remove the out-and-back folds a polygon boolean can leave on a ring.

    A boolean cut that only touches the boundary (the tip of a weave lens is the usual case)
    can make the boundary run out along a line and come straight back to where it started.
    Such a fold encloses no area, so the fill looks right, but the fold *is* part of the ring:
    stroking the ring draws that line, and it shows up as a short whisker sticking out of the
    ribbon (SPEC FR-057, the same family as the seam ticks).

    Only reversals are considered — the ring has to turn back into itself — and only when the
    triangle they span carries no area, so a genuine corner or a real (if thin) feature is
    never touched. Folds are removed one at a time, re-judging the ring after each drop:
    dropping a vertex moves its neighbours' test, and a run of near-duplicate points (float
    noise from the boolean) makes *every* one of them look like a zero-area reversal —
    dropping them all in one pass removes the vertex the ring really turns at, and with it
    the thin wedge the ring encloses there.
    """
    if len(points) < 4:
        return points
    kept = [np.array(point) for point in points[:-1]]
    changed = True
    while changed and len(kept) >= 3:
        changed = False
        count = len(kept)
        for index in range(count):
            previous = kept[index - 1]
            current = kept[index]
            following = kept[(index + 1) % count]
            back = current - previous
            forward = following - current
            if float(np.dot(back, forward)) >= 0.0:
                continue
            area = 0.5 * abs(float(back[0] * forward[1] - back[1] * forward[0]))
            if area > area_tolerance:
                continue
            kept = [point for position, point in enumerate(kept) if position != index]
            changed = True
            break
    if len(kept) < 3:
        return points
    return np.vstack((np.array(kept), np.array(kept[0])))


def _ring_points(ring: Any) -> np.ndarray:
    coords = _drop_folds(np.asarray(ring.coords, dtype=float)[:, :2])
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


def _arm_strip(
    path: PolylinePath,
    arc: float,
    window: float,
    *,
    offset: float,
    join: JoinStyle,
    miter_limit: float,
    line_class: Any,
) -> Any:
    """A short ribbon strip centred on one pass of a self-crossing.

    A self-crossing has no second band to intersect with, so the local footprint of a
    pass is built from a window of its own centreline around the crossing. The window is
    chosen to be clearly longer than the overlap (`4 * offset / sin(theta)`), which is
    why the result is checked against that expectation before it is trusted.

    Used by both backends: the arrangement builds its lens from two of these, and the
    Boolean backend uses them to know where the *true* notch lies — its own cut is
    clipped by the section windows it works through (see :func:`_self_crossing_lens`).
    """
    length = float(path.length)
    start, end = arc - window, arc + window
    if not path.closed:
        start, end = max(start, 0.0), min(end, length)
    return line_class(_arc_points(path, start, end)).buffer(
        offset, cap_style="flat", join_style=_JOIN_STYLES[join], mitre_limit=float(miter_limit)
    )


def _self_crossing_reach(offset: float, sin_angle: float) -> float:
    """How far from a self-crossing a pass must be its own geometry.

    Two ribbons of half-width ``offset`` meeting at angle ``theta`` overlap for about
    ``offset / sin(theta)`` along each pass, so a window of a couple of widths around the
    crossing contains that overlap. The cut is the *intersection* inside the window, so
    the result does not depend on the window size as long as it is large enough; the
    ``0.2`` clamp matches the one the stroke backend uses for shallow crossings.
    """
    return 2.0 * offset / max(abs(float(sin_angle)), 0.2)


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
    pass_windows: bool = False,
) -> dict[str, list[_Strip]]:
    """Sections of the paths that cross themselves, keyed by path ID.

    ``pass_windows`` additionally splits a window either side of every self-crossing pass.
    The Boolean backend needs that: it cuts the under pass, and without the windows the
    piece between the crossing's two split points holds the material of *both* passes, so
    cutting it would erase the strand that is supposed to stay on top. The arrangement
    backend owns whole faces and works off the plain crossing splits, so it leaves the flag
    alone and stays unaffected by the Boolean backend's cut geometry.
    """
    split_arcs: dict[str, list[float]] = {path_id: [] for path_id in bands}
    for crossing in self_crossings:
        split_arcs[crossing.path_a].extend((crossing.s_a, crossing.s_b))
        if not pass_windows:
            continue
        reach = _self_crossing_reach(offset, crossing.sin_angle)
        for arc in (crossing.s_a, crossing.s_b):
            split_arcs[crossing.path_a].extend((arc - reach, arc + reach))
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


def _union_or_none(parts: list[Any], unary_union: Any) -> Any | None:
    """The union of the non-empty parts, or ``None`` when none of them has area."""
    live = [part for part in parts if part is not None and not part.is_empty]
    if not live:
        return None
    return live[0] if len(live) == 1 else unary_union(live)


#: Above this many parts :func:`_covered_area` stops trying the exact union. The exact
#: path runs three orders of pairwise ``union`` with a ``covers`` check per part, i.e.
#: O(n^2) Shapely overlays, which made dense short-path inputs (48 crossings, > 5 minutes)
#: pathologically slow while telling us nothing the caller's arithmetic cross-check — a
#: union is never larger than the sum of the parts' own areas — cannot.
_COVERED_AREA_EXACT_LIMIT = 64


def _union_chain(parts: list[Any]) -> Any:
    """Union a list of geometries without depending on ``shapely.ops``."""
    running = parts[0]
    for part in parts[1:]:
        running = running.union(part)
    return running


def _covered_area(
    parts: list[Any],
    *,
    unary_union: Any | None = None,
) -> float:
    """The area ``parts`` cover: every one of them, overlaps counted once.

    A one-shot ``unary_union`` can drop a part that only touches its neighbours along
    an edge — measured on a 158-region render, where 40 of the parts came out
    uncovered and the area 5e-2 short, in every operand order — which would understate
    what the renderer paints and make the area check cry wolf. So for a small set of
    parts they are unioned one at a time, the result is checked against every part, and
    the orders are tried both ways: a lossy union is a lower bound of the true one, so a
    verified attempt is exact and the larger of the attempts is the better estimate.

    That exact path is O(n^2) Shapely overlays, so it is only taken while there are
    ``_COVERED_AREA_EXACT_LIMIT`` parts or fewer. Above that a one-shot union is used
    instead: the result is then an estimate, and — like any union of these parts — it is
    never larger than the sum of their own areas. ``render_region_geometry`` holds that
    arithmetic bound independently (``region_area_sum``) and uses it to catch, and to
    correct, a union that overstates the area; overstating is the failure mode an
    invalid polygon (duplicate vertices, a self-touch) can cause, while the exact path
    below only defends against *understating*.
    """
    live = [part for part in parts if part is not None and not part.is_empty]
    if not live:
        return 0.0
    if len(live) == 1:
        return float(live[0].area)
    if len(live) > _COVERED_AREA_EXACT_LIMIT:
        unioned = unary_union(live) if unary_union is not None else _union_chain(live)
        return float(unioned.area)
    best: Any | None = None
    for order in (live, live[::-1], sorted(live, key=lambda part: -part.area)):
        running = order[0]
        for part in order[1:]:
            running = running.union(part)
        if all(running.covers(part) for part in live):
            return float(running.area)
        if best is None or float(running.area) > float(best.area):
            best = running
    return float(best.area)


def _sections_around(
    group: list[_Strip], arc: float, reach: float, path: PolylinePath
) -> list[_Strip]:
    """The sections covering ``arc ± reach``: the material of one pass at a crossing.

    ``build_sections`` cuts a window either side of every self-crossing pass, so this is a
    contiguous run of sections that belongs to that pass alone (the other pass's material
    lives in its own run, and the long piece between the two windows belongs to neither).
    """
    length = float(path.length)
    low, high = arc - reach, arc + reach
    spans = [(low, high)]
    if path.closed:
        # A closed path wraps, so the window also matches the shifted copies of itself.
        spans += [(low + length, high + length), (low - length, high - length)]
    found = []
    for strip in group:
        for low, high in spans:
            if strip.start_arc < high - 1e-12 and strip.end_arc > low + 1e-12:
                found.append(strip)
                break
    return found


def _self_crossing_lens(
    under_sections: list[_Strip],
    over_sections: list[_Strip],
    visible: dict[str, Any],
    point: tuple[float, float],
    window: Any,
    *,
    unary_union: Any,
    point_class: Any,
) -> Any | None:
    """The offset-band overlap at a self-crossing, i.e. exactly where the over pass covers.

    A self-crossing's two passes are two different runs of sections of one path, so the
    question is the same one asked at a cross-path crossing — "where does the strand on
    top actually cover the strand below?" — and is answered the same way: intersect the
    two offset bands and keep the component that contains this crossing point
    (:func:`_local_lens`). Both sides are clipped to the window first, which is what keeps
    the cut local: the sections themselves run far away from the crossing, and only the
    overlap *at* the crossing may be removed.

    Both sides are taken as they currently stand, so a pass that was already cut loses
    (and protects) only what it really shows: a cut can never open a gap the over pass
    does not cover.
    """
    under = _union_or_none(
        [visible[strip.strip_id].intersection(window) for strip in under_sections], unary_union
    )
    over = _union_or_none(
        [visible[strip.strip_id].intersection(window) for strip in over_sections], unary_union
    )
    if under is None or over is None:
        return None
    lens = _local_lens(under, over, point, point_class)
    if lens is None or lens.is_empty:
        return None
    return lens


def _boundary_segments(geometry: Any) -> list[tuple[np.ndarray, np.ndarray]]:
    """The edges of a geometry's rings as ``(start, end)`` pairs."""
    if geometry is None or geometry.is_empty:
        return []
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    for polygon in _polygons(geometry):
        ring = np.asarray(polygon.exterior.coords, dtype=float)[:, :2]
        for start, end in zip(ring[:-1], ring[1:], strict=False):
            segments.append((start, end))
    return segments


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
        polygon_class=Polygon, unary_union=unary_union, pass_windows=True,
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
    # The boundary of every lens that was actually subtracted: the weave notches a
    # renderer still has to stroke lie on it (see ``mark_flush_edges``).
    weave_edges: list[tuple[np.ndarray, np.ndarray]] = []
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
            # One path: both passes are sections of the same ribbon. They are still two
            # different passes, so the under one is cut exactly like a cross-path
            # crossing, by the local overlap of the two offset bands. Leaving the cut to
            # the paint order only works while a consistent order exists, and an odd
            # cycle of self-crossings has none (the solver says so through its
            # self-crossing conflict witnesses).
            under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
            over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
            path = geometry_by_id.get(crossing.path_a)
            group = strips.get(crossing.path_a, [])
            self_crossing_count += 1
            if path is None or not group:
                walk.add({"kind": "skip", "reason": "self_crossing_without_sections",
                          "crossing_id": crossing.crossing_id})
                continue
            reach = _self_crossing_reach(offset, crossing.sin_angle)
            under_sections = _sections_around(group, under_arc, reach, path)
            over_sections = _sections_around(group, over_arc, reach, path)
            if not under_sections or not over_sections:
                lens_miss_count += 1
                walk.add({"kind": "skip", "reason": "self_crossing_without_sections",
                          "crossing_id": crossing.crossing_id})
                continue
            window = Point(float(crossing.point[0]), float(crossing.point[1])).buffer(reach)
            lens = _self_crossing_lens(
                under_sections, over_sections, visible_strip, crossing.point, window,
                unary_union=unary_union, point_class=Point,
            )
            if lens is None:
                lens_miss_count += 1
                walk.add({"kind": "skip", "reason": "no_local_overlap",
                          "crossing_id": crossing.crossing_id})
                continue
            # Cut with the overlap of the two passes' *own bands*, not with the lens the
            # window-clipped intersection above produced. The clipped one both stops short
            # of the real footprint and carries section caps (seams, not notches) in its
            # boundary, so the piece left over reaches past the cut: the renderer then had
            # no ring edge along the far end of the notch and its stroke stopped in the
            # middle of the ribbon (measured on `n = 7` CA: 4 stroke ends dangling, 0 in
            # the arrangement backend). Intersecting with the pass on top's *visible*
            # material keeps the old guarantee that a cut never opens a gap the over pass
            # does not cover.
            arm_window = _self_crossing_reach(offset, crossing.sin_angle)
            arms = [
                _arm_strip(
                    path, arc, arm_window, offset=offset, join=join,
                    miter_limit=miter_limit, line_class=LineString,
                )
                for arc in (under_arc, over_arc)
            ]
            arm_lens = _local_lens(arms[0], arms[1], crossing.point, Point)
            if arm_lens is not None:
                over_visible = _union_or_none(
                    [visible_strip[strip.strip_id] for strip in over_sections], unary_union
                )
                footprint = (
                    None if over_visible is None else arm_lens.intersection(over_visible)
                )
                if footprint is not None and not footprint.is_empty:
                    lens = footprint
                weave_edges.extend(_boundary_segments(arm_lens))
            else:
                weave_edges.extend(_boundary_segments(lens))
            removed = _subtract_from_strips(under_sections, visible_strip, lens)
            removed_area += removed
            cut_count += 1
            section_cut_count += 1
            walk.add({"kind": "weave", "crossing_id": crossing.crossing_id,
                      "under": [strip.strip_id for strip in under_sections],
                      "over": [strip.strip_id for strip in over_sections],
                      "target": "self-section", "lens_area": float(lens.area),
                      "removed_area": float(removed)})
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
            weave_edges.extend(_boundary_segments(lens))
            walk.add({"kind": "weave", "crossing_id": crossing.crossing_id,
                      "under": under_id, "over": over_id, "target": "section",
                      "lens_area": float(lens.area), "removed_area": float(removed)})
            continue
        before = float(current.area)
        visible_band[under_id] = current.difference(lens)
        removed = before - float(visible_band[under_id].area)
        removed_area += removed
        cut_count += 1
        weave_edges.extend(_boundary_segments(lens))
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
                "路径层面的过／欠约束存在环，绘制顺序只能按节点顺序确定性打破；"
                "交叉处的上下关系由几何切口决定（被压的分段已按偏移带求交挖掉），"
                "因此该环不再决定任何交叉的结果，只影响未切口的重叠分段之间的先后。"
            ),
            details={"constraints": [[under, over] for under, over in congested]},
            hints=(
                "两条股线交叉偶数次、或单条路径自交时该环都可能出现，不影响编织结果。",
                "不透明填充仍应按 draw_index 递增绘制。",
            ),
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
    hole_chords: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for path in paths:
        group = strips.get(path.path_id)
        if group:
            # The sections stay separate pieces: a piece boundary is what draws the strand
            # on top (its silhouette crossing the strand below it), so merging them back
            # would remove the weave itself. The chords where the path was split are marked
            # as flush afterwards and skipped by the renderer instead (see
            # ``mark_flush_edges``).
            parts = [
                (strip.strip_id, visible_strip[strip.strip_id]) for strip in group
                if not visible_strip[strip.strip_id].is_empty
            ]
        else:
            band = visible_band.get(path.path_id)
            parts = [(path.path_id, band)] if band is not None and not band.is_empty else []
        for node, geometry in parts:
            pieces, chords = _open_occlusion_holes(
                geometry,
                path=path,
                crossings=[
                    crossing for crossing in weavable
                    if path.path_id in (crossing.path_a, crossing.path_b)
                ],
                source_hole_areas=source_hole_areas.get(path.path_id, []),
                offset=offset,
            )
            if chords:
                hole_chords.setdefault(path.path_id, []).extend(chords)
            for index, polygon in enumerate(pieces):
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
    union_area = _covered_area(ribbon_parts, unary_union=unary_union)
    painted_area = _covered_area(painted_parts, unary_union=unary_union)
    region_area_sum = float(sum(region.area for region in regions))
    tolerance = max(area_tolerance * max(union_area, 1.0), 1e-12)
    # Arithmetic cross-check that needs no geometry: a union can never be larger than the
    # sum of the parts it unions, and the emitted regions tile exactly the painted parts
    # (opening an occlusion hole only re-splits a polygon; it does not change its area),
    # so ``region_area_sum`` is the same number with overlaps counted twice. A
    # ``painted_area`` above it is therefore a Boolean-engine error, not geometry: it is
    # what happens when ``_covered_area`` unions an invalid polygon (duplicate vertices,
    # a self-touch) and an occlusion hole is filled back in. This used to pass silently —
    # the mismatch check below only looks for painted *smaller* than the reference — and,
    # measured on `ros-n10-pa-l12-o05`, reported a visible area of 37.70 for 161 regions
    # whose areas sum to 10.18, which is impossible. ``region_area_sum`` is the
    # trustworthy number here and becomes the value.
    if painted_area > region_area_sum + tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-AREA-MISMATCH",
            severity=Severity.WARNING,
            message=(
                "可见区域面积大于各区域面积之和：并集不可能大于各部件之和，"
                "这是布尔运算对带孔或自接触多边形求并时把孔填回造成的记账错误。"
                "区域面积之和是可信值，已以它为准；区域几何本身仍是对的。"
            ),
            details={
                "painted_area": painted_area,
                "region_area_sum": region_area_sum,
                "difference": painted_area - region_area_sum,
                "tolerance": tolerance,
            },
            hints=(
                "这是一处静默记账错误，画面不受影响；可用 arrangement 后端核对同一输入。",
                "细丝带（lens 整个落在被压丝带内部）最容易触发。",
            ),
        ))
        painted_area = region_area_sum
    whole_union = float(unary_union(list(bands.values())).area) if bands else 0.0
    section_seam = bool(strips) and abs(union_area - whole_union) > tolerance
    if section_seam:
        diagnostics.append(Diagnostic(
            code="REGION-SECTION-SEAM",
            severity=Severity.INFO,
            message=(
                "分段并集与整条丝带并集有差异：某个切分点落在折线顶点上，两段之间要么"
                "少了拐角连接的面积、要么互相重叠了一块，因此分段面积之和不是丝带面积。"
            ),
            details={"section_area": union_area, "band_area": whole_union},
            hints=("提高采样密度让交叉落在段中，或减小 offset，可让差异消失。",),
        ))
    if region_area_sum > painted_area + tolerance:
        # Only when the emitted pieces really do overlap somewhere. Self-crossing sections
        # are merged back after their cuts, so what is left is the case the Boolean model
        # cannot answer: strands that overlap without crossing (nearly parallel ribbons).
        diagnostics.append(Diagnostic(
            code="REGION-OVERLAPPING-SECTIONS",
            severity=Severity.INFO,
            message=(
                "输出的片段互相重叠（区域面积之和大于可见面积）：自交分段在切口之外仍可能互相重叠，"
                "没有交叉点的贴近平行丝带也会互相覆盖，重叠处由 draw_index 决定先后。"
            ),
            details={
                "region_area_sum": region_area_sum,
                "painted_area": painted_area,
            },
            hints=("填充时按 RibbonRegion.draw_index 递增绘制；可见面积请用 painted_area。",),
        ))
    # ``union_area`` is the union of the *sections*, which is only a fair reference while
    # they tile the ribbon; when a split point lands on a vertex (``section_seam``) their
    # union is smaller than the ribbon, and the ribbon union is the honest yardstick.
    reference_area = whole_union if section_seam else union_area
    if ribbon_parts and painted_area < reference_area - tolerance:
        diagnostics.append(Diagnostic(
            code="REGION-AREA-MISMATCH",
            severity=Severity.WARNING,
            message=(
                "可见区域总面积小于丝带并集面积：某处被切除的区域没有被上方丝带覆盖"
                "（通常是三条以上丝带在非交叉点处互相重叠）。"
            ),
            details={
                "painted_area": painted_area,
                "union_area": union_area,
                "band_area": whole_union,
                "reference_area": reference_area,
                "difference": painted_area - reference_area,
                "tolerance": tolerance,
            },
            hints=("检查是否有三条以上丝带在同一区域重叠；必要时减小 offset 或改回描边后端。",),
        ))
    cuts = _cut_lines(paths, strips, offset=offset)
    for path_id, chords in hole_chords.items():
        # The chords that opened an occlusion hole are seams too: the strand runs straight
        # through them, so they must not be stroked and the fill must be closed over them.
        cuts.setdefault(path_id, []).extend(chords)
    node_bands: dict[str, Any] = {}
    for group in strips.values():
        for strip in group:
            node_bands[strip.strip_id] = strip.band
    for path_id, band in bands.items():
        if path_id not in strips:
            node_bands[path_id] = band
    flush_edge_count = mark_flush_edges(
        regions, cuts=cuts, weave=weave_edges, node_bands=node_bands
    )
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
            "flush_edge_count": flush_edge_count,
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
