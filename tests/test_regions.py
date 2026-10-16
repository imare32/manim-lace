"""Area-based ribbon regions: exact Boolean cutting, rings, holes and accounting.

The backend needs the optional ``shapely`` extra; the validation tests that do not
touch geometry (parameter checks and the missing-dependency hint) run everywhere.
"""

import numpy as np
import pytest

from manim_lace import JoinStyle, LaceEngine, PolylinePath
from manim_lace.render.regions import (
    RegionRing,
    RibbonRegion,
    _drop_folds,
    mark_flush_edges,
    render_region_geometry,
)

shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402


def _paths(*arrays):
    return [
        PolylinePath(np.asarray(array, dtype=float), path_id=f"P{index:04d}")
        for index, array in enumerate(arrays)
    ]


def _crossing_ribbon_result(offset=0.2, **kwargs):
    paths = [
        np.array([[-2.0, 0.0], [2.0, 0.0]]),
        np.array([[0.0, -2.0], [0.0, 2.0]]),
    ]
    return LaceEngine(paths, offset=offset, weave_mode="free", render_mode="ribbon", **kwargs).solve()


def _circle_and_line(offset=0.2):
    theta = np.linspace(0.0, 2.0 * np.pi, 361)
    circle = np.column_stack((np.cos(theta), np.sin(theta)))
    line = np.array([[-2.0, 0.0], [2.0, 0.0]])
    return LaceEngine(
        [circle, line], offset=offset, weave_mode="free", render_mode="ribbon"
    ).solve()


def _band(points, offset, **kwargs):
    return LineString(np.asarray(points, dtype=float)).buffer(offset, **kwargs)


def test_ribbon_mode_returns_regions_instead_of_stroke_pieces():
    result = _crossing_ribbon_result()
    assert result.render_mode == "ribbon"
    assert result.pieces
    assert all(isinstance(region, RibbonRegion) for region in result.pieces)
    assert {region.path_id for region in result.pieces} == {"P0000", "P0001"}
    assert any(event.event_type == "region.polygon" for event in result.trace)
    assert any(event.event_type == "region.accounting" for event in result.trace)


def test_the_under_ribbon_loses_exactly_the_over_ribbon_footprint():
    result = _crossing_ribbon_result(offset=0.2)
    assignment = result.topology.assignments[result.crossings[0].crossing_id]
    under_id = "P0000" if assignment.under_side == "a" else "P0001"
    over_id = "P0001" if assignment.under_side == "a" else "P0000"
    under_band = _band([[-2.0, 0.0], [2.0, 0.0]] if under_id == "P0000" else [[0.0, -2.0], [0.0, 2.0]],
                       0.2, cap_style="flat", join_style="mitre")
    over_band = _band([[-2.0, 0.0], [2.0, 0.0]] if over_id == "P0000" else [[0.0, -2.0], [0.0, 2.0]],
                      0.2, cap_style="flat", join_style="mitre")
    lens = under_band.intersection(over_band)
    visible = sum(region.area for region in result.pieces if region.path_id == under_id)
    # No radius heuristic: the removed area is the exact Boolean intersection.
    assert visible == pytest.approx(under_band.area - lens.area, abs=1e-9)
    assert not any(d.code == "REGION-AREA-MISMATCH" for d in result.diagnostics)


@pytest.mark.parametrize("offset", [0.1, 0.2, 0.35])
def test_visible_areas_conserve_the_union_of_the_bands(offset):
    for result in (_circle_and_line(offset), _crossing_ribbon_result(offset)):
        accounting = next(
            event for event in result.trace if event.event_type == "region.accounting"
        ).data
        assert accounting["covered_area"] == pytest.approx(accounting["union_area"], abs=1e-9)
        assert accounting["removed_area"] > 0
        assert not any(d.code == "REGION-AREA-MISMATCH" for d in result.diagnostics)


def test_a_closed_ribbon_keeps_its_source_contour_hole():
    theta = np.linspace(0.0, 2.0 * np.pi, 361)
    circle = np.column_stack((2.0 * np.cos(theta), 2.0 * np.sin(theta)))
    result = LaceEngine([circle], offset=0.25, render_mode="ribbon").solve()
    assert len(result.pieces) == 1
    region = result.pieces[0]
    assert len(region.holes) == 1
    hole = region.holes[0]
    # The inner contour is a source hole, not a gap the weave created.
    assert hole.role == "source_contour"
    assert hole.area == pytest.approx(np.pi * (2.0 - 0.25) ** 2, rel=2e-3)
    assert region.exterior.counter_clockwise
    assert not hole.counter_clockwise
    assert np.allclose(hole.points[0], hole.points[-1])


def test_every_ring_is_a_valid_closed_outline():
    result = _circle_and_line()
    for region in result.pieces:
        for ring in region.rings:
            polygon = Polygon(ring.points)
            assert polygon.is_valid, region.region_id
            assert polygon.is_simple, region.region_id
            assert np.allclose(ring.points[0], ring.points[-1])
            assert len(ring.points) >= 4


def test_join_style_changes_sharp_corner_geometry(offset=0.12):
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    miter = LaceEngine([bow], offset=offset, render_mode="ribbon", join="miter").solve()
    bevel = LaceEngine([bow], offset=offset, render_mode="ribbon", join="bevel").solve()
    round_ = LaceEngine([bow], offset=offset, render_mode="ribbon", join="round").solve()
    areas = [
        sum(region.area for region in result.pieces) for result in (miter, bevel, round_)
    ]
    # The sharp bow corners make miter the largest and bevel the smallest outline.
    assert areas[0] > areas[2] > areas[1]


def test_cap_style_changes_open_ribbon_geometry():
    flat = np.array([[0.0, 0.0], [2.0, 0.0]])
    butt = LaceEngine([flat], offset=0.2, render_mode="ribbon").solve()
    rounded = LaceEngine([flat], offset=0.2, render_mode="ribbon", cap_style="round").solve()
    squared = LaceEngine([flat], offset=0.2, render_mode="ribbon", cap_style="square").solve()
    butt_area = sum(region.area for region in butt.pieces)
    round_area = sum(region.area for region in rounded.pieces)
    square_area = sum(region.area for region in squared.pieces)
    assert butt_area == pytest.approx(2.0 * 0.4, abs=1e-9)
    # A round cap adds the two half discs; the Boolean engine discretises the arc, so
    # the area is slightly inside the analytic value.
    assert round_area == pytest.approx(butt_area + np.pi * 0.04, abs=1e-3)
    assert round_area < butt_area + np.pi * 0.04
    # A square cap adds two offset x width rectangles, one per end.
    assert square_area == pytest.approx(butt_area + 2 * 0.2 * 0.4, abs=1e-9)


def test_a_self_crossing_path_is_cut_on_the_under_pass():
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    offset = 0.1
    result = LaceEngine([bow], offset=offset, render_mode="ribbon").solve()
    codes = [d.code for d in result.diagnostics]
    # A self-crossing is woven by cutting area, exactly like a cross-path crossing: the
    # two passes are different sections of one path, and the under one loses the local
    # overlap of the two offset bands. Nothing is left to the paint order.
    assert "REGION-AREA-MISMATCH" not in codes
    assert "REGION-OVERLAPPING-SECTIONS" not in codes
    accounting = next(event for event in result.trace if event.event_type == "region.accounting").data
    # Two 90 degree passes of one ribbon hide one square of side 2 * offset.
    assert accounting["removed_area"] == pytest.approx(4.0 * offset * offset, rel=1e-6)
    assert accounting["painted_area"] == pytest.approx(accounting["band_area"], abs=1e-9)
    assert accounting["region_area_sum"] == pytest.approx(accounting["painted_area"], abs=1e-9)
    assert sorted(region.draw_index for region in result.pieces) == list(range(len(result.pieces)))
    traced = [
        event.object_ids[0] for event in result.trace if event.event_type == "region.polygon"
    ]
    assert traced == [
        region.region_id
        for region in sorted(result.pieces, key=lambda item: (item.draw_index, item.region_id))
    ]


def test_a_self_crossing_marks_the_section_cuts_as_seams_not_the_notches():
    # The seams of a self-crossing are the chords the section split cuts across the
    # strand. The weave notches — the edges where the under pass stops against the over
    # pass's lateral edge — must stay out of that set: they are boundary a renderer has to
    # stroke, and marking them is what drew ticks across the ribbon. The flush set also
    # carries the sides another strand covers (a covered side shows no colour change, so
    # it owes no outline of its own), so the chords are picked out by their geometry
    # rather than by "everything that is flush".
    offset = 0.1
    figure = np.array([[-1.0, -1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, 1.0]])
    engine = LaceEngine([figure], offset=offset, render_mode="ribbon", weave_mode="free")
    result = engine.solve()
    centerline = LineString(figure)
    crossing = np.asarray(result.crossings[0].point, dtype=float)

    # The chords the section split cuts across the strand, rebuilt the way the backend
    # builds them: a chord is told apart from a weave notch by where it runs, and both
    # meet the centreline, so the notch list below excludes exactly these.
    from manim_lace.render.regions import _cut_lines, _on_cut, build_bands, build_sections

    bands, _holes = build_bands(
        engine.paths, offset=offset, cap_style="butt", join="miter", miter_limit=5.0,
        diagnostics=[],
    )
    sections = build_sections(
        engine.paths, bands, [c for c in result.crossings if c.kind == "transverse"],
        offset=offset, cap_style="butt", join="miter", miter_limit=5.0,
        line_class=LineString, point_class=Point, polygon_class=Polygon,
        unary_union=unary_union, pass_windows=True,
    )
    chords = _cut_lines(engine.paths, sections, offset=offset).get(engine.paths[0].path_id, ())

    def edges(region):
        points = np.asarray(region.exterior.points, dtype=float)
        count = len(points) - 1
        for index in range(count):
            yield index, points[index], points[(index + 1) % count]

    def crossing_distance(start, end):
        return LineString([start, end]).distance(Point(*crossing))

    def on_chord(start, end):
        return any(_on_cut(start, end, chord_start, chord_end, 1e-9)
                   for chord_start, chord_end in chords)

    # A section cut is the chord through the crossing that separates two sections; it
    # arrives split into pieces by the other pass's outline, so every piece that runs
    # through the crossing point belongs to it.
    cut_pieces = [
        (region, index)
        for region in result.pieces
        for index, start, end in edges(region)
        if 0.0 < float(np.hypot(*(end - start))) <= 2.0 * offset
        and crossing_distance(start, end) == pytest.approx(0.0, abs=1e-9)
    ]
    assert cut_pieces, "the geometry must actually have section cuts to prove anything"
    for region, index in cut_pieces:
        assert index in region.flush_edges, "a section cut is a seam and must not be stroked"

    notches = [
        (region, index)
        for region in result.pieces
        for index, start, end in edges(region)
        # A notch cuts across the strand: it meets the centreline at a point interior to
        # both, while a covered side only runs along one lateral edge. The chords of the
        # section split meet the centreline too, so they are excluded by name.
        if centerline.crosses(LineString([start, end]))
        and not on_chord(start, end)
    ]
    assert notches, "the geometry must actually have notches for this to prove anything"
    for region, index in notches:
        assert index not in region.flush_edges, "a weave notch is real boundary"


def test_the_self_crossing_cut_keeps_each_pass_material_beside_the_crossing():
    # A figure eight with its crossing in the middle of straight runs: the cut must be
    # local to the crossing. Cutting whole sections instead would erase the material the
    # strand on top still shows right next to the crossing.
    from manim_lace.render.regions import _arc_frame

    figure = np.array([[-1.0, -1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, 1.0]])
    engine = LaceEngine([figure], offset=0.1, render_mode="ribbon", weave_mode="free")
    result = engine.solve()
    crossing = result.crossings[0]
    path = engine.paths[0]
    polygons = [
        Polygon(region.exterior.points, [hole.points for hole in region.holes])
        for region in result.pieces
    ]
    visible = unary_union(polygons)

    for arc in (crossing.s_a, crossing.s_b):
        point, tangent = _arc_frame(path, arc)
        for direction in (1.0, -1.0):
            probe = Point(*(point + tangent * 1.0 * direction))
            assert visible.contains(probe), "each pass keeps its own material beside the crossing"

    # The crossing itself is covered exactly once: the lens belongs to the over pass only,
    # so no piece may overlap another there.
    disk = Point(*crossing.point).buffer(0.02)
    covered = sum(polygon.intersection(disk).area for polygon in polygons)
    assert covered == pytest.approx(visible.intersection(disk).area, abs=1e-9)
    assert covered > 0.0


def test_coincident_crossings_are_reported_because_they_cannot_conserve_area():
    # The bow-tie self-crosses exactly where the line crosses it, so three strands meet
    # at one point. Each crossing removes the overlap it sees, and the two removals
    # cancel each other out, which the backend reports instead of hiding.
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    line = np.array([[-1.2, 0.0], [1.2, 0.0]])
    result = LaceEngine(
        [bow, line], offset=0.12, render_mode="ribbon", conflict_strategy="relax"
    ).solve()
    codes = [d.code for d in result.diagnostics]
    assert "REGION-COINCIDENT-CROSSINGS" in codes
    assert "REGION-AREA-MISMATCH" in codes
    mismatch = next(d for d in result.diagnostics if d.code == "REGION-AREA-MISMATCH")
    assert mismatch.details["difference"] < 0
    assert mismatch.details["tolerance"] > 0


def test_a_zero_area_fold_is_dropped_and_a_real_thin_corner_is_kept():
    # A boolean cut that only touches the boundary can leave the ring running out along a
    # line and straight back. That fold holds no area, but it is part of the ring, so
    # stroking the ring would draw it as a whisker sticking out of the ribbon.
    folded = np.array([
        [0.0, 0.0], [0.04, 0.0], [0.0005, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0],
    ])
    cleaned = _drop_folds(folded)
    # The turnaround vertex goes. What stays is the point the excursion returned to, which
    # now sits on the straight run — the out-and-back itself is what must be gone, and the
    # ring still covers exactly what it covered.
    assert [tuple(point) for point in cleaned] == [
        (0.0, 0.0), (0.0005, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0),
    ]
    assert Polygon(cleaned).area == pytest.approx(Polygon(folded).area)
    # A thin feature the geometry really has is not a fold: it turns back, but it spans area.
    cusp = np.array([[0.0, 0.0], [0.5, 0.02], [1.0, 0.0], [0.5, -1.0], [0.0, 0.0]])
    assert np.array_equal(_drop_folds(cusp), cusp)
    # Removal is idempotent, and a ring too small to fold is returned untouched.
    assert np.array_equal(_drop_folds(cleaned), cleaned)
    degenerate = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]])
    assert np.array_equal(_drop_folds(degenerate), degenerate)


def test_a_wedge_whose_tip_is_near_duplicate_points_survives():
    # A crossing whose two cut chords meet on a band's lateral edge leaves the tip of the
    # wedge as several copies of one point that differ only in the last bits (the polygon
    # boolean's noise). Each copy looks like a zero-area reversal on its own; dropping them
    # all in one pass removed the vertex the ring really turns at, and with it the whole
    # wedge — a hole in the painted ribbon. Folds come off one at a time, so the last copy
    # is judged against the ring's real corners and kept.
    tip = np.array([0.3, 0.4])
    ring = np.array([
        [0.0, 0.0], [1.0, 0.0],
        tip + np.array([0.0, 0.0]),
        tip + np.array([4e-16, 0.0]),
        tip + np.array([-4e-16, 4e-16]),
        [0.0, 1.0], [0.0, 0.0],
    ])
    cleaned = _drop_folds(ring)
    # The wedge keeps its tip, and the ring still covers the same area.
    assert any(np.allclose(point, tip, atol=1e-12) for point in cleaned)
    assert Polygon(cleaned).area == pytest.approx(Polygon(ring).area)


def test_the_weave_notch_is_stroked_even_where_it_is_its_own_band_edge():
    # A notch is the pass on top crossing the pass below, and the edge that carries it
    # belongs to whichever region's ring reaches there. For the pass *on top* that edge
    # is its own band's lateral edge, so the "covered side" test used to hide it — and
    # where the pass below does not carry that piece (its own cut is clipped by the
    # section windows it works through), the notch then ended in the middle of the
    # ribbon. What decides is the visible material: the edge is a notch when this
    # region owns one side of it and the owner changes across it.
    #
    # A is the region under test; B below it (drawn first) is on the left, C above it
    # (drawn last) covers A's top edge on both sides.
    def region(region_id, points, draw_index):
        ring = np.asarray(points, dtype=float)
        return RibbonRegion(
            region_id=region_id, path_id="P0000",
            exterior=RegionRing(points=ring, role="exterior"),
            area=float(Polygon(ring).area), draw_index=draw_index,
        )

    a = region("A.region0", [
        [4.0, 0.0], [8.0, 0.0], [8.0, 2.0], [4.0, 2.0], [4.0, 0.0],
    ], 1)
    b = region("B.region0", [
        [0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0], [0.0, 0.0],
    ], 0)
    # C sits on the middle of A's top side, so it is painted over both sides of that
    # piece of the boundary — but it stays clear of A's left side.
    c = region("C.region0", [
        [6.0, 1.5], [7.0, 1.5], [7.0, 2.5], [6.0, 2.5], [6.0, 1.5],
    ], 2)
    bands = {
        "A": Polygon(a.exterior.points),
        "B": Polygon(b.exterior.points),
        "C": Polygon(c.exterior.points),
    }
    # A's left side (the shared edge with B) and its top side (covered by C in the
    # middle) are both recorded as lens boundaries — both are notches as far as the
    # weave knows.
    weave = [
        (np.array([4.0, 0.0]), np.array([4.0, 2.0])),
        (np.array([8.0, 2.0]), np.array([4.0, 2.0])),
    ]
    mark_flush_edges([a, b, c], cuts={}, weave=weave, node_bands=bands)
    points = np.asarray(a.exterior.points, dtype=float)
    # C's sides split A's top side in three.
    assert [tuple(point) for point in points] == [
        (4.0, 0.0), (8.0, 0.0), (8.0, 2.0), (7.0, 2.0), (6.0, 2.0), (4.0, 2.0),
        (4.0, 0.0),
    ]
    # Edge 5 is A's left side: A is what is visible on its own side and B on the other,
    # so the notch is real and has to be stroked — even though the edge lies on A's own
    # band boundary, which used to be enough to hide it.
    assert 5 not in a.flush_edges, a.flush_edges
    # Edge 3 is the piece of A's top side under C: C is painted over both sides of it,
    # so the notch is hidden underneath and C's own outline is the one owed.
    assert a.flush_edges == (3,), a.flush_edges


def test_the_flush_indices_address_the_ring_the_renderer_draws():
    # One edge can be split — another region's boundary crosses it, so a vertex is
    # inserted — while a pair of near-collinear edges is joined, a vertex folded away. The
    # two cancel out in the point count, and the ring still has to become the joined one:
    # the indices address *that* ring. Measured on the n=7 CA card (Boolean backend,
    # ``P0000#14.region0``): the split and the merge cancelled, the original ring stayed,
    # and one stale index both stroked a covered side — a line across the ribbon — and hid
    # half of the silhouette.
    #
    # A is the region under test: a 4x2 square whose right side is covered by B and whose
    # top side is half covered by C (both the same path, so no colour change), with one
    # collinear vertex pair on the right side that joins. B and C are shaped so that C's
    # lower edge lands exactly on A's top edge from x=2 to x=4: one crossing point, two
    # pieces.
    def region(region_id, points, draw_index):
        ring = np.asarray(points, dtype=float)
        return RibbonRegion(
            region_id=region_id, path_id="P0000",
            exterior=RegionRing(points=ring, role="exterior"),
            area=float(Polygon(ring).area), draw_index=draw_index,
        )

    a = region("A.region0", [
        [0.0, 0.0], [4.0, 0.0], [4.0, 1.0], [4.0, 2.0], [0.0, 2.0], [0.0, 0.0],
    ], 0)
    b = region("B.region0", [
        [4.0, 0.0], [8.0, 0.0], [8.0, 2.0], [4.0, 2.0], [4.0, 0.0],
    ], 1)
    c = region("C.region0", [
        [2.0, 2.0], [4.0, 2.0], [4.0, 2.6], [2.0, 2.6], [2.0, 2.0],
    ], 2)
    bands = {
        "A": Polygon(a.exterior.points),
        "B": Polygon(b.exterior.points),
        "C": Polygon(c.exterior.points),
    }
    marked = mark_flush_edges([a, b, c], cuts={}, weave=(), node_bands=bands)
    points = np.asarray(a.exterior.points, dtype=float)

    # The ring is the joined one: the split vertex is there, the folded corner is not, and
    # the point count happens to be unchanged — which is exactly why comparing counts
    # cannot decide whether to replace it.
    assert [tuple(point) for point in points] == [
        (0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0),
    ]
    # The two hidden runs of A are the covered right side (the joined pair) and the
    # covered half of the top edge; everything else is silhouette and stays stroked.
    assert a.flush_edges == (1, 2), a.flush_edges
    # A's two, plus B's covered left side and C's covered lower edge.
    assert marked == 4, marked
    assert b.flush_edges == (3,), b.flush_edges  # its left side, covered by A
    assert c.flush_edges == (0,), c.flush_edges  # its lower edge, covered by A


def test_a_ribbon_ring_never_keeps_a_folded_vertex():
    # Three interlocked circles -- the gallery's chain card. A boolean cut that only touches
    # the boundary used to leave out-and-back folds in these rings, and the renderer stroked
    # each fold as a short whisker poking into the neighbouring ribbon. Every ring the
    # backend hands out must already be free of them.
    circles = []
    for index, x in enumerate((-1.3, 0.0, 1.3)):
        theta = np.linspace(0.0, 2.0 * np.pi, 721)
        circles.append(np.column_stack((
            0.9 * np.cos(theta) + x,
            0.9 * np.sin(theta) + 0.3 * (index % 2),
        )))
    result = LaceEngine(circles, offset=0.13, render_mode="ribbon").solve()
    assert result.pieces
    rings = [ring for region in result.pieces for ring in (region.exterior, *region.holes)]
    assert rings
    for ring in rings:
        points = np.asarray(ring.points, dtype=float)
        assert len(_drop_folds(points)) == len(points)


def test_missing_assignments_are_reported_per_crossing():
    paths = [np.array([[-1.0, -1.0], [1.0, 1.0]]), np.array([[-1.0, 1.0], [1.0, -1.0]])]
    result = LaceEngine(paths, offset=0.1, render_mode="ribbon", weave_mode="manual").solve()
    assert result.topology.assignments == {}
    missing = [d for d in result.diagnostics if d.code == "REGION-MISSING-ASSIGNMENT"]
    assert len(missing) == len(result.crossings) == 1
    accounting = next(event for event in result.trace if event.event_type == "region.accounting").data
    assert accounting["removed_area"] == 0.0


def test_a_zero_length_path_reports_an_empty_ribbon():
    paths = [
        PolylinePath(np.array([[0.0, 0.0], [1.0, 0.0]]), path_id="ok"),
        PolylinePath(np.array([[0.5, 0.0], [0.5, 0.0]]), path_id="flat"),
    ]
    result = LaceEngine(paths, offset=0.1, render_mode="ribbon").solve()
    empty = [d for d in result.diagnostics if d.code == "REGION-EMPTY-RIBBON"]
    assert [d.path_ids for d in empty] == [("flat",)]
    assert {region.path_id for region in result.pieces} == {"ok"}


def test_invalid_ribbon_parameters_are_rejected():
    paths = _paths([[0.0, 0.0], [1.0, 0.0]])
    with pytest.raises(ValueError):
        render_region_geometry(paths, [], None, offset=0.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_region_geometry(paths, [], None, offset=0.1, cap_style="curly")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_region_geometry(paths, [], None, offset=0.1, join="spline")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_region_geometry(paths, [], None, offset=0.1, area_tolerance=-1.0)  # type: ignore[arg-type]


def test_missing_shapely_is_reported_with_the_install_hint(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("shapely"):
            raise ImportError("blocked for the test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(ImportError, match="manim-lace\\[geometry\\]"):
        render_region_geometry(_paths([[0.0, 0.0], [1.0, 0.0]]), [], None, offset=0.1)  # type: ignore[arg-type]


def test_both_backends_share_the_same_topology():
    paths = [
        np.array([[-2.0, 0.0], [2.0, 0.0]]),
        np.array([[0.0, -2.0], [0.0, 2.0]]),
    ]
    stroke = LaceEngine(paths, offset=0.2, render_mode="stroke").solve()
    ribbon = LaceEngine(paths, offset=0.2, render_mode="ribbon").solve()
    assert [c.crossing_id for c in stroke.crossings] == [c.crossing_id for c in ribbon.crossings]
    assert stroke.topology.assignments == ribbon.topology.assignments
    # Both honour the assignment: the stroke path is cut, the ribbon loses area.
    assert len(stroke.pieces) > len(paths)
    accounting = next(
        event for event in ribbon.trace if event.event_type == "region.accounting"
    ).data
    assert accounting["removed_area"] > 0


def test_join_style_and_miter_limit_reach_the_engine():
    engine = LaceEngine(
        [np.array([[0.0, 0.0], [1.0, 0.0]])],
        offset=0.1, render_mode="ribbon", join="bevel", miter_limit=2.0,
    )
    assert engine.join in JoinStyle.__args__
    assert engine.join == "bevel"
    assert engine.miter_limit == 2.0
