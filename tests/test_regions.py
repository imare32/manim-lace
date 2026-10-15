"""Area-based ribbon regions: exact Boolean cutting, rings, holes and accounting.

The backend needs the optional ``shapely`` extra; the validation tests that do not
touch geometry (parameter checks and the missing-dependency hint) run everywhere.
"""

import numpy as np
import pytest

from manim_lace import JoinStyle, LaceEngine, PolylinePath
from manim_lace.render.regions import RibbonRegion, render_region_geometry

shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString, Polygon  # noqa: E402


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


def test_self_crossings_are_reported_instead_of_silently_unwoven():
    bow = np.array([[-1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [1.0, -1.0]])
    result = LaceEngine([bow], offset=0.1, render_mode="ribbon").solve()
    codes = [d.code for d in result.diagnostics]
    assert "REGION-SELF-CROSSING-UNSUPPORTED" in codes
    # The band is kept whole, so the reported area is still the band area.
    accounting = next(event for event in result.trace if event.event_type == "region.accounting").data
    assert accounting["removed_area"] == 0.0
    assert accounting["covered_area"] == pytest.approx(accounting["band_area"], abs=1e-9)


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
