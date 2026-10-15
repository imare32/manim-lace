"""Area-based ribbon regions: exact Boolean cutting, rings, holes and accounting.

The backend needs the optional ``shapely`` extra; the validation tests that do not
touch geometry (parameter checks and the missing-dependency hint) run everywhere.
"""

import numpy as np
import pytest

from manim_lace import JoinStyle, LaceEngine, PolylinePath
from manim_lace.render.regions import RibbonRegion, _drop_folds, render_region_geometry

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
    # stroke, and marking them is what drew ticks across the ribbon.
    offset = 0.1
    figure = np.array([[-1.0, -1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, 1.0]])
    result = LaceEngine([figure], offset=offset, render_mode="ribbon", weave_mode="free").solve()
    centerline = LineString(figure)

    def edges(region):
        points = np.asarray(region.exterior.points, dtype=float)
        count = len(points) - 1
        for index in range(count):
            yield index, points[index], points[(index + 1) % count]

    def band_distance(start, end):
        """Distance from the edge's middle to the centreline of the strand."""
        return centerline.distance(Point(*(0.5 * (start + end))))

    seams = [
        (region, start, end)
        for region in result.pieces
        for index, start, end in edges(region)
        if index in region.flush_edges
    ]
    assert seams
    for region, start, end in seams:
        assert float(np.hypot(*(end - start))) == pytest.approx(2.0 * offset, abs=1e-9)
        # A chord across the strand is centred on it; a notch follows the other pass's
        # lateral edge and is one band width away from the centreline instead.
        assert band_distance(start, end) == pytest.approx(0.0, abs=1e-9)

    notches = [
        (region, index)
        for region in result.pieces
        for index, start, end in edges(region)
        if index not in region.flush_edges
        and float(np.hypot(*(end - start))) == pytest.approx(2.0 * offset, abs=1e-9)
        and band_distance(start, end) == pytest.approx(offset, abs=1e-9)
    ]
    assert notches, "the geometry must actually have notches for this to prove anything"


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
    assert len(cleaned) == len(folded) - 2
    assert [tuple(point) for point in cleaned] == [
        (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0),
    ]
    # A thin feature the geometry really has is not a fold: it turns back, but it spans area.
    cusp = np.array([[0.0, 0.0], [0.5, 0.02], [1.0, 0.0], [0.5, -1.0], [0.0, 0.0]])
    assert np.array_equal(_drop_folds(cusp), cusp)
    # Removal is idempotent, and a ring too small to fold is returned untouched.
    assert np.array_equal(_drop_folds(cleaned), cleaned)
    degenerate = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]])
    assert np.array_equal(_drop_folds(degenerate), degenerate)


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
