"""Adaptive, parameter-preserving sampling for 2D mathematical curves."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..model import PathSource, PolylinePath
from ..tracing import BoundedRecords

PointFunction = Callable[[float], Iterable[float]]
#: Reporter called once per sampled curve with the subdivision summary.
SubdivisionTracer = Callable[[dict[str, Any]], None]


def _as_xy(func: PointFunction, t: float) -> np.ndarray:
    try:
        value = np.asarray(tuple(func(float(t))), dtype=float).reshape(-1)
    except (ArithmeticError, ValueError, OverflowError):
        # Domain errors such as math.log(x <= 0) should create a path break,
        # not a segment connecting across an undefined interval.
        return np.array([np.nan, np.nan])
    if value.size < 2:
        raise ValueError("curve function must return at least (x, y)")
    return value[:2]


def _point_segment_distance(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    direction = b - a
    denom = float(direction @ direction)
    if denom <= 1e-30:
        return float(np.linalg.norm(point - a))
    fraction = float(np.clip(((point - a) @ direction) / denom, 0.0, 1.0))
    return float(np.linalg.norm(point - (a + fraction * direction)))


@dataclass(slots=True)
class _SubdivisionLog:
    """Exact subdivision counters plus a bounded list of the decisions taken.

    Every recursion node ends in exactly one of ``split``, ``accept``, ``budget``
    (the depth cap forced a single split) or ``drop`` (a non-finite midpoint), so
    ``node_count == split_count + accepted_count + budget_capped_count +
    singular_count``. The counters are exact even when the decision list is
    truncated, and ``max_depth_reached`` is a counter for the same reason.
    """

    max_error: float
    max_step: float
    max_depth: int
    decisions: BoundedRecords = field(default_factory=BoundedRecords)
    interval_count: int = 0
    node_count: int = 0
    split_count: int = 0
    accepted_count: int = 0
    budget_capped_count: int = 0
    singular_count: int = 0
    max_depth_reached: int = 0

    def record(
        self,
        kind: str,
        reason: str,
        t0: float,
        t1: float,
        depth: int,
        error: float | None,
    ) -> None:
        self.node_count += 1
        self.max_depth_reached = max(self.max_depth_reached, depth)
        self.decisions.add({
            "kind": kind,
            "reason": reason,
            "t0": float(t0),
            "t1": float(t1),
            "depth": int(depth),
            "error": None if error is None else float(error),
        })


def _adaptive_interval(
    func: PointFunction,
    t0: float,
    p0: np.ndarray,
    t1: float,
    p1: np.ndarray,
    *,
    max_error: float,
    max_step: float,
    max_depth: int,
    depth: int,
    log: _SubdivisionLog | None = None,
) -> list[tuple[float, np.ndarray]]:
    tm = (t0 + t1) / 2
    pm = _as_xy(func, tm)
    finite = np.isfinite(p0).all() and np.isfinite(pm).all() and np.isfinite(p1).all()
    if not finite:
        # The interval may straddle a singularity. Omit this small parameter
        # interval rather than accidentally joining two branches across it.
        if log is not None:
            log.singular_count += 1
            log.record("drop", "not_finite", t0, t1, depth, None)
        return []
    error = _point_segment_distance(pm, p0, p1)
    too_wide = (t1 - t0) > max_step
    too_curved = error > max_error
    if not (too_wide or too_curved):
        if log is not None:
            log.accepted_count += 1
            log.record("accept", "converged", t0, t1, depth, error)
        return [(t0, p0), (t1, p1)]
    reasons = "+".join(name for name, hit in (("max_step", too_wide), ("flatness", too_curved)) if hit)
    if depth >= max_depth:
        if log is not None:
            log.budget_capped_count += 1
            log.record("budget", f"depth_cap+{reasons}", t0, t1, depth, error)
        return [(t0, p0), (tm, pm), (t1, p1)]
    if log is not None:
        log.split_count += 1
        log.record("split", reasons, t0, t1, depth, error)
    left = _adaptive_interval(
        func, t0, p0, tm, pm,
        max_error=max_error, max_step=max_step, max_depth=max_depth, depth=depth + 1, log=log,
    )
    right = _adaptive_interval(
        func, tm, pm, t1, p1,
        max_error=max_error, max_step=max_step, max_depth=max_depth, depth=depth + 1, log=log,
    )
    if left and right and np.allclose(left[-1][1], right[0][1]):
        return left + right[1:]
    return left + right


def sample_parametric(
    func: PointFunction,
    t_range: tuple[float, float],
    *,
    path_id: str = "P0000",
    max_error: float = 1e-3,
    max_step: float | None = None,
    max_depth: int = 18,
    breakpoints: Iterable[float] = (),
    closed: bool = False,
    object_label: str = "parametric",
    subdivision_tracer: SubdivisionTracer | None = None,
) -> list[PolylinePath]:
    """Sample ``gamma(t) -> (x, y[, z])`` into one or more ordered paths.

    ``max_step`` is a parameter-space bound, not a world-space length. It is
    important for oscillatory black-box functions where midpoint error alone can
    miss high-frequency behavior. Callers should supply known singularities and
    discontinuities via ``breakpoints``.

    ``subdivision_tracer`` is called exactly once, at the end, with the summary of
    the adaptive subdivision this call performed: the effective parameters, exact
    counters (``node_count``, ``split_count``, ``accepted_count``,
    ``budget_capped_count``, ``singular_count``, ``max_depth_reached``,
    ``interval_count``, ``part_count``, ``sample_count``) and a bounded, ordered
    list of the decisions taken (``decisions`` plus ``decisions_count`` /
    ``decisions_truncated``). Every node ends in exactly one of split, accept,
    depth cap or drop, so those counters add up; the decision list is truncated at
    :data:`manim_lace.tracing.DEFAULT_TRACE_RECORD_LIMIT` while the counters stay
    exact.
    """
    t0, t1 = map(float, t_range)
    if not np.isfinite([t0, t1]).all() or t1 <= t0:
        raise ValueError("t_range must be finite and strictly increasing")
    if max_error <= 0 or not np.isfinite(max_error):
        raise ValueError("max_error must be positive and finite")
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    if max_step is None:
        max_step = (t1 - t0) / 128
    if max_step <= 0 or not np.isfinite(max_step):
        raise ValueError("max_step must be positive and finite")

    cuts = sorted({t0, t1, *(float(b) for b in breakpoints if t0 < float(b) < t1)})
    log = (
        _SubdivisionLog(max_error=max_error, max_step=max_step, max_depth=max_depth)
        if subdivision_tracer is not None else None
    )
    output: list[PolylinePath] = []
    part_index = 0
    dropped_intervals = 0
    for range_index in range(len(cuts) - 1):
        a, b = cuts[range_index], cuts[range_index + 1]
        n = max(1, int(np.ceil((b - a) / max_step)))
        seed_ts = np.linspace(a, b, n + 1)
        raw: list[tuple[float, np.ndarray]] = []
        for left_t, right_t in zip(seed_ts[:-1], seed_ts[1:]):
            p_left, p_right = _as_xy(func, left_t), _as_xy(func, right_t)
            if not (np.isfinite(p_left).all() and np.isfinite(p_right).all()):
                # Undefined values separate subpaths. Never connect across them.
                dropped_intervals += 1
                if len(raw) >= 2:
                    output.append(_make_path(raw, path_id, part_index, object_label, max_error, False, func))
                    part_index += 1
                raw = []
                continue
            if log is not None:
                log.interval_count += 1
            refined = _adaptive_interval(
                func, left_t, p_left, right_t, p_right,
                max_error=max_error, max_step=max_step, max_depth=max_depth, depth=0, log=log,
            )
            if not refined:
                dropped_intervals += 1
                if len(raw) >= 2:
                    output.append(_make_path(raw, path_id, part_index, object_label, max_error, False, func))
                    part_index += 1
                raw = []
                continue
            if raw and np.isclose(raw[-1][0], refined[0][0]):
                raw.extend(refined[1:])
            else:
                if len(raw) >= 2:
                    output.append(_make_path(raw, path_id, part_index, object_label, max_error, False, func))
                    part_index += 1
                raw = list(refined)
        if len(raw) >= 2:
            final_closed = bool(closed and range_index == len(cuts) - 2)
            output.append(_make_path(raw, path_id, part_index, object_label, max_error, final_closed, func))
            part_index += 1
    if log is not None and subdivision_tracer is not None:
        subdivision_tracer({
            "path_id": path_id,
            "object_label": object_label,
            "closed": bool(closed),
            "t_range": [t0, t1],
            "breakpoints": sorted(float(b) for b in cuts[1:-1]),
            "max_error": float(max_error),
            "max_step": float(max_step),
            "max_depth": int(max_depth),
            "interval_count": log.interval_count,
            "node_count": log.node_count,
            "split_count": log.split_count,
            "accepted_count": log.accepted_count,
            "budget_capped_count": log.budget_capped_count,
            "singular_count": log.singular_count,
            "max_depth_reached": log.max_depth_reached,
            "dropped_interval_count": dropped_intervals,
            "part_count": len(output),
            "sample_count": int(sum(len(path.points) for path in output)),
            **log.decisions.as_payload("decisions"),
        })
    return output


def _make_path(
    samples: list[tuple[float, np.ndarray]],
    base_id: str,
    part_index: int,
    object_label: str,
    max_error: float,
    closed: bool,
    curve: PointFunction,
) -> PolylinePath:
    # Consecutive samples at the same parameter can arise at interval boundaries.
    compact: list[tuple[float, np.ndarray]] = []
    for item in samples:
        if not compact or not np.isclose(item[0], compact[-1][0]):
            compact.append(item)
    points = np.asarray([p for _, p in compact], dtype=float)
    params = np.asarray([t for t, _ in compact], dtype=float)
    if closed and not np.allclose(points[0], points[-1]):
        points = np.vstack((points, points[0]))
        params = np.append(params, params[-1])
    return PolylinePath(
        points=points,
        path_id=f"{base_id}.{part_index:02d}" if part_index else base_id,
        closed=closed,
        source=PathSource(
            object_type="parametric_function",
            object_label=object_label,
            subpath_index=part_index,
            parameter_name="x" if object_label == "explicit_function_graph" else "t",
        ),
        parameters=params,
        sampling_error=max_error,
        # Retain the curve so crossings can be refined on it (SPEC FR-036).
        curve=curve,
    )


def sample_graph(
    func: Callable[[float], float],
    x_range: tuple[float, float],
    *,
    path_id: str = "P0000",
    max_error: float = 1e-3,
    max_step: float | None = None,
    max_depth: int = 18,
    breakpoints: Iterable[float] = (),
    jump_threshold: float | None = None,
    subdivision_tracer: SubdivisionTracer | None = None,
) -> list[PolylinePath]:
    """Sample ``y=f(x)``. Known discontinuities should be supplied as breakpoints.

    ``jump_threshold`` optionally splits output when neighboring sampled y values
    differ by more than the given world-space distance. It is deliberately
    opt-in because a universal automatic threshold can mistake steep continuous
    functions for discontinuities.

    ``subdivision_tracer`` is forwarded to :func:`sample_parametric`; when
    ``jump_threshold`` splits paths afterwards, the summary gains an honest
    ``jump_split_path_count`` (the sampled ``part_count`` describes the sampler's
    own output, before those splits).
    """
    tracer = subdivision_tracer
    summaries: list[dict[str, Any]] = []
    paths = sample_parametric(
        lambda x: (x, func(x)),
        x_range,
        path_id=path_id,
        max_error=max_error,
        max_step=max_step,
        max_depth=max_depth,
        breakpoints=breakpoints,
        object_label="explicit_function_graph",
        subdivision_tracer=summaries.append if tracer is not None else None,
    )
    if jump_threshold is None:
        if tracer is not None:
            for summary in summaries:
                tracer(summary)
        return paths
    if jump_threshold <= 0:
        raise ValueError("jump_threshold must be positive")
    split_paths: list[PolylinePath] = []
    for path in paths:
        start = 0
        for i in range(1, len(path.points)):
            if abs(path.points[i, 1] - path.points[i - 1, 1]) > jump_threshold:
                if i - start >= 2:
                    split_paths.append(PolylinePath(
                        points=path.points[start:i], path_id=f"{path.path_id}.split{len(split_paths)}",
                        source=path.source, parameters=path.parameters[start:i] if path.parameters is not None else None,
                        sampling_error=path.sampling_error, curve=path.curve,
                    ))
                start = i
        if len(path.points) - start >= 2:
            split_paths.append(PolylinePath(
                points=path.points[start:], path_id=f"{path.path_id}.split{len(split_paths)}",
                source=path.source, parameters=path.parameters[start:] if path.parameters is not None else None,
                sampling_error=path.sampling_error, curve=path.curve,
            ))
    if tracer is not None:
        for summary in summaries:
            # Honest about the second splitting pass: the sampler's own part count
            # predates it, so the post-split path count is reported separately.
            tracer({**summary, "jump_split_path_count": len(split_paths)})
    return split_paths
