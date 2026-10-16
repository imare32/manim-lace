"""Face-based planar arrangement backend, compared against the Boolean one.

The two region backends must agree wherever the assignment is unambiguous — including
self-crossings, which the Boolean backend cuts on the under pass just like a cross-path
crossing. They then part ways where the Boolean one runs out of room: it can still leave
sections overlapping, and only the arrangement owns every face exactly once. These tests
pin both the agreement and the differences down.
"""

import numpy as np
import pytest

from manim_lace import LaceEngine, PolylinePath
from manim_lace.render.arrangement import render_arrangement_regions
from manim_lace.render.regions import render_region_geometry

shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString, Point, Polygon  # noqa: E402


def _circle(radius=1.0, samples=361):
    theta = np.linspace(0.0, 2.0 * np.pi, samples)
    return np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))


BOW = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
FIGURE_EIGHT = np.array([[-1.0, -1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, 1.0]])


def _pentagram(radius=1.0):
    """The star polygon {5/2}: one closed path that crosses itself five times.

    Its crossings are far enough apart that the sections between them belong to a single
    pass, which is what lets a test tell the two passes of a self-crossing apart.
    """
    angles = np.pi / 2.0 + np.arange(5) * 2.0 * np.pi / 5.0
    order = (np.arange(5) * 2) % 5
    return radius * np.column_stack((np.cos(angles[order]), np.sin(angles[order])))


PENTAGRAM = _pentagram()
THREE_LINES = [
    np.array([[-1.0, -1.0], [2.0, 0.2]]),
    np.array([[-1.0, 0.5], [2.0, -1.0]]),
    np.array([[-0.5, -1.2], [0.2, 1.4]]),
]


def _both(paths, offset=0.12, **kwargs):
    engine = LaceEngine(
        paths, offset=offset, render_mode="ribbon", conflict_strategy="relax", **kwargs
    )
    result = engine.solve()
    arrangement = render_arrangement_regions(
        engine.paths, result.crossings, result.topology, offset=offset
    )
    boolean = render_region_geometry(
        engine.paths, result.crossings, result.topology, offset=offset
    )
    return engine, result, arrangement, boolean


def _codes(render_result):
    return sorted({diagnostic.code for diagnostic in render_result.diagnostics})


def test_regions_never_overlap_so_the_sum_is_the_painted_area():
    for paths in ([_circle(), np.array([[-2.0, 0.0], [2.0, 0.0]])], [BOW], [FIGURE_EIGHT]):
        _, _, arrangement, _ = _both(paths)
        assert arrangement.region_area_sum == pytest.approx(arrangement.painted_area, abs=1e-9)
        assert arrangement.painted_area == pytest.approx(arrangement.union_area, abs=1e-9)
        assert "REGION-AREA-MISMATCH" not in _codes(arrangement)


def test_the_two_backends_agree_on_ordinary_crossings():
    for paths in ([_circle(), np.array([[-2.0, 0.0], [2.0, 0.0]])], THREE_LINES):
        _, _, arrangement, boolean = _both(paths)
        assert arrangement.painted_area == pytest.approx(boolean.painted_area, abs=1e-9)
        assert arrangement.union_area == pytest.approx(boolean.union_area, abs=1e-9)
        # Both hide the same total area: the Boolean one removes it, the arrangement
        # simply does not give it to the strand underneath.
        assert arrangement.removed_area == pytest.approx(boolean.removed_area, abs=1e-9)
        assert arrangement.region_area_sum == pytest.approx(boolean.region_area_sum, abs=1e-9)


def test_a_self_crossing_lens_equals_the_analytic_overlap():
    # Two 90 degree passes of the same ribbon: the hidden area is (2 * offset)^2 / sin 90.
    offset = 0.12
    _, _, arrangement, boolean = _both([BOW], offset=offset)
    expected = 4.0 * offset * offset
    assert arrangement.removed_area == pytest.approx(expected, rel=1e-6)
    # The Boolean backend cuts the under pass of a self-crossing by the same local overlap
    # of the two offset bands, so it hides exactly the same area.
    assert boolean.removed_area == pytest.approx(expected, rel=1e-6)
    assert boolean.painted_area == pytest.approx(arrangement.painted_area, rel=1e-9)
    assert "REGION-AREA-MISMATCH" not in _codes(boolean)
    assert boolean.region_area_sum == pytest.approx(boolean.painted_area, rel=1e-9)
    assert arrangement.region_area_sum == pytest.approx(boolean.region_area_sum, rel=1e-9)


def test_the_under_pass_of_a_self_crossing_does_not_own_the_lens():
    from manim_lace.render.regions import _arc_frame

    engine, result, arrangement, _ = _both([PENTAGRAM], offset=0.08)
    path = engine.paths[0]
    crossings = [c for c in result.crossings if c.kind == "transverse"]
    assert crossings
    checked = 0
    for crossing in crossings:
        assignment = result.topology.assignments[crossing.crossing_id]
        assert assignment is not None
        under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
        over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
        under_sections = _sections_at(engine, result, path, under_arc, pass_windows=False)
        over_sections = _sections_at(engine, result, path, over_arc, pass_windows=False)
        if not under_sections or not over_sections or under_sections & over_sections:
            continue  # sections too coarse to tell the two passes apart here
        checked += 1
        point, tangent = _arc_frame(path, under_arc)

        def owners(probe):
            return [
                region.region_id for region in arrangement.regions
                if Polygon(region.exterior.points).contains(Point(*probe))
            ]

        # On the under pass, a probe beyond the crossing falls in the strand that continues
        # through it: the lens belongs to the over pass, so the under region stops earlier.
        along = point + tangent * 0.3
        assert owners(along), "the under pass must still own its own material"
        # "Same path" is not enough here: both passes are sections of one path, so the lens
        # has to be checked against the sections that meet the path at the *over* arc.
        lens_owners = owners(point + tangent * 0.01)
        assert lens_owners, "the lens must be painted by somebody"
        for region_id in lens_owners:
            node = region_id.rsplit(".region", 1)[0]
            assert node in over_sections, f"the lens belongs to the over pass, got {node}"
    assert checked, "no crossing could tell the two passes apart"


def _sections_at(engine, result, path, arc, *, pass_windows):
    """The strip ids that meet ``path`` at ``arc``: the local strand of that pass."""
    from shapely.ops import unary_union

    from manim_lace.render.regions import _StripBuilder, build_bands, build_sections

    weavable = [c for c in result.crossings if c.kind == "transverse"]
    diagnostics: list = []
    bands, _holes = build_bands(
        [path], offset=engine.offset, cap_style="butt", join="miter",
        miter_limit=5.0, diagnostics=diagnostics,
    )
    sections = build_sections(
        [path], bands, weavable, offset=engine.offset, cap_style="butt", join="miter",
        miter_limit=5.0, line_class=LineString, point_class=Point,
        polygon_class=Polygon, unary_union=unary_union, pass_windows=pass_windows,
    )
    return {
        strip.strip_id for strip in _StripBuilder.adjacent(
            sections[path.path_id], arc, closed=path.closed, length=float(path.length)
        )
    }


def test_both_backends_cut_the_same_pass_of_a_self_crossing():
    # The lens of a self-crossing is the footprint of the over pass, so whichever backend
    # owns the faces has to give them to the sections that meet the path at the *over*
    # arc: both panels then cut the same ribbon and stroke the weave notch on the other
    # one. The Boolean backend always did; the arrangement handed the lens to whichever
    # covering section sorted first, which at some crossings gave it to the under pass --
    # the weave reversed there, so one panel showed a ribbon cut that the other showed
    # whole, and each panel drew a stroke the other one did not.
    from manim_lace.render.regions import _arc_frame

    offset = 0.08
    engine, result, arrangement, boolean = _both([PENTAGRAM], offset=offset)
    path = engine.paths[0]
    crossings = [c for c in result.crossings if c.kind == "transverse"]
    assert crossings
    checked = 0
    for crossing in crossings:
        assignment = result.topology.assignments[crossing.crossing_id]
        assert assignment is not None
        under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
        over_arc = crossing.s_b if assignment.under_side == "a" else crossing.s_a
        over_sections = _sections_at(engine, result, path, over_arc, pass_windows=False)
        under_sections = _sections_at(engine, result, path, under_arc, pass_windows=False)
        if not over_sections or not under_sections or over_sections & under_sections:
            continue
        checked += 1
        _, under_tangent = _arc_frame(path, under_arc)
        # A point on the under strand just past the crossing: inside the lens, so it is
        # painted by the strand on top and by nobody else.
        probe = np.asarray(crossing.point, dtype=float) + under_tangent * (0.25 * offset)
        owners = [
            region.region_id for region in arrangement.regions
            if Polygon(region.exterior.points).intersects(Point(*probe))
        ]
        assert owners, "the arrangement must paint the lens"
        for region_id in owners:
            node = region_id.rsplit(".region", 1)[0]
            assert node in over_sections, (
                f"arrangement: the lens belongs to the over pass, got {node}"
            )
        # The Boolean backend removes the lens from the under pass, so the same point is
        # painted by the over strand's own (windowed) sections.
        windowed_over = _sections_at(engine, result, path, over_arc, pass_windows=True)
        owners = [
            region.region_id for region in boolean.regions
            if Polygon(region.exterior.points).intersects(Point(*probe))
        ]
        assert owners, "the over strand must cover the under strand's material there"
        for region_id in owners:
            node = region_id.rsplit(".region", 1)[0]
            assert node in windowed_over, (
                f"boolean: the lens belongs to the over pass, got {node}"
            )
    assert checked, "no crossing could tell the two passes apart"


def test_the_arrangement_marks_a_self_crossing_cut_as_a_seam():
    # Every boundary of the arrangement is noded, so a section cut arrives here split into
    # pieces by the other pass's outline. The marking still has to land on the cut line —
    # the chord through the crossing that separates two sections of one strand — and must
    # not land on the weave notch, which is offset from the crossing and is real boundary.
    # The flush set also carries covered sides, so the cut line is picked out by its
    # geometry (it runs through the crossing) instead of by "everything that is flush".
    offset = 0.1
    engine, result, arrangement, _ = _both([FIGURE_EIGHT], offset=offset, weave_mode="free")
    crossing = np.asarray(result.crossings[0].point, dtype=float)
    centerline = LineString(FIGURE_EIGHT)

    # The chords the section split cuts across the strand, rebuilt the way the backend
    # builds them: a chord is told apart from a weave notch by where it runs, and both
    # meet the centreline, so the notch list below excludes exactly these.
    from shapely.ops import unary_union

    from manim_lace.render.regions import _cut_lines, _on_cut, build_bands, build_sections

    bands, _holes = build_bands(
        engine.paths, offset=offset, cap_style="butt", join="miter", miter_limit=5.0,
        diagnostics=[],
    )
    sections = build_sections(
        engine.paths, bands, [c for c in result.crossings if c.kind == "transverse"],
        offset=offset, cap_style="butt", join="miter", miter_limit=5.0,
        line_class=LineString, point_class=Point, polygon_class=Polygon,
        unary_union=unary_union,
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

    def on_cut_line(start, end):
        return (
            0.0 < float(np.hypot(*(end - start))) <= 2.0 * offset
            and crossing_distance(start, end) == pytest.approx(0.0, abs=1e-9)
        )

    cut_pieces = [
        (region, index)
        for region in arrangement.regions
        for index, start, end in edges(region)
        if on_cut_line(start, end)
    ]
    assert cut_pieces, "the geometry must actually have cut pieces to prove anything"
    for region, index in cut_pieces:
        assert index in region.flush_edges, "a section cut is a seam and must not be stroked"

    notches = [
        (region, index)
        for region in arrangement.regions
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


def test_coincident_crossings_conserve_area_in_the_arrangement():
    paths = [BOW, np.array([[-1.2, 0.0], [1.2, 0.0]])]
    _, _, arrangement, boolean = _both(paths)
    # Three strands meet at one point. The arrangement still owns every face exactly once.
    assert arrangement.painted_area == pytest.approx(arrangement.union_area, abs=1e-9)
    assert "REGION-AREA-MISMATCH" not in _codes(arrangement)
    # The assignments genuinely contradict each other there, which is reported.
    assert "REGION-CONFLICTING-OVERLAP" in _codes(arrangement)
    # The Boolean backend cannot keep coverage in that configuration and says so.
    assert "REGION-AREA-MISMATCH" in _codes(boolean)
    assert boolean.painted_area < boolean.union_area


def test_every_ring_of_the_arrangement_is_a_valid_closed_outline():
    _, _, arrangement, _ = _both([_circle(), np.array([[-2.0, 0.0], [2.0, 0.0]])])
    assert arrangement.regions
    for region in arrangement.regions:
        for ring in region.rings:
            polygon = Polygon(ring.points)
            assert polygon.is_valid and polygon.is_simple
            assert np.allclose(ring.points[0], ring.points[-1])
        assert region.exterior.counter_clockwise
        assert all(not hole.counter_clockwise for hole in region.holes)


def test_draw_indices_are_a_total_order_for_renderers():
    _, _, arrangement, _ = _both(THREE_LINES)
    assert sorted(region.draw_index for region in arrangement.regions) == list(
        range(len(arrangement.regions))
    )
    assert [region.region_id for region in arrangement.ordered_regions()] == [
        region.region_id
        for region in sorted(arrangement.regions, key=lambda item: (item.draw_index, item.region_id))
    ]


def test_invalid_arrangement_parameters_are_rejected():
    paths = [PolylinePath(np.array([[0.0, 0.0], [1.0, 0.0]]), path_id="P0000")]
    with pytest.raises(ValueError):
        render_arrangement_regions(paths, [], None, offset=0.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_arrangement_regions(paths, [], None, offset=0.1, join="spline")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        render_arrangement_regions(paths, [], None, offset=0.1, area_tolerance=-1.0)  # type: ignore[arg-type]


def test_the_engine_can_select_the_backend():
    paths = [_circle(), np.array([[-2.0, 0.0], [2.0, 0.0]])]
    arrangement = LaceEngine(
        paths, offset=0.15, render_mode="ribbon", ribbon_backend="arrangement"
    ).solve()
    boolean = LaceEngine(paths, offset=0.15, render_mode="ribbon").solve()
    assert len(arrangement.pieces) == len(arrangement.pieces)
    assert {region.region_id for region in arrangement.pieces} != set()
    assert {region.region_id for region in boolean.pieces} != set()
    accounting = next(
        event for event in arrangement.trace if event.event_type == "region.accounting"
    ).data
    assert accounting["painted_area"] == pytest.approx(accounting["union_area"], abs=1e-9)
    with pytest.raises(ValueError):
        LaceEngine(paths, render_mode="ribbon", ribbon_backend="quadtree")


def test_a_dense_self_intersecting_curve_is_covered_exactly():
    theta = np.linspace(0.0, 2.0 * np.pi, 400)
    curve = np.column_stack((np.sin(3.0 * theta), np.sin(4.0 * theta)))
    # ``free`` mode: the alternating solution has no consistent answer for a dense
    # self-crossing curve, and the point here is the geometry, not the topology.
    _, _, arrangement, boolean = _both([curve], offset=0.08, weave_mode="free")
    assert arrangement.painted_area == pytest.approx(arrangement.union_area, rel=1e-9)
    assert arrangement.region_area_sum == pytest.approx(arrangement.painted_area, rel=1e-9)
    assert arrangement.removed_area > 0
    # The Boolean backend cuts every self-crossing too, so it covers its ribbon exactly;
    # on a curve this dense its sections keep overlapping where no cut touched them, which
    # is what the backend reports instead of hiding.
    assert boolean.painted_area == pytest.approx(boolean.union_area, rel=1e-9)
    assert boolean.removed_area > 0
    assert boolean.region_area_sum > boolean.painted_area
    assert "REGION-OVERLAPPING-SECTIONS" in _codes(boolean)
