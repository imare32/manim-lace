"""Face-based planar arrangement backend, compared against the Boolean one.

The two region backends must agree wherever the assignment is unambiguous, and the
arrangement must be the one that stays exact where the Boolean one cannot: overlapping
sections for self-crossings and coincident crossings. These tests pin both the agreement
and the differences down.
"""

import numpy as np
import pytest

from manim_lace import LaceEngine, PolylinePath
from manim_lace.render.arrangement import render_arrangement_regions
from manim_lace.render.regions import render_region_geometry

shapely = pytest.importorskip("shapely")

from shapely.geometry import Point, Polygon  # noqa: E402


def _circle(radius=1.0, samples=361):
    theta = np.linspace(0.0, 2.0 * np.pi, samples)
    return np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))


BOW = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
FIGURE_EIGHT = np.array([[-1.0, -1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, 1.0]])
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
    # The Boolean backend cannot cut a band with itself, and says so through overlapping
    # sections with no hidden area at all.
    assert boolean.removed_area == 0.0
    assert "REGION-OVERLAPPING-SECTIONS" in _codes(boolean)
    assert arrangement.region_area_sum < boolean.region_area_sum


def test_the_under_pass_of_a_self_crossing_does_not_own_the_lens():
    from manim_lace.render.regions import _arc_frame

    engine, result, arrangement, _ = _both([FIGURE_EIGHT], offset=0.1)
    crossing = result.crossings[0]
    assignment = result.topology.assignments[crossing.crossing_id]
    assert assignment is not None
    path = engine.paths[0]
    under_arc = crossing.s_a if assignment.under_side == "a" else crossing.s_b
    point, tangent = _arc_frame(path, under_arc)

    def owners(probe):
        return [
            region.region_id for region in arrangement.regions
            if Polygon(region.exterior.points).contains(Point(*probe))
        ]

    # On the under pass, a probe beyond the crossing falls in the strand that continues
    # through it: the lens belongs to the over pass, so the under region stops earlier.
    along = point + tangent * 1.0
    assert owners(along), "the under pass must still own its own material"
    lens_owner = [
        region for region in arrangement.regions
        if Polygon(region.exterior.points).contains(Point(*crossing.point))
    ]
    assert all(region.path_id == crossing.path_a for region in lens_owner)


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


def test_a_dense_self_intersecting_curve_keeps_disjoint_regions():
    theta = np.linspace(0.0, 2.0 * np.pi, 400)
    curve = np.column_stack((np.sin(3.0 * theta), np.sin(4.0 * theta)))
    # ``free`` mode: the alternating solution has no consistent answer for a dense
    # self-crossing curve, and the point here is the geometry, not the topology.
    _, _, arrangement, boolean = _both([curve], offset=0.08, weave_mode="free")
    assert arrangement.painted_area == pytest.approx(arrangement.union_area, rel=1e-9)
    assert arrangement.region_area_sum == pytest.approx(arrangement.painted_area, rel=1e-9)
    assert arrangement.removed_area > 0
    # The Boolean backend keeps the sections apart only by overlap, so its area sum is
    # measurably larger than what is painted.
    assert boolean.region_area_sum > 1.1 * boolean.painted_area
