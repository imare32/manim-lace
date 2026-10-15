"""Orchestration layer for path normalization, crossings, topology, and strokes."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import numpy as np

from .animation.trace import TraceRecorder
from .geometry.intersections import detect_crossings
from .geometry.sampling import sample_graph, sample_parametric
from .model import LaceResult, PathSource, PolylinePath
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
    ) -> None:
        if not np.isfinite(offset) or offset <= 0:
            raise ValueError("offset must be positive and finite")
        if render_mode not in {"stroke", "ribbon"}:
            raise ValueError("render_mode must be 'stroke' or 'ribbon'")
        if not np.isfinite(min_piece_length) or min_piece_length < 0:
            raise ValueError("min_piece_length must be finite and non-negative")
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
            self.paths, position_tol=self.position_tol, angle_tol=self.angle_tol,
        )
        for crossing in detected.crossings:
            trace.emit(
                "crossings", "crossing.detected", f"识别交叉候选 {crossing.crossing_id}（{crossing.kind}）。",
                object_ids=(crossing.crossing_id, crossing.path_a, crossing.path_b),
                data={"point": crossing.point, "s_a": crossing.s_a, "s_b": crossing.s_b,
                      "sin_angle": crossing.sin_angle, "kind": crossing.kind},
            )
        topology = solve_weave(
            detected.crossings,
            [p.path_id for p in self.paths],
            mode=self.weave_mode,
            manual=self.manual_over,  # type: ignore[arg-type]
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
            min_piece_length=self.min_piece_length,
        )
        for piece in rendered.pieces:
            trace.emit(
                "construction", "stroke.piece", f"生成描边片段 {piece.piece_id}。",
                object_ids=(piece.piece_id, piece.path_id),
                data={"point_count": len(piece.points), "arc_start": piece.arc_start,
                      "arc_end": piece.arc_end, "closed": piece.closed},
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
        )
        return self.result
