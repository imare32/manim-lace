"""Orchestration layer for path normalization, crossings, topology, and strokes."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import numpy as np

from .animation.trace import TraceRecorder
from .geometry.intersections import CandidateStrategy, detect_crossings
from .geometry.sampling import sample_graph, sample_parametric
from .model import (
    CapStyle,
    ConflictStrategy,
    EventPolicy,
    LaceResult,
    PathSource,
    PolylinePath,
    normalize_event_policy,
)
from .render.stroke import render_stroke_geometry
from .topology.solver import WeaveMode, solve_weave


class LaceEngine:
    """Pure-geometry coordinator; does not require Manim to be installed.

    Parameters
    ----------
    paths:
        A sequence of :class:`PolylinePath` instances or ``(N, 2)/(N, 3)`` arrays.
    offset:
        Ribbon half-width in world coordinates.
    weave_mode:
        ``alternating`` (constraint solver), ``free`` (per-crossing defaults), or
        ``manual`` (all transverse crossings need an explicit side assignment).
    render_mode:
        The starter kit currently implements ``stroke`` geometry only. ``ribbon``
        is an explicit extension point and raises until a genuine region backend is
        added.
    min_piece_length:
        Visible centerline pieces shorter than this arc length are dropped and
        reported through a ``RENDER-PIECE-DROPPED`` diagnostic.
    candidate_strategy:
        ``grid`` (deterministic uniform-grid pruning, the default) or
        ``brute_force`` (every segment pair). Both must yield identical events;
        the strategy only changes how many exact tests are executed.
    refine:
        Locally re-solve each crossing on the source curves when both paths
        expose one (SPEC FR-036). Paths built from plain coordinates have no
        probe and keep the sampled-polyline estimate.
    event_policy:
        How to treat candidates that are not plain transverse crossings
        (SPEC FR-032): an :class:`EventPolicy`, a mapping of field names, or one
        value applied to every field. The default diagnoses them and keeps them out
        of the weave solver, and ``weave`` promotes endpoint contacts and
        near-tangents into it.
    conflict_strategy:
        What ``alternating`` mode does when strict alternation has no solution
        (SPEC FR-045): ``error`` (default) reports the minimal conflict witnesses
        and returns no assignment, ``manual`` keeps the user's over sides as hard
        constraints and relaxes the automatic ones that contradict them, ``relax``
        keeps the automatic solution and relaxes what has to give. Both relaxing
        strategies mark every relaxed crossing with ``source='relaxed'``.
    cap_style:
        How the visible ends of cut pieces are painted: ``butt`` (default, the
        geometry stops exactly at the cut), ``round`` or ``square`` (the paint
        protrudes half the ribbon width, so the cut is widened by ``offset``). The
        pieces also get a deterministic ``draw_index`` that puts every under path
        before the paths over it.
    """

    def __init__(
        self,
        paths: Sequence[PolylinePath | np.ndarray],
        *,
        offset: float = 0.1,
        weave_mode: WeaveMode = "alternating",
        manual_over: dict[str, str] | None = None,
        render_mode: str = "stroke",
        position_tol: float = 1e-7,
        angle_tol: float = 1e-8,
        min_sin: float = 0.2,
        overshoot: float = 0.03,
        min_piece_length: float = 1e-7,
        candidate_strategy: CandidateStrategy = "grid",
        refine: bool = True,
        event_policy: EventPolicy | dict[str, str] | str | None = None,
        conflict_strategy: ConflictStrategy = "error",
        cap_style: CapStyle = "butt",
    ) -> None:
        # Every knob is validated here so that an invalid configuration fails at
        # construction instead of halfway through solve().
        if not np.isfinite(offset) or offset <= 0:
            raise ValueError("offset must be positive and finite")
        if render_mode not in {"stroke", "ribbon"}:
            raise ValueError("render_mode must be 'stroke' or 'ribbon'")
        if not np.isfinite(position_tol) or position_tol <= 0:
            raise ValueError("position_tol must be positive and finite")
        if not np.isfinite(angle_tol) or not 0 < angle_tol < 1:
            raise ValueError("angle_tol must be finite and within (0, 1)")
        if not np.isfinite(min_sin) or not 0 < min_sin <= 1:
            raise ValueError("min_sin must be within (0, 1]")
        if not np.isfinite(overshoot) or overshoot < 0:
            raise ValueError("overshoot must be finite and non-negative")
        if not np.isfinite(min_piece_length) or min_piece_length < 0:
            raise ValueError("min_piece_length must be finite and non-negative")
        if candidate_strategy not in ("grid", "brute_force"):
            raise ValueError("candidate_strategy must be 'grid' or 'brute_force'")
        if not isinstance(refine, bool):
            raise ValueError("refine must be a bool")
        if conflict_strategy not in ("error", "manual", "relax"):
            raise ValueError("conflict_strategy must be 'error', 'manual' or 'relax'")
        if cap_style not in ("butt", "round", "square"):
            raise ValueError("cap_style must be 'butt', 'round' or 'square'")
        resolved_policy = normalize_event_policy(event_policy)
        if weave_mode not in ("alternating", "free", "manual"):
            raise ValueError("weave_mode must be 'alternating', 'free' or 'manual'")
        invalid_manual = {
            key: side for key, side in (manual_over or {}).items() if side not in {"a", "b"}
        }
        if invalid_manual:
            raise ValueError(f"manual_over values must be 'a' or 'b': {invalid_manual}")
        if render_mode == "ribbon":
            raise NotImplementedError(
                "render_mode='ribbon' is reserved for the future region backend. "
                "This starter kit currently implements the stroke geometry backend."
            )
        self.paths = self._normalize_paths(paths)
        self.offset = float(offset)
        self.weave_mode = weave_mode
        self.manual_over = {str(k): str(v) for k, v in (manual_over or {}).items()}
        self.render_mode = render_mode
        self.position_tol = float(position_tol)
        self.angle_tol = float(angle_tol)
        self.min_sin = float(min_sin)
        self.overshoot = float(overshoot)
        self.min_piece_length = float(min_piece_length)
        self.candidate_strategy: CandidateStrategy = candidate_strategy
        self.refine = refine
        self.event_policy = resolved_policy
        self.conflict_strategy: ConflictStrategy = conflict_strategy
        self.cap_style: CapStyle = cap_style
        self.result: LaceResult | None = None

    @staticmethod
    def _normalize_paths(paths: Sequence[PolylinePath | np.ndarray]) -> list[PolylinePath]:
        normalized: list[PolylinePath] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(paths):
            if isinstance(item, PolylinePath):
                path = item
                if path.path_id in seen_ids:
                    path = PolylinePath(
                        points=path.points,
                        path_id=f"{path.path_id}.{index:02d}",
                        closed=path.closed,
                        source=path.source,
                        parameters=path.parameters,
                        sampling_error=path.sampling_error,
                        curve=path.curve,
                        )
            else:
                path = PolylinePath(
                    points=np.asarray(item, dtype=float),
                    path_id=f"P{index:04d}",
                    source=PathSource(object_type="array", subpath_index=index),
                )
            seen_ids.add(path.path_id)
            normalized.append(path)
        if not normalized:
            raise ValueError("at least one path is required")
        return normalized

    @classmethod
    def from_parametric(
        cls,
        func: Callable[[float], Iterable[float]],
        t_range: tuple[float, float],
        *,
        offset: float = 0.1,
        max_error: float = 1e-3,
        max_step: float | None = None,
        breakpoints: Iterable[float] = (),
        closed: bool = False,
        **kwargs: object,
    ) -> LaceEngine:
        paths = sample_parametric(
            func, t_range, max_error=max_error, max_step=max_step,
            breakpoints=breakpoints, closed=closed,
        )
        return cls(paths, offset=offset, **kwargs)

    @classmethod
    def from_graph(
        cls,
        func: Callable[[float], float],
        x_range: tuple[float, float],
        *,
        offset: float = 0.1,
        max_error: float = 1e-3,
        max_step: float | None = None,
        breakpoints: Iterable[float] = (),
        jump_threshold: float | None = None,
        **kwargs: object,
    ) -> LaceEngine:
        paths = sample_graph(
            func, x_range, max_error=max_error, max_step=max_step,
            breakpoints=breakpoints, jump_threshold=jump_threshold,
        )
        return cls(paths, offset=offset, **kwargs)

    def solve(self) -> LaceResult:
        trace = TraceRecorder()
        for path in self.paths:
            trace.emit(
                "input", "path.normalized", f"规范化路径 {path.path_id}，包含 {len(path.points)} 个采样点。",
                object_ids=(path.path_id,),
                data={"point_count": len(path.points), "closed": path.closed, "length": path.length,
                      "sampling_error": path.sampling_error},
            )
        detected = detect_crossings(
            self.paths,
            position_tol=self.position_tol,
            angle_tol=self.angle_tol,
            candidate_strategy=self.candidate_strategy,
            refine=self.refine,
            policy=self.event_policy,
        )
        if detected.stats is not None:
            trace.emit(
                "crossings", "crossing.candidates",
                (
                    f"候选筛选（{detected.stats.strategy}）："
                    f"{detected.stats.candidate_pairs}/{detected.stats.all_pairs} 对进入精确判定。"
                ),
                data={
                    "strategy": detected.stats.strategy,
                    "segment_count": detected.stats.segment_count,
                    "candidate_pairs": detected.stats.candidate_pairs,
                    "pair_checks": detected.stats.pair_checks,
                    "grid_cells": detected.stats.grid_cells,
                    "all_pairs": detected.stats.all_pairs,
                    "refined_events": detected.stats.refined_events,
                },
            )
        for crossing in detected.crossings:
            trace.emit(
                "crossings", "crossing.detected", f"识别交叉候选 {crossing.crossing_id}（{crossing.kind}）。",
                object_ids=(crossing.crossing_id, crossing.path_a, crossing.path_b),
                data={"point": crossing.point, "s_a": crossing.s_a, "s_b": crossing.s_b,
                      "sin_angle": crossing.sin_angle, "kind": crossing.kind,
                      "refined": crossing.refined, "parameter_a": crossing.parameter_a,
                      "parameter_b": crossing.parameter_b},
            )
        topology = solve_weave(
            detected.crossings,
            [p.path_id for p in self.paths],
            mode=self.weave_mode,
            manual=self.manual_over,  # type: ignore[arg-type]
            conflict_strategy=self.conflict_strategy,
        )
        for crossing_id, assignment in sorted(topology.assignments.items()):
            trace.emit(
                "topology", "crossing.assigned", f"{crossing_id}: {assignment.over_side} 侧在上。",
                object_ids=(crossing_id,),
                data={"over_side": assignment.over_side, "under_side": assignment.under_side,
                      "source": assignment.source, "explanation": assignment.explanation},
            )
        for diagnostic in [*detected.diagnostics, *topology.diagnostics]:
            trace.emit(
                "diagnostics", "diagnostic", diagnostic.message,
                object_ids=tuple(diagnostic.path_ids) + ((diagnostic.crossing_id,) if diagnostic.crossing_id else ()),
                data={"code": diagnostic.code, "severity": diagnostic.severity.value,
                      "details": diagnostic.details, "hints": diagnostic.hints},
            )
        rendered = render_stroke_geometry(
            self.paths, detected.crossings, topology,
            offset=self.offset, min_sin=self.min_sin, overshoot=self.overshoot,
            min_piece_length=self.min_piece_length, cap_style=self.cap_style,
        )
        for piece in rendered.ordered_pieces():
            trace.emit(
                "construction", "stroke.piece", f"生成描边片段 {piece.piece_id}。",
                object_ids=(piece.piece_id, piece.path_id),
                data={"point_count": len(piece.points), "arc_start": piece.arc_start,
                      "arc_end": piece.arc_end, "closed": piece.closed,
                      "draw_index": piece.draw_index},
            )
        for diagnostic in rendered.diagnostics:
            trace.emit("diagnostics", "diagnostic", diagnostic.message,
                       object_ids=tuple(diagnostic.path_ids),
                       data={"code": diagnostic.code, "severity": diagnostic.severity.value,
                             "hints": diagnostic.hints})
        trace.emit(
            "complete", "result.complete", "编织几何求解完成。",
            object_ids=tuple(p.piece_id for p in rendered.pieces),
            data={"path_count": len(self.paths), "crossing_count": len(detected.crossings),
                  "piece_count": len(rendered.pieces)},
        )
        self.result = LaceResult(
            paths=self.paths,
            crossings=detected.crossings,
            topology=topology,
            pieces=rendered.pieces,
            diagnostics=[*detected.diagnostics, *topology.diagnostics, *rendered.diagnostics],
            trace=trace.events,
            render_mode=self.render_mode,
            detection_stats=detected.stats,
        )
        return self.result
