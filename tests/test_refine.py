"""Crossing refinement on the source curve (SPEC FR-036).

The events are still detected on the sampled polyline; these tests pin down what
refinement adds when the source curve is available, and that nothing changes when
it is not.
"""

import numpy as np
import pytest

from manim_lace import LaceEngine, PolylinePath, sample_parametric
from manim_lace.geometry.intersections import detect_crossings
from manim_lace.geometry.refine import refine_crossing


def _one_path(func, t_range, *, path_id, closed=False, max_error=1e-3, max_step=None):
    paths = sample_parametric(
        func, t_range, path_id=path_id, closed=closed,
        max_error=max_error, max_step=max_step,
    )
    assert len(paths) == 1, path_id
    return paths[0]


def _event_at(result, predicate, kind="transverse"):
    matches = [c for c in result.crossings if c.kind == kind and predicate(c)]
    assert len(matches) == 1, [c.point for c in result.crossings]
    return matches[0]


def _parameter_of(event, path, *, side):
    """Source parameter of the sampled hit, without using the refinement result."""
    segment = event.segment_a if side == "a" else event.segment_b
    fraction = event.u_a if side == "a" else event.u_b
    start = float(path.parameters[segment])
    return start + fraction * float(path.parameters[segment + 1] - start)


def _circle_and_line():
    circle = _one_path(
        lambda t: (np.cos(t), np.sin(t)), (0.0, 2 * np.pi),
        path_id="circle", closed=True, max_error=1e-3,
    )
    line = _one_path(lambda t: (-2.0 + 4.0 * t, 0.5), (0.0, 1.0), path_id="line")
    return circle, line


def test_refinement_solves_the_crossing_on_the_source_curve():
    circle, line = _circle_and_line()
    exact_x = float(np.sqrt(1.0 - 0.25))
    coarse = detect_crossings([circle, line], refine=False)
    fine = detect_crossings([circle, line], refine=True)
    assert len(coarse.crossings) == len(fine.crossings) == 2

    coarse_event = _event_at(coarse, lambda c: c.point[0] > 0)
    fine_event = _event_at(fine, lambda c: c.point[0] > 0)

    coarse_error = abs(coarse_event.point[0] - exact_x)
    fine_error = abs(fine_event.point[0] - exact_x)
    # The sampled polyline is inside the circle by the flattening tolerance, so the
    # chord crossing misses the true crossing by a visible amount.
    assert coarse_error > 1e-5
    assert fine_error < 1e-9
    assert fine_error * 1e3 < coarse_error

    assert coarse_event.refined is False and fine_event.refined is True
    assert fine_event.parameter_a is not None and fine_event.parameter_b is not None
    assert np.allclose(circle.curve(fine_event.parameter_a), fine_event.point, atol=1e-9)
    assert np.allclose(line.curve(fine_event.parameter_b), fine_event.point, atol=1e-9)
    # The angle now comes from the true tangents: the circle tangent at (x, 0.5) is
    # perpendicular to the radius, the line is horizontal.
    assert fine_event.sin_angle == pytest.approx(float(np.sqrt(1.0 - 0.25)), abs=1e-9)
    assert abs(coarse_event.sin_angle - fine_event.sin_angle) > 1e-5


def test_refinement_replaces_the_chord_angle_at_a_sample_vertex():
    # Both curves pass exactly through the sample vertex, so only the angle can be
    # wrong there: the parabola's chord pair is far from its horizontal tangent.
    parabola = _one_path(
        lambda t: (t, t * t), (-1.0, 1.0), path_id="parabola", max_error=0.2, max_step=0.5,
    )
    line = _one_path(lambda t: (-1.0 + 2.0 * t, -1.0 + 2.0 * t), (0.0, 1.0), path_id="line")
    coarse = detect_crossings([parabola, line], refine=False)
    fine = detect_crossings([parabola, line], refine=True)

    coarse_event = _event_at(coarse, lambda c: True)
    fine_event = _event_at(fine, lambda c: True)
    assert np.allclose(coarse_event.point, (0.0, 0.0), atol=1e-12)
    assert np.allclose(fine_event.point, (0.0, 0.0), atol=1e-12)
    # True tangent (1, 0) against the 45 degree line.
    assert fine_event.sin_angle == pytest.approx(np.sqrt(0.5), abs=1e-9)
    assert coarse_event.sin_angle > 0.9  # the chord pair reports a much shallower angle


def test_refinement_keeps_self_crossing_passes_ordered():
    # The nodal cubic (t^2 - 1, t^3 - t) revisits (0, 0) at t = -1 and t = +1 with
    # tangents (+/-1, 1), i.e. a right angle.
    node = _one_path(
        lambda t: (t * t - 1.0, t**3 - t), (-1.5, 1.5),
        path_id="node", max_error=0.5, max_step=0.5,
    )
    coarse = detect_crossings([node], refine=False)
    fine = detect_crossings([node], refine=True)

    coarse_event = _event_at(coarse, lambda c: True)
    fine_event = _event_at(fine, lambda c: True)
    assert fine_event.path_a == fine_event.path_b == "node"
    assert fine_event.s_a < fine_event.s_b
    assert fine_event.parameter_a == pytest.approx(-1.0, abs=1e-7)
    assert fine_event.parameter_b == pytest.approx(1.0, abs=1e-7)
    assert fine_event.sin_angle == pytest.approx(1.0, abs=1e-9)
    # The chord pair is not exactly wrong here, it is just not the tangent pair.
    assert coarse_event.sin_angle < fine_event.sin_angle - 1e-4


def test_a_real_corner_keeps_the_chord_angle():
    # |t| is sampled as a dense polyline with a genuine kink at t = 0. A corner has
    # no single local tangent, so refinement must decline instead of averaging the
    # two branches into an angle that no part of the path actually has.
    corner = _one_path(
        lambda t: (t, abs(t)), (-1.0, 1.0), path_id="corner", max_error=1e-3, max_step=0.01,
    )
    through_apex = _one_path(lambda t: (0.0, -1.0 + 2.0 * t), (0.0, 1.0), path_id="apex-line")
    through_branch = _one_path(
        lambda t: (0.5, -1.0 + 2.0 * t), (0.0, 1.0), path_id="branch-line"
    )
    paths = [corner, through_apex, through_branch]
    coarse = detect_crossings(paths, refine=False)
    fine = detect_crossings(paths, refine=True)
    assert coarse.stats is not None and fine.stats is not None

    apex = _event_at(coarse, lambda c: np.allclose(c.point, (0.0, 0.0), atol=1e-9))
    refined_apex = _event_at(fine, lambda c: np.allclose(c.point, (0.0, 0.0), atol=1e-9))
    assert apex.kind == refined_apex.kind == "transverse"
    assert refined_apex.refined is False
    # Smoothing the kink would have reported the perpendicular angle (sin 1.0); the
    # event keeps the angle of the branch the line actually crosses.
    assert refined_apex.sin_angle == pytest.approx(apex.sin_angle, abs=1e-12)
    assert refined_apex.sin_angle == pytest.approx(np.sqrt(0.5), abs=1e-9)
    # A crossing in the middle of a straight branch is smooth and still refines.
    branch = _event_at(fine, lambda c: np.allclose(c.point, (0.5, 0.5), atol=1e-9))
    assert branch.refined is True
    assert fine.stats.refined_events == 1


def test_unrefined_events_are_byte_identical_to_the_sampled_result():
    circle, line = _circle_and_line()
    coarse = detect_crossings([circle, line], refine=False)
    fine = detect_crossings([circle, line], refine=True)
    assert coarse.stats is not None and fine.stats is not None
    assert coarse.stats.refined_events == 0
    assert fine.stats.refined_events == 2
    for event in coarse.crossings:
        assert event.refined is False
        assert event.parameter_a is None and event.parameter_b is None


def test_paths_without_a_probe_keep_the_polyline_estimate():
    # Plain coordinate arrays have no evaluable source curve at all: the detector
    # must report exactly what the sampled geometry says.
    paths = [
        PolylinePath(np.column_stack((
            np.cos(np.linspace(0.0, 2 * np.pi, 65)), np.sin(np.linspace(0.0, 2 * np.pi, 65))
        )), path_id="circle", closed=True),
        PolylinePath(np.array([[-2.0, 0.5], [2.0, 0.5]]), path_id="line"),
    ]
    refined = detect_crossings(paths, refine=True)
    plain = detect_crossings(paths, refine=False)
    assert _signature(refined) == _signature(plain)
    assert all(event.refined is False for event in refined.crossings)
    assert refined.stats is not None and refined.stats.refined_events == 0


@pytest.mark.parametrize(
    "broken",
    [
        lambda t: (_ for _ in ()).throw(ZeroDivisionError("undefined")),
        lambda t: (np.nan, np.nan),
        lambda t: (np.inf, 0.0),
    ],
)
def test_an_unreliable_probe_falls_back_instead_of_poisoning_the_event(broken):
    from dataclasses import replace

    circle, line = _circle_and_line()
    circle = replace(circle, curve=broken)
    reliable = detect_crossings([circle, line], refine=False)
    unreliable = detect_crossings([circle, line], refine=True)
    assert _signature(unreliable) == _signature(reliable)
    assert all(event.refined is False for event in unreliable.crossings)


def test_refinement_needs_both_curves_and_both_parameter_mappings():
    a = PolylinePath(np.array([[0.0, -1.0], [0.0, 1.0]]), path_id="a")
    b = PolylinePath(np.array([[-1.0, 0.0], [1.0, 0.0]]), path_id="b")
    plain = refine_crossing(
        a, b, segment_a=0, u_a=0.5, segment_b=0, u_b=0.5,
        point=(0.0, 0.0), position_tol=1e-7,
    )
    assert plain is None
    # A probe without a parameter mapping is not enough either: the Newton iteration
    # works in source-parameter space.
    probing = PolylinePath(
        np.array([[0.0, -1.0], [0.0, 1.0]]), path_id="a", curve=lambda t: (0.0, t)
    )
    assert refine_crossing(
        probing, b, segment_a=0, u_a=0.5, segment_b=0, u_b=0.5,
        point=(0.0, 0.0), position_tol=1e-7,
    ) is None


def test_refinement_does_not_promote_a_path_endpoint_to_a_crossing():
    # A parametric T-junction: the endpoint of one curve lands on the interior of the
    # other. Refinement must not move the endpoint off the path end and turn a
    # diagnostic-only contact into a woven crossing.
    through = _one_path(lambda t: (-1.0 + 2.0 * t, 0.0), (0.0, 1.0), path_id="through")
    ending = _one_path(lambda t: (0.0, t), (0.0, 1.0), path_id="ending")
    result = detect_crossings([through, ending], refine=True)
    event = _event_at(result, lambda c: True, kind="endpoint_touch")
    assert np.allclose(event.point, (0.0, 0.0), atol=1e-12)
    assert min(event.s_b, ending.length - event.s_b) <= 1e-9  # reported at the path end
    assert any(d.code == "GEOM-ENDPOINT_TOUCH" for d in result.diagnostics)


def test_refinement_reports_its_convergence_evidence():
    circle, line = _circle_and_line()
    coarse = detect_crossings([circle, line], refine=False)
    event = _event_at(coarse, lambda c: c.point[0] > 0)
    result = refine_crossing(
        circle, line,
        segment_a=event.segment_a, u_a=event.u_a,
        segment_b=event.segment_b, u_b=event.u_b,
        point=event.point, position_tol=1e-7,
    )
    assert result is not None
    assert 1 <= result.iterations <= 32
    assert result.residual < 1e-10
    assert np.linalg.norm(np.asarray(circle.curve(result.parameter_a))[:2] - result.point) < 1e-12


def test_refinement_is_deterministic():
    circle, line = _circle_and_line()
    first = detect_crossings([circle, line], refine=True)
    second = detect_crossings([circle, line], refine=True)
    assert _signature(first) == _signature(second)


def test_engine_exposes_refinement_through_stats_and_trace():
    circle, line = _circle_and_line()
    result = LaceEngine([circle, line], offset=0.1, weave_mode="free").solve()
    assert result.detection_stats is not None
    assert result.detection_stats.refined_events == 2
    detected = [event for event in result.trace if event.event_type == "crossing.detected"]
    assert len(detected) == 2
    assert all(event.data["refined"] for event in detected)
    assert all(event.data["parameter_a"] is not None for event in detected)
    candidates = [event for event in result.trace if event.event_type == "crossing.candidates"]
    assert candidates[0].data["refined_events"] == 2
    assert result.pieces and all(np.isfinite(piece.points).all() for piece in result.pieces)


def test_engine_can_disable_refinement():
    circle, line = _circle_and_line()
    result = LaceEngine([circle, line], offset=0.1, weave_mode="free", refine=False).solve()
    assert result.detection_stats is not None
    assert result.detection_stats.refined_events == 0
    assert all(event.refined is False for event in result.crossings)


@pytest.mark.parametrize("kwargs", [{"refine": "yes"}, {"refine": 1}])
def test_invalid_refine_knob_is_rejected(kwargs):
    with pytest.raises(ValueError):
        LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])], **kwargs)


def _signature(result):
    return [
        (
            event.crossing_id, event.kind, event.point, event.s_a, event.s_b,
            event.segment_a, event.segment_b, event.sin_angle, event.refined,
            event.parameter_a, event.parameter_b,
        )
        for event in result.crossings
    ]
