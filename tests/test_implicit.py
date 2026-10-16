"""The independent isocontour extractor for implicit curves (SPEC FR-008).

Every number asserted here was measured on this implementation, and the tests that pin a
*limitation* say so explicitly — when FR-009/FR-010 (endpoint snapping) lands, the
self-touching tests are expected to change, deliberately, with the new behaviour recorded.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from manim_lace import LaceEngine, sample_implicit
from manim_lace.geometry.implicit import ORIENTATION_RULES


def _sample(field, x_range=(-2.0, 2.0), y_range=(-2.0, 2.0), **kwargs):
    """Sample one field and return its paths plus the honest summary."""
    summaries: list[dict] = []
    paths = sample_implicit(field, x_range, y_range,
                            subdivision_tracer=summaries.append, **kwargs)
    assert len(summaries) == 1
    return paths, summaries[0]


def _circle(x, y):
    return x * x + y * y - 1.0


def _signed_area(points: np.ndarray) -> float:
    return 0.5 * float(np.sum(
        points[:-1, 0] * points[1:, 1] - points[1:, 0] * points[:-1, 1]
    ))


# ---------------------------------------------------------------------------
# The basic contract: one path per connected branch
# ---------------------------------------------------------------------------


def test_a_circle_is_one_closed_branch_inside_its_error_target() -> None:
    paths, summary = _sample(_circle)

    assert len(paths) == 1
    path = paths[0]
    assert path.closed is True
    assert path.source.object_type == "implicit_curve"
    radii = np.linalg.norm(path.points, axis=1)
    # The first pass at 96x96 already meets max_error=1e-3, so the radii are that close.
    assert np.allclose(radii, 1.0, atol=1e-3), (radii.min(), radii.max())
    assert summary["final_residual"] <= 1e-3
    assert summary["pass_count"] == 1
    assert summary["resolution"] == [96, 96]
    assert path.sampling_error == pytest.approx(summary["final_residual"])


def test_two_components_of_one_level_set_become_two_paths() -> None:
    """FR-008: multiple connected components must be split, with their origin recorded."""
    paths, summary = _sample(lambda x, y: (x * x + y * y - 1.0) * (x * x + y * y - 4.0),
                             (-3.0, 3.0), (-3.0, 3.0))

    assert len(paths) == 2
    assert all(path.closed for path in paths)
    radii = sorted(float(np.linalg.norm(path.points, axis=1).mean()) for path in paths)
    assert radii == pytest.approx([1.0, 2.0], abs=1e-2)
    assert summary["closed_branch_count"] == 2
    # Each branch carries its own provenance: which component, from which grid and level.
    for index, path in enumerate(paths):
        metadata = path.source.metadata
        assert metadata["branch_index"] == index
        assert path.source.subpath_index == index
        assert metadata["level"] == 0.0
        assert metadata["resolution"] == summary["resolution"]
        assert metadata["seed_edge"] is not None
        assert metadata["within_error_target"] is True
    assert [path.path_id for path in paths] == ["P0000", "P0000.01"]


def test_a_nonzero_level_is_the_contour_of_that_level() -> None:
    paths, _summary = _sample(_circle, level=0.75)
    radii = np.linalg.norm(paths[0].points, axis=1)
    assert radii == pytest.approx(math.sqrt(1.75), abs=2e-3)


# ---------------------------------------------------------------------------
# Error control is measured, not asserted
# ---------------------------------------------------------------------------


def test_a_tighter_target_refines_further_and_measures_a_smaller_error() -> None:
    _loose_paths, loose = _sample(_circle, max_error=1e-2, resolution=(16, 16))
    _tight_paths, tight = _sample(_circle, max_error=1e-6, resolution=(16, 16))

    assert loose["resolution"] == [32, 32]
    assert tight["resolution"] == [256, 256]
    assert tight["pass_count"] > loose["pass_count"]
    assert tight["final_residual"] < loose["final_residual"] / 10.0
    # A tighter target costs more field evaluations; the summary says how many.
    assert tight["field_evaluations"] > loose["field_evaluations"]


def test_a_coarse_grid_that_already_meets_the_target_is_not_refined() -> None:
    _paths, summary = _sample(_circle, max_error=0.1, resolution=(16, 16))
    assert summary["pass_count"] == 1
    assert summary["refinement_exhausted"] is False
    assert summary["final_residual"] <= 0.1


def test_the_summary_reports_its_own_work_consistently() -> None:
    paths, summary = _sample(_circle)
    assert summary["sampler"] == "implicit_isocontour"
    assert summary["branch_count"] == len(paths)
    assert summary["sample_count"] == sum(len(path.points) for path in paths)
    assert summary["max_depth_reached"] == summary["pass_count"] - 1
    assert summary["field_evaluations"] > 0
    assert [entry["pass"] for entry in summary["passes"]] == list(range(summary["pass_count"]))
    assert summary["branch_residuals"] == [path.sampling_error for path in paths]
    assert summary["branches_over_error_target"] == []


def test_the_same_field_gives_the_same_points_twice() -> None:
    field = lambda x, y: np.sin(x) * np.cos(y) - 0.3  # noqa: E731
    first, _ = _sample(field, (-4.0, 4.0), (-4.0, 4.0))
    second, _ = _sample(field, (-4.0, 4.0), (-4.0, 4.0))
    assert len(first) == len(second) > 0
    for left, right in zip(first, second):
        assert np.array_equal(left.points, right.points)


# ---------------------------------------------------------------------------
# Ambiguity, and the two things this extractor cannot represent
# ---------------------------------------------------------------------------


def test_an_ambiguous_saddle_is_decided_by_a_rule_and_reported() -> None:
    """``F = x*y`` at level 0: four corners alternate in the cell at the origin."""
    paths, summary = _sample(lambda x, y: x * y)

    assert summary["ambiguous_saddles"] == 1
    assert [entry["code"] for entry in summary["diagnostics"]] == [
        "GEOM-IMPLICIT-AMBIGUOUS-SADDLE"
    ]
    assert len(paths) == 2
    assert all(not path.closed for path in paths)


def test_a_self_touching_cross_keeps_its_two_branches_apart() -> None:
    """Documented limitation: the touch point is not represented as a crossing.

    ``x*y = 0`` is the union of the two axes, which cross at the origin. The two branches
    come near each other and never meet, so no crossing survives into the weave. With
    refinement off the closest approach is ``0.707 * cell size`` at every resolution tried:
    it shrinks with the grid and never reaches zero, which is why no cell-level special case
    can close it.
    """
    def closest_approach(paths) -> float:
        left, right = paths[0].points, paths[1].points
        return float(np.linalg.norm(left[:, None, :] - right[None, :, :], axis=-1).min())

    ratios = []
    for resolution in (24, 48, 96, 192):
        paths, _summary = _sample(lambda x, y: x * y, resolution=(resolution, resolution),
                                  max_refine_passes=0)
        assert len(paths) == 2
        gap = closest_approach(paths)
        assert gap > 0.0, "the two branches must not meet in this implementation"
        for path in paths:
            closest = float(np.linalg.norm(path.points, axis=1).min())
            assert 0.0 < closest
        ratios.append(gap / (4.0 / (resolution - 1)))
    assert ratios == pytest.approx([0.707] * len(ratios), abs=0.01), ratios


def test_the_saddle_pairing_is_not_resolution_stable() -> None:
    """A known instability, pinned rather than hidden.

    In the single ambiguous cell of ``x*y = 0`` the bilinear centre value equals the level,
    so which rays end up in the same branch is decided by the sign of a zero. Measured with
    refinement off, the pairing alternates with the grid; this test records that it does,
    and the module docstring says what to use instead when a stable touch point is needed.
    """
    owners = []
    for resolution in (24, 48, 96, 192, 384):
        paths, _summary = _sample(lambda x, y: x * y, resolution=(resolution, resolution),
                                  max_refine_passes=0)
        first = paths[0].points
        x_ray = "+" if first[np.argmax(np.abs(first[:, 0])), 0] > 0 else "-"
        y_ray = "+" if first[np.argmax(np.abs(first[:, 1])), 1] > 0 else "-"
        owners.append(f"x{x_ray}y{y_ray}")
    assert len(set(owners)) > 1, owners
    assert owners == ["x+y-", "x-y-", "x+y-", "x+y-", "x-y-"], owners


def test_refinement_can_stop_short_of_the_target_when_the_pass_cap_runs_out() -> None:
    """Starting coarser spends the pass budget and lands on a smaller final grid.

    Each pass doubles the resolution, so a 4-pass budget from 24 nodes reaches 384 while the
    same budget from 96 nodes reaches 768. The summary says which happened, and the miss is
    reported instead of being hidden.
    """
    _paths, coarse = _sample(lambda x, y: x * y, resolution=(24, 24))
    _paths, fine = _sample(lambda x, y: x * y, resolution=(96, 96))
    assert coarse["resolution"] == [384, 384] and coarse["refinement_exhausted"] is True
    assert fine["resolution"] == [768, 768] and fine["refinement_exhausted"] is False
    assert "GEOM-IMPLICIT-ERROR-TARGET-MISSED" in [
        entry["code"] for entry in coarse["diagnostics"]
    ]
    assert "GEOM-IMPLICIT-ERROR-TARGET-MISSED" not in [
        entry["code"] for entry in fine["diagnostics"]
    ]


def test_a_lemniscate_loses_its_node_through_the_engine() -> None:
    """The measured cost of the same limitation, one level up: no crossing at the node.

    The lemniscate ``(x²+y²)² = x²-y²`` is one closed branch whose two arms pass within
    0.0082 of each other at the origin, so the engine reports 0 crossings where the true
    figure-eight has a node. This test exists so that the day endpoint snapping (FR-009/
    FR-010) closes the gap, the change is deliberate and visible.
    """
    paths, _summary = _sample(
        lambda x, y: (x * x + y * y) ** 2 - (x * x - y * y), (-1.5, 1.5), (-1.0, 1.0)
    )
    assert len(paths) == 1
    path = paths[0]
    assert path.closed is True
    radii = np.linalg.norm(path.points, axis=1)
    assert float(radii.min()) < 0.005

    engine = LaceEngine.from_implicit(
        lambda x, y: (x * x + y * y) ** 2 - (x * x - y * y), (-1.5, 1.5), (-1.0, 1.0),
        offset=0.05,
    )
    result = engine.solve()
    assert len(result.paths) == 1
    assert result.crossings == []


def test_a_pole_is_reported_as_a_missed_target_and_the_result_is_not_a_contour() -> None:
    """A pole is not a zero: this is where the extractor's one assumption breaks.

    ``1/(x²+y²-0.25)`` has no zero inside the box, but the corner values straddle the level
    across the pole, so a curve is invented. It cannot be detected from the local linear
    model, so the extractor's promise is the residual: the target is never met, and the
    warning names the branches that must not be trusted.
    """
    paths, summary = _sample(lambda x, y: 1.0 / (x * x + y * y - 0.25),
                             (-1.0, 1.0), (-1.0, 1.0), max_error=1e-3)

    assert paths, "the extractor does return the invented curve (documented, warned)"
    radii = np.linalg.norm(paths[0].points, axis=1)
    assert radii == pytest.approx(0.5, abs=0.02), "it traces the pole circle at r = 0.5"
    # Proof that the returned curve is not a contour of F: |F| there is huge, not ~0.
    point = paths[0].points[0]
    radius_squared = float(point[0] ** 2 + point[1] ** 2)
    assert radius_squared == pytest.approx(0.25, abs=0.02)
    assert abs(1.0 / (radius_squared - 0.25)) > 10.0

    assert summary["refinement_exhausted"] is True
    assert summary["final_residual"] > 1e-3
    assert summary["branches_over_error_target"] == [0]
    codes = [entry["code"] for entry in summary["diagnostics"]]
    assert "GEOM-IMPLICIT-ERROR-TARGET-MISSED" in codes
    missed = next(entry for entry in summary["diagnostics"]
                  if entry["code"] == "GEOM-IMPLICIT-ERROR-TARGET-MISSED")
    assert missed["details"]["branches_over_error_target"] == [0]
    assert "极" in missed["message"] or "不连续" in missed["message"]
    assert paths[0].source.metadata["within_error_target"] is False
    assert paths[0].sampling_error == pytest.approx(summary["branch_residuals"][0])


def test_a_level_that_is_never_crossed_returns_nothing_and_says_so() -> None:
    paths, summary = _sample(lambda x, y: x * x + y * y + 1.0)
    assert paths == []
    assert summary["branch_count"] == 0
    assert [entry["code"] for entry in summary["diagnostics"]] == [
        "GEOM-IMPLICIT-NO-CONTOUR"
    ]


def test_the_engine_explains_an_empty_level_set_instead_of_failing_obscurely() -> None:
    with pytest.raises(ValueError, match="没有等值线"):
        LaceEngine.from_implicit(lambda x, y: x * x + y * y + 1.0, (-2.0, 2.0), (-2.0, 2.0))


# ---------------------------------------------------------------------------
# Holes in the field: counted per cell, never mistaken for a saddle
# ---------------------------------------------------------------------------


def test_nonfinite_corners_are_counted_and_not_mistaken_for_saddles() -> None:
    """A field that is NaN everywhere must report 9025 dead cells and 0 saddles.

    It used to report the exact opposite: the cell helper returned ``1`` for "non-finite"
    and ``1`` for "ambiguous saddle", so every dead cell inflated the saddle count while
    the non-finite counter could never fire.
    """
    paths, summary = _sample(lambda x, y: np.nan, (-1.0, 1.0), (-1.0, 1.0), resolution=(96, 96))
    assert paths == []
    assert summary["nonfinite_cells"] == 95 * 95
    assert summary["ambiguous_saddles"] == 0
    codes = sorted(entry["code"] for entry in summary["diagnostics"])
    assert codes == ["GEOM-IMPLICIT-NO-CONTOUR", "GEOM-IMPLICIT-NONFINITE"]


def test_a_domain_hole_breaks_the_grid_but_still_finds_the_contour() -> None:
    """``sqrt(1-r²) - 0.5`` is NaN outside the unit disk; the contour inside is r=√0.75."""
    def hole(x, y):
        inside = 1.0 - x * x - y * y
        return np.where(inside < 0.0, np.nan, np.sqrt(np.where(inside < 0.0, 0.0, inside)) - 0.5)

    paths, summary = _sample(hole, (-1.5, 1.5), (-1.5, 1.5))
    assert len(paths) == 1
    radii = np.linalg.norm(paths[0].points, axis=1)
    assert float(radii.mean()) == pytest.approx(math.sqrt(0.75), abs=2e-3)
    assert summary["nonfinite_cells"] > 0
    assert summary["ambiguous_saddles"] == 0
    assert "GEOM-IMPLICIT-NONFINITE" in [entry["code"] for entry in summary["diagnostics"]]


# ---------------------------------------------------------------------------
# Orientation: the equation does not decide a direction, so a rule does
# ---------------------------------------------------------------------------


def test_the_gradient_rule_puts_the_negative_side_on_the_left() -> None:
    for rule in ("gradient", "ccw"):
        paths, summary = _sample(_circle, orientation=rule)
        ring = paths[0].points
        # For x²+y²-1 the inside (F < 0) is the disk, so the left side is the interior, which
        # for a counter-clockwise ring it is.
        assert _signed_area(ring) > 0.0, rule
        assert summary["orientation_rule"] == rule
    # The raw grid order is clockwise here, so the rules that promise a direction reverse it.
    _paths, gradient = _sample(_circle, orientation="gradient")
    assert gradient["orientation"] == {"reversed": 1}
    paths, none = _sample(_circle, orientation="none")
    assert _signed_area(paths[0].points) < 0.0
    assert none["orientation"] == {"kept": 1}


def test_the_orientation_outcome_is_recorded_per_branch() -> None:
    paths, _summary = _sample(_circle)
    metadata = paths[0].source.metadata
    assert metadata["orientation_rule"] == "gradient"
    assert metadata["orientation_outcome"] in {"kept", "reversed", "undetermined"}


# ---------------------------------------------------------------------------
# How the field is called: both lanes agree, and neither one crashes
# ---------------------------------------------------------------------------


def test_the_two_evaluation_lanes_agree_on_the_same_field() -> None:
    """Vectorised and elementwise calls of the *same* function must agree exactly."""
    vectorised, _ = _sample(lambda x, y: x * x + y * y - 1.0)

    def elementwise(x, y):
        return float(x) * float(x) + float(y) * float(y) - 1.0

    lane, _ = _sample(elementwise)
    assert len(vectorised) == len(lane) == 1
    assert np.array_equal(vectorised[0].points, lane[0].points)


def test_two_formulas_for_the_same_circle_agree_within_the_error_target() -> None:
    """``x²+y²-1`` and ``hypot(x,y)-1`` share a zero set but not their values.

    Linear interpolation along a grid edge is driven by the values, so the two arcs differ
    by about the size of the residual — which is exactly what the error target is for. They
    must not be asserted to be identical.
    """
    polynomial, first = _sample(lambda x, y: x * x + y * y - 1.0)

    def hypot_form(x, y):
        return math.hypot(x, y) - 1.0

    hypot_paths, second = _sample(hypot_form)
    radii_a = np.linalg.norm(polynomial[0].points, axis=1)
    radii_b = np.linalg.norm(hypot_paths[0].points, axis=1)
    assert len(radii_a) == len(radii_b)
    assert np.allclose(radii_a, radii_b, atol=max(first["final_residual"],
                                                  second["final_residual"]) * 4.0)
    assert not np.array_equal(polynomial[0].points, hypot_paths[0].points)


def test_a_field_that_ignores_one_coordinate_is_not_a_crash() -> None:
    """The straight contour ``tanh(50(x-0.3))`` depends on x only.

    Passing ``(1, nx)`` and ``(ny, 1)`` arrays to the field and letting it broadcast made
    such a field return a ``(1, nx)`` value, and the reshape into the grid blew up. The
    coordinates are expanded to the full grid before the call, so this works.
    """
    paths, _summary = _sample(lambda x, y: np.tanh(50.0 * (x - 0.3)),
                              (-1.0, 1.0), (-1.0, 1.0))
    assert len(paths) == 1
    assert paths[0].points[:, 0] == pytest.approx(0.3, abs=2e-3)
    assert paths[0].points[:, 1].min() == pytest.approx(-1.0, abs=1e-9)
    assert paths[0].points[:, 1].max() == pytest.approx(1.0, abs=1e-9)


def test_a_field_that_returns_a_scalar_for_arrays_falls_back_to_elementwise() -> None:
    def scalar_only(x, y):
        return float(np.asarray(x).ravel()[0] ** 2 + np.asarray(y).ravel()[0] ** 2 - 1.0)

    paths, _summary = _sample(scalar_only)
    assert len(paths) == 1
    radii = np.linalg.norm(paths[0].points, axis=1)
    assert float(radii.mean()) == pytest.approx(1.0, abs=1e-2)


def test_the_exported_orientation_rules_are_the_accepted_ones() -> None:
    assert set(ORIENTATION_RULES) == {"gradient", "ccw", "none"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"orientation": "clockwise"}, "orientation must be one of"),
        ({"resolution": (1, 8)}, "at least 2 nodes"),
        ({"resolution": (8,)}, "resolution must be an"),
        ({"max_error": 0.0}, "max_error must be positive"),
        ({"max_error": float("nan")}, "max_error must be positive"),
        ({"level": float("inf")}, "level must be finite"),
        ({"x_range": (2.0, 2.0)}, "x_range must be increasing"),
        ({"y_range": (1.0, -1.0)}, "y_range must be increasing"),
        ({"max_refine_passes": -1}, "max_refine_passes must not be negative"),
        ({"max_refine_passes": 1.5}, "max_refine_passes must be an integer"),
    ],
)
def test_validation_rejects_nonsense(kwargs, message) -> None:
    """The ranges are supplied through the same mapping, so a range case can override it."""
    arguments = {"x_range": (-1.0, 1.0), "y_range": (-1.0, 1.0), **kwargs}
    with pytest.raises(ValueError, match=message):
        sample_implicit(lambda x, y: x * x + y * y - 1.0, **arguments)


def test_zero_refinement_passes_means_one_pass_and_is_allowed() -> None:
    """``max_refine_passes=0`` is a legitimate request, not an error.

    Rejecting it forced a caller who wants a single pass to inflate ``max_error`` instead,
    which would also change what the reported residual means.
    """
    paths, summary = _sample(_circle, max_refine_passes=0, max_error=1e-9)
    assert summary["pass_count"] == 1
    assert summary["resolution"] == [96, 96]
    assert summary["refinement_exhausted"] is True
    assert len(paths) == 1


def test_a_non_callable_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be callable"):
        sample_implicit("not a function", (-1.0, 1.0), (-1.0, 1.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Through the engine: implicit input behaves like any other source
# ---------------------------------------------------------------------------


def test_the_engine_solves_an_implicit_circle() -> None:
    engine = LaceEngine.from_implicit(_circle, (-2.0, 2.0), (-2.0, 2.0), offset=0.08)
    result = engine.solve()

    assert len(result.paths) == 1
    assert result.paths[0].closed is True
    assert result.crossings == []
    assert result.pieces, "the ribbon backend must produce geometry for the ring"
    assert result.diagnostics == []


def test_the_engine_reports_the_implicit_summary_as_a_trace_event() -> None:
    engine = LaceEngine.from_implicit(_circle, (-2.0, 2.0), (-2.0, 2.0), offset=0.08)
    result = engine.solve()
    events = [event for event in result.trace if event.event_type == "sampling.subdivision"]
    assert len(events) == 1
    assert events[0].data["sampler"] == "implicit_isocontour"
    assert events[0].data["branch_count"] == 1
    assert events[0].data["x_range"] == [-2.0, 2.0]


def test_sampler_diagnostics_become_real_diagnostics_on_the_result() -> None:
    """A warning that only exists in the trace payload is a warning nobody sees."""
    engine = LaceEngine.from_implicit(lambda x, y: x * y, (-2.0, 2.0), (-2.0, 2.0), offset=0.1)
    result = engine.solve()

    codes = [diagnostic.code for diagnostic in result.diagnostics]
    assert "GEOM-IMPLICIT-AMBIGUOUS-SADDLE" in codes
    diagnostic = next(d for d in result.diagnostics if d.code == "GEOM-IMPLICIT-AMBIGUOUS-SADDLE")
    assert diagnostic.severity.value == "info"
    assert diagnostic.details["cells"] == 1
    assert diagnostic.path_ids == ("P0000", "P0000.01")


def test_several_branches_of_one_field_are_woven_together() -> None:
    """Two concentric branches of one level set enter the weave as two strands."""
    engine = LaceEngine.from_implicit(
        lambda x, y: (x * x + y * y - 1.0) * (x * x + y * y - 4.0),
        (-3.0, 3.0), (-3.0, 3.0), offset=0.1,
    )
    result = engine.solve()
    assert len(result.paths) == 2
    assert len(result.pieces) >= 2
    # Concentric closed rings cannot cross each other.
    assert result.crossings == []