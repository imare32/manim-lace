import numpy as np
import pytest

manim = pytest.importorskip("manim")

from manim_lace.adapters.manim import extract_paths  # noqa: E402
from manim_lace.geometry.intersections import detect_crossings  # noqa: E402


def test_circle_adapter_returns_closed_polyline():
    from manim import Circle

    paths = extract_paths(Circle(radius=1), max_error=0.01)
    assert paths
    assert any(path.closed for path in paths)


def test_adapter_exposes_the_bezier_curves_for_refinement():
    from manim import Circle

    path = extract_paths(Circle(radius=1), max_error=0.01)[0]
    assert path.curve is not None
    assert path.parameters is not None
    # The probe is the source curve, so it agrees with the retained sample points.
    for point, parameter in zip(path.points[:8], path.parameters[:8], strict=True):
        assert np.allclose(np.asarray(path.curve(float(parameter)))[:2], point, atol=1e-12)


def test_ribbons_follow_the_draw_order_and_the_cap_style():
    from manim import CapStyleType, Circle, Line, VGroup

    from manim_lace import Lace

    source = VGroup(
        Circle(radius=1),
        Line(np.array([-2.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])),
    )
    lace = Lace(source, offset=0.15, cap_style="round")
    expected = [piece.piece_id for piece in sorted(lace.result.pieces, key=lambda p: p.draw_index)]
    assert expected
    assert len(lace.ribbons) == len(expected)
    assert [mob.cap_style for mob in lace.ribbons] == [CapStyleType.ROUND] * len(expected)
    assert [mob.z_index for mob in lace.ribbons] == list(range(len(expected)))
    for mob, piece_id in zip(lace.ribbons, expected, strict=True):
        piece = next(item for item in lace.result.pieces if item.piece_id == piece_id)
        corners = np.asarray(mob.points)[:, :2]
        # Manim stores cubic control points; the geometry is verified through the
        # endpoints and the bounding box instead of its internal point layout.
        assert np.allclose(corners[0], piece.points[0], atol=1e-12)
        assert np.allclose(corners[-1], piece.points[-1], atol=1e-12)
        assert np.allclose(corners.min(axis=0), piece.points.min(axis=0), atol=1e-12)
        assert np.allclose(corners.max(axis=0), piece.points.max(axis=0), atol=1e-12)


def test_parametric_facade_defaults_to_butt_caps():
    from manim import CapStyleType

    from manim_lace import Lace

    lace = Lace.from_parametric(
        lambda t: (np.cos(t), np.sin(t)), (0.0, 2 * np.pi), closed=True, offset=0.1
    )
    assert lace.engine.cap_style == "butt"
    assert all(mob.cap_style == CapStyleType.BUTT for mob in lace.ribbons)


def test_ribbon_mode_builds_filled_regions():
    from manim import TEAL, Circle, Line, VGroup

    from manim_lace import Lace

    source = VGroup(
        Circle(radius=1),
        Line(np.array([-2.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])),
    )
    lace = Lace(source, offset=0.15, render="ribbon", stroke_color=TEAL, fill_color=TEAL)
    assert lace.render_mode == "ribbon"
    assert len(lace.ribbons) == len(lace.result.pieces) >= 2
    assert all(mob.get_fill_opacity() == pytest.approx(1.0) for mob in lace.ribbons)
    assert all(mob.get_stroke_width() > 0 for mob in lace.ribbons)
    expected = sorted(lace.result.pieces, key=lambda item: (item.draw_index, item.region_id))
    for mob, region in zip(lace.ribbons, expected, strict=True):
        corners = np.asarray(mob.points)[:, :2]
        assert np.allclose(corners[0], region.exterior.points[0], atol=1e-12)
        assert np.allclose(corners.min(axis=0), region.exterior.points.min(axis=0), atol=1e-9)
        assert np.allclose(corners.max(axis=0), region.exterior.points.max(axis=0), atol=1e-9)


def test_ribbon_holes_are_a_separate_layer():
    from manim import Circle

    from manim_lace import Lace

    with_holes = Lace(Circle(radius=1), offset=0.2, render="ribbon")
    assert len(with_holes.holes) == 1
    assert with_holes.holes[0].get_fill_opacity() == pytest.approx(1.0)

    without_holes = Lace(Circle(radius=1), offset=0.2, render="ribbon", draw_holes=False)
    assert len(without_holes.holes) == 0


def test_ribbon_mode_is_available_from_the_parametric_factory():
    from manim_lace import Lace

    lace = Lace.from_parametric(
        lambda t: (np.cos(t), np.sin(t)), (0.0, 2 * np.pi),
        closed=True, offset=0.1, render="ribbon",
    )
    assert lace.render_mode == "ribbon"
    assert lace.engine.render_mode == "ribbon"
    assert lace.ribbons


def test_unknown_render_mode_is_rejected():
    from manim import Circle

    from manim_lace import Lace

    with pytest.raises(ValueError):
        Lace(Circle(radius=1), render="mesh")
    with pytest.raises(ValueError):
        Lace.from_parametric(lambda t: (t, t), (0.0, 1.0), render="mesh")


def _source_curve_gap(event, path_a, path_b, *, refined):
    """Distance between the two source curves at the event's parameters.

    For a refined event the recorded parameters are used; for a sampled event they
    are reconstructed from the polyline segment and the fraction inside it.
    """
    if refined:
        t_a, t_b = event.parameter_a, event.parameter_b
    else:
        t_a = _segment_parameter(path_a, event.segment_a, event.u_a)
        t_b = _segment_parameter(path_b, event.segment_b, event.u_b)
    point_a = np.asarray(path_a.curve(float(t_a)))[:2]
    point_b = np.asarray(path_b.curve(float(t_b)))[:2]
    return float(np.linalg.norm(point_a - point_b))


def _segment_parameter(path, segment, fraction):
    start = float(path.parameters[segment])
    return start + fraction * float(path.parameters[segment + 1] - start)


def test_manim_crossings_refine_onto_the_real_bezier_curves():
    from manim import Circle, Line, VGroup

    paths = extract_paths(
        VGroup(Circle(radius=1), Line(np.array([0.5, -2.0, 0.0]), np.array([0.5, 2.0, 0.0]))),
        max_error=1e-3,
    )
    circle = next(path for path in paths if path.closed)
    line = next(path for path in paths if not path.closed)
    assert circle.curve is not None and line.curve is not None

    coarse = detect_crossings(paths, refine=False)
    fine = detect_crossings(paths, refine=True)
    assert len(coarse.crossings) == len(fine.crossings) == 2
    assert coarse.stats is not None and fine.stats is not None
    assert coarse.stats.refined_events == 0
    assert fine.stats.refined_events == 2

    # Sorting by arc length keeps the two crossings aligned between the two runs.
    coarse_events = sorted(coarse.crossings, key=lambda event: event.s_b)
    fine_events = sorted(fine.crossings, key=lambda event: event.s_b)
    for coarse_event, fine_event in zip(coarse_events, fine_events, strict=True):
        assert coarse_event.refined is False and fine_event.refined is True
        coarse_gap = _source_curve_gap(coarse_event, circle, line, refined=False)
        fine_gap = _source_curve_gap(fine_event, circle, line, refined=True)
        # The sampled hit is off the Bezier data by the flattening tolerance; the
        # refined parameters solve the source-curve equation.
        assert coarse_gap > 1e-5
        assert fine_gap < 1e-9
        assert coarse_gap > 1e3 * fine_gap
