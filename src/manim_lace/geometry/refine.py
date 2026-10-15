"""Adaptive local refinement of a crossing on the source curve (SPEC FR-036).

Crossings are still *detected* on the sampled polyline: the candidate test is a
straight-segment intersection, which is exact for the sampled geometry. What the
polyline cannot answer is where the underlying smooth curve crosses and at which
angle. At a sample vertex the reported angle is the angle of the two chord
segments, not of the local tangents, and the reported position carries the
sampling error close to the crossing.

When both paths expose an evaluable source curve (``PolylinePath.curve``) together
with the source parameter mapping the samplers keep (``PolylinePath.parameters``,
SPEC FR-022), the raw hit is refined with a damped Newton iteration on

    F(t, u) = gamma_a(t) - gamma_b(u) = 0

started from the chord solution and restricted to the parameter window that
produced the hit. The refined result carries the source parameters, the curve
position, the curve arc length and an angle sine computed from the true local
tangents.

Everything here is optional and fail-open: an unavailable probe, a probe that
raises or returns non-finite values, a non-convergent iteration, a solution that
leaves the local window, and a path that genuinely kinks at the crossing (where no
single local tangent exists) all return ``None`` and leave the polyline estimate in
place. Refinement therefore can never fabricate a crossing that the sampled
geometry did not report, and never claims a tangent that the source curve does not
have.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ..model import CurveProbe, PolylinePath

__all__ = ["RefinementResult", "refine_crossing"]

#: Parameter window, in local sample spacings, that refinement may explore.
WINDOW_SPANS = 2.0
#: Newton iterations before the refinement is declared non-convergent.
MAX_ITERATIONS = 32
#: The iteration stops refining once the residual is this far below ``position_tol``.
#: ``position_tol`` itself stays the acceptance bound, so a stalled-but-good solution
#: at a shallow angle is still accepted while a clean crossing reaches round-off.
CONVERGED_RESIDUAL_RATIO = 1e-3
#: Relative step used for central-difference derivatives. It is tied to the local
#: sample spacing, so it stays scale-independent: truncation error is far below the
#: sampling error, while the round-off floor stays orders of magnitude lower still.
DERIVATIVE_STEP_RATIO = 1e-3
#: Backtracking attempts for one accepted Newton step.
MAX_BACKTRACKS = 8
#: Largest turn (radians) the source curve may show between its two one-sided tangents
#: at the crossing. A smooth curve turns by roughly ``step * curvature`` there, and the
#: step is a thousandth of the local sample spacing, so it stays orders of magnitude
#: below this. A kink shows its full corner angle instead, which means there is no
#: single local tangent and the chord estimate is the honest local answer.
MAX_LOCAL_TURN = 0.05

_GAUSS_NODES, _GAUSS_WEIGHTS = np.polynomial.legendre.leggauss(5)


@dataclass(frozen=True, slots=True)
class RefinementResult:
    """A crossing solved on the source curves instead of on the chords."""

    point: tuple[float, float]
    s_a: float
    s_b: float
    sin_angle: float
    parameter_a: float
    parameter_b: float
    segment_a: int
    u_a: float
    segment_b: int
    u_b: float
    iterations: int
    residual: float

    def swapped(self) -> RefinementResult:
        """Exchange the two sides; used to keep self-crossing passes ordered by arc length."""
        return replace(
            self,
            s_a=self.s_b,
            s_b=self.s_a,
            parameter_a=self.parameter_b,
            parameter_b=self.parameter_a,
            segment_a=self.segment_b,
            segment_b=self.segment_a,
            u_a=self.u_b,
            u_b=self.u_a,
        )


def _evaluate(probe: CurveProbe, t: float) -> np.ndarray | None:
    """Evaluate a probe, tolerating undefined or non-finite values."""
    try:
        value = np.asarray(tuple(probe(float(t))), dtype=float).reshape(-1)[:2]
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return None
    if value.size < 2 or not np.isfinite(value).all():
        return None
    return value


def _derivative(probe: CurveProbe, t: float, span: float) -> np.ndarray | None:
    if span <= 0:
        return None
    step = span * DERIVATIVE_STEP_RATIO
    forward, backward = _evaluate(probe, t + step), _evaluate(probe, t - step)
    if forward is None or backward is None:
        return None
    return (forward - backward) / (2.0 * step)


def _local_turn(probe: CurveProbe, t: float, span: float) -> float | None:
    """Turn angle between the two one-sided tangents at ``t``.

    It vanishes for a smooth curve (the one-sided differences stay inside the local
    branch) and jumps to the corner angle where the path actually kinks.
    """
    here = _evaluate(probe, t)
    if here is None:
        return None
    step = span * DERIVATIVE_STEP_RATIO
    behind, ahead = _evaluate(probe, t - step), _evaluate(probe, t + step)
    if behind is None or ahead is None:
        return None
    incoming, outgoing = here - behind, ahead - here
    lengths = float(np.linalg.norm(incoming)) * float(np.linalg.norm(outgoing))
    if lengths <= 0:
        return None
    cosine = float(incoming @ outgoing) / lengths
    return float(np.arccos(float(np.clip(cosine, -1.0, 1.0))))


def _parameter_at(parameters: np.ndarray, segment: int, fraction: float) -> float | None:
    if not 0 <= segment < len(parameters) - 1:
        return None
    start, end = float(parameters[segment]), float(parameters[segment + 1])
    return start + float(np.clip(fraction, 0.0, 1.0)) * (end - start)


def _local_span(parameters: np.ndarray, segment: int) -> float:
    """Parameter width of the sampled segment that produced the hit."""
    if not 0 <= segment < len(parameters) - 1:
        return 0.0
    return abs(float(parameters[segment + 1]) - float(parameters[segment]))


def _locate(parameters: np.ndarray, t: float) -> tuple[int, float]:
    """Map a source parameter back to (segment index, fraction inside that segment)."""
    index = int(np.searchsorted(parameters, t, side="right") - 1)
    index = int(np.clip(index, 0, len(parameters) - 2))
    width = float(parameters[index + 1] - parameters[index])
    if width <= 0:
        return index, 0.0
    fraction = float(np.clip((t - float(parameters[index])) / width, 0.0, 1.0))
    return index, fraction


def _curve_length(probe: CurveProbe, t_start: float, t_end: float, span: float) -> float | None:
    """Signed arc length of the source curve between two parameters (Gauss-Legendre)."""
    if t_start == t_end:
        return 0.0
    half, middle = 0.5 * (t_end - t_start), 0.5 * (t_end + t_start)
    total = 0.0
    for node, weight in zip(_GAUSS_NODES, _GAUSS_WEIGHTS, strict=True):
        derivative = _derivative(probe, middle + half * float(node), span)
        if derivative is None:
            return None
        total += float(weight) * float(np.linalg.norm(derivative))
    return total * half


def _arc_position(
    path: PolylinePath, segment: int, parameters: np.ndarray, probe: CurveProbe,
    t: float, span: float,
) -> float | None:
    """Arc length of a refined parameter, measured on the same cumulative the polyline uses."""
    cumulative = path.cumulative_lengths
    if not 0 <= segment < len(cumulative) - 1:
        return None
    offset = _curve_length(probe, float(parameters[segment]), t, span)
    if offset is None:
        return None
    arc = float(cumulative[segment]) + offset
    if path.closed and path.length > 0:
        return arc % path.length
    return float(np.clip(arc, 0.0, path.length))


def refine_crossing(
    path_a: PolylinePath,
    path_b: PolylinePath,
    *,
    segment_a: int,
    u_a: float,
    segment_b: int,
    u_b: float,
    point: tuple[float, float],
    position_tol: float,
) -> RefinementResult | None:
    """Solve ``gamma_a(t) - gamma_b(u) = 0`` near a sampled crossing.

    Returns ``None`` whenever the refinement is unavailable or not trustworthy;
    callers keep the chord-based hit in that case.
    """
    probe_a, probe_b = path_a.curve, path_b.curve
    parameters_a, parameters_b = path_a.parameters, path_b.parameters
    if probe_a is None or probe_b is None or parameters_a is None or parameters_b is None:
        return None
    t_a = _parameter_at(parameters_a, segment_a, u_a)
    t_b = _parameter_at(parameters_b, segment_b, u_b)
    if t_a is None or t_b is None:
        return None
    start_a, start_b = t_a, t_b
    span_a = _local_span(parameters_a, segment_a)
    span_b = _local_span(parameters_b, segment_b)
    hit = np.asarray(point, dtype=float)

    target = position_tol * CONVERGED_RESIDUAL_RATIO
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):
        current_a, current_b = _evaluate(probe_a, t_a), _evaluate(probe_b, t_b)
        if current_a is None or current_b is None:
            return None
        residual = current_a - current_b
        magnitude = float(np.linalg.norm(residual))
        if magnitude <= target:
            break
        tangent_a = _derivative(probe_a, t_a, span_a)
        tangent_b = _derivative(probe_b, t_b, span_b)
        if tangent_a is None or tangent_b is None:
            return None
        jacobian = np.array([[tangent_a[0], -tangent_b[0]], [tangent_a[1], -tangent_b[1]]])
        if abs(float(jacobian[0, 0] * jacobian[1, 1] - jacobian[0, 1] * jacobian[1, 0])) <= 1e-300:
            return None
        delta = np.linalg.solve(jacobian, -residual)
        step = 1.0
        for _ in range(MAX_BACKTRACKS):
            candidate_a, candidate_b = t_a + step * float(delta[0]), t_b + step * float(delta[1])
            if (
                abs(candidate_a - start_a) > WINDOW_SPANS * span_a
                or abs(candidate_b - start_b) > WINDOW_SPANS * span_b
            ):
                step *= 0.5
                continue
            moved_a, moved_b = _evaluate(probe_a, candidate_a), _evaluate(probe_b, candidate_b)
            if moved_a is None or moved_b is None:
                return None
            if float(np.linalg.norm(moved_a - moved_b)) < magnitude:
                t_a, t_b = candidate_a, candidate_b
                break
            step *= 0.5
        else:
            # No acceptable step: at this precision the iteration has stalled. The
            # acceptance test below decides whether the result is still trustworthy.
            break
    else:
        return None

    final_a, final_b = _evaluate(probe_a, t_a), _evaluate(probe_b, t_b)
    if final_a is None or final_b is None:
        return None
    residual = float(np.linalg.norm(final_a - final_b))
    if residual > position_tol:
        return None
    tangent_a = _derivative(probe_a, t_a, span_a)
    tangent_b = _derivative(probe_b, t_b, span_b)
    if tangent_a is None or tangent_b is None:
        return None
    speed_a = float(np.linalg.norm(tangent_a))
    speed_b = float(np.linalg.norm(tangent_b))
    if speed_a <= 0 or speed_b <= 0:
        return None
    # The solution must stay inside the neighbourhood the candidate was detected
    # in; a probe that jumps elsewhere is not a refinement of this event.
    reach = WINDOW_SPANS * max(span_a * speed_a, span_b * speed_b, position_tol)
    if float(np.linalg.norm(final_a - hit)) > reach:
        return None
    # A path that really turns sharply here has no single local tangent; keep the
    # chord estimate rather than reporting an angle smoothed across the kink.
    for probe, t, span in ((probe_a, t_a, span_a), (probe_b, t_b, span_b)):
        turn = _local_turn(probe, t, span)
        if turn is None or turn > MAX_LOCAL_TURN:
            return None
    s_a = _arc_position(path_a, segment_a, parameters_a, probe_a, t_a, span_a)
    s_b = _arc_position(path_b, segment_b, parameters_b, probe_b, t_b, span_b)
    if s_a is None or s_b is None:
        return None
    refined_segment_a, refined_u_a = _locate(parameters_a, t_a)
    refined_segment_b, refined_u_b = _locate(parameters_b, t_b)
    sin_angle = abs(
        float(tangent_a[0] * tangent_b[1] - tangent_a[1] * tangent_b[0]) / (speed_a * speed_b)
    )
    return RefinementResult(
        point=(float(final_a[0]), float(final_a[1])),
        s_a=s_a,
        s_b=s_b,
        sin_angle=float(np.clip(sin_angle, 0.0, 1.0)),
        parameter_a=float(t_a),
        parameter_b=float(t_b),
        segment_a=refined_segment_a,
        u_a=refined_u_a,
        segment_b=refined_segment_b,
        u_b=refined_u_b,
        iterations=iterations,
        residual=residual,
    )
