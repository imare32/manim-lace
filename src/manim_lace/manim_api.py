"""Optional Manim convenience API. Install with ``pip install .[manim]``."""

from __future__ import annotations

from typing import Any

import numpy as np
from manim import (  # type: ignore[import-not-found]
    BLUE,
    GREY_B,
    ORANGE,
    RED,
    WHITE,
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Succession,
    Text,
    VGroup,
    VMobject,
    Wait,
)

from .adapters.manim import extract_paths
from .animation.plan import build_animation_plan
from .engine import LaceEngine
from .model import LaceResult, PolylinePath


class Lace(VGroup):
    """Turn a Manim 2D vector object into a stroke-style weave.

    This is a Manim VGroup facade over the renderer-neutral :class:`LaceEngine`.
    The area-based ``ribbon`` renderer is intentionally not implemented yet.
    """

    def __init__(
        self,
        target_mobject: Any,
        offset: float = 0.1,
        *,
        render: str = "stroke",
        weave_mode: str = "alternating",
        manual_over: dict[str, str] | None = None,
        stroke_color: Any = WHITE,
        stroke_width: float | None = None,
        stroke_opacity: float = 1.0,
        sample_error: float = 1e-3,
        min_sin: float = 0.2,
        **extra: Any,
    ) -> None:
        super().__init__()
        if extra:
            raise TypeError(f"unsupported Lace options in starter kit: {sorted(extra)}")
        if render != "stroke":
            raise NotImplementedError(
                "The starter kit currently implements render='stroke'. The 'ribbon' region renderer is a roadmap item."
            )
        self.target_mobject = target_mobject
        self.offset = float(offset)
        self.render_mode = render
        self.paths: list[PolylinePath] = extract_paths(target_mobject, max_error=sample_error)
        self.engine = LaceEngine(
            self.paths,
            offset=offset,
            weave_mode=weave_mode,  # type: ignore[arg-type]
            manual_over=manual_over,
            render_mode=render,
            min_sin=min_sin,
        )
        self.result: LaceResult = self.engine.solve()
        self.interlacing = self.result.topology  # migration-friendly discoverability
        self.crossings = self.result.crossings
        self.diagnostics = self.result.diagnostics
        self.trace = self.result.trace
        self.holes = VGroup()
        self.source_paths = VGroup()
        for path in self.paths:
            mob = _polyline_to_vmobject(path.points, closed=path.closed)
            mob.set_stroke(GREY_B, width=1.5, opacity=0.45)
            self.source_paths.add(mob)
        self.ribbons = VGroup()
        width = stroke_width if stroke_width is not None else max(1.0, 200.0 * offset)
        for piece in self.result.pieces:
            mob = _polyline_to_vmobject(piece.points, closed=piece.closed)
            mob.set_stroke(stroke_color, width=width, opacity=stroke_opacity)
            self.ribbons.add(mob)
        self.add(self.ribbons)

    @classmethod
    def from_parametric(
        cls, func: Any, t_range: tuple[float, float], *, offset: float = 0.1, **kwargs: Any
    ) -> "Lace":
        """Create a Manim VGroup directly from a parametric function.

        Geometry options are forwarded to ``LaceEngine.from_parametric``;
        style options (``stroke_color``, ``stroke_width``, ``stroke_opacity``)
        are consumed by this wrapper.
        """
        style = {
            "stroke_color": kwargs.pop("stroke_color", WHITE),
            "stroke_width": kwargs.pop("stroke_width", None),
            "stroke_opacity": kwargs.pop("stroke_opacity", 1.0),
        }
        render = kwargs.pop("render", "stroke")
        if render != "stroke":
            raise NotImplementedError("Only render='stroke' is available in starter kit v0.1")
        sample_error = kwargs.pop("sample_error", kwargs.pop("max_error", 1e-3))
        engine = LaceEngine.from_parametric(
            func, t_range, offset=offset, max_error=sample_error, **kwargs
        )
        obj = cls.__new__(cls)
        VGroup.__init__(obj)
        obj.target_mobject = None
        obj.offset = float(offset)
        obj.render_mode = "stroke"
        obj.paths = engine.paths
        obj.engine = engine
        obj.result = engine.solve()
        obj.interlacing = obj.result.topology
        obj.crossings = obj.result.crossings
        obj.diagnostics = obj.result.diagnostics
        obj.trace = obj.result.trace
        obj.holes = VGroup()
        obj.source_paths = VGroup(*[_polyline_to_vmobject(p.points, closed=p.closed) for p in obj.paths])
        for mob in obj.source_paths:
            mob.set_stroke(GREY_B, width=1.5, opacity=0.45)
        obj.ribbons = VGroup(*[_polyline_to_vmobject(p.points, closed=p.closed) for p in obj.result.pieces])
        width = style["stroke_width"] if style["stroke_width"] is not None else max(1.0, 200.0 * offset)
        for mob in obj.ribbons:
            mob.set_stroke(style["stroke_color"], width=width, opacity=style["stroke_opacity"])
        obj.add(obj.ribbons)
        return obj

    @classmethod
    def from_graph(
        cls, func: Any, x_range: tuple[float, float], *, offset: float = 0.1, **kwargs: Any
    ) -> "Lace":
        """Create a Manim VGroup directly from ``y = f(x)``."""
        style = {
            "stroke_color": kwargs.pop("stroke_color", WHITE),
            "stroke_width": kwargs.pop("stroke_width", None),
            "stroke_opacity": kwargs.pop("stroke_opacity", 1.0),
        }
        render = kwargs.pop("render", "stroke")
        if render != "stroke":
            raise NotImplementedError("Only render='stroke' is available in starter kit v0.1")
        sample_error = kwargs.pop("sample_error", kwargs.pop("max_error", 1e-3))
        engine = LaceEngine.from_graph(
            func, x_range, offset=offset, max_error=sample_error, **kwargs
        )
        obj = cls.__new__(cls)
        VGroup.__init__(obj)
        obj.target_mobject = None
        obj.offset = float(offset)
        obj.render_mode = "stroke"
        obj.paths = engine.paths
        obj.engine = engine
        obj.result = engine.solve()
        obj.interlacing = obj.result.topology
        obj.crossings = obj.result.crossings
        obj.diagnostics = obj.result.diagnostics
        obj.trace = obj.result.trace
        obj.holes = VGroup()
        obj.source_paths = VGroup(*[_polyline_to_vmobject(p.points, closed=p.closed) for p in obj.paths])
        for mob in obj.source_paths:
            mob.set_stroke(GREY_B, width=1.5, opacity=0.45)
        obj.ribbons = VGroup(*[_polyline_to_vmobject(p.points, closed=p.closed) for p in obj.result.pieces])
        width = style["stroke_width"] if style["stroke_width"] is not None else max(1.0, 200.0 * offset)
        for mob in obj.ribbons:
            mob.set_stroke(style["stroke_color"], width=width, opacity=style["stroke_opacity"])
        obj.add(obj.ribbons)
        return obj

    def as_mobject(self) -> "Lace":
        return self

    def build_animation(self, mode: str = "overview", *, show_sampling: bool = False, show_crossing_ids: bool = True) -> Any:
        """Compose a Manim Succession from actual solver data and trace events.

        Modes: overview, algorithm, construction, debug. This first adapter is
        intentionally simple; users may create custom scenes from ``self.trace``.
        """
        plan = build_animation_plan(self.result, mode=mode)  # type: ignore[arg-type]
        animations = []
        stage_names = {stage.name for stage in plan.stages}
        source_layer = self.source_paths.copy()
        if "input" in stage_names:
            animations.append(Create(source_layer, run_time=1.2))
            if show_sampling or mode in {"algorithm", "debug"}:
                dots = VGroup()
                for path in self.paths:
                    stride = max(1, len(path.points) // 40)
                    for point in path.points[::stride]:
                        dots.add(Dot([point[0], point[1], 0], radius=0.018, color=BLUE))
                if len(dots):
                    animations.append(FadeIn(dots, run_time=0.6))
                    animations.append(FadeOut(dots, run_time=0.3))
        if "crossings" in stage_names:
            marks = VGroup(*[
                Dot([event.point[0], event.point[1], 0], radius=0.055,
                    color=ORANGE if event.kind == "transverse" else BLUE)
                for event in self.crossings
            ])
            if len(marks):
                animations.append(FadeIn(marks, run_time=0.5))
                if show_crossing_ids or mode in {"algorithm", "debug"}:
                    labels = VGroup(*[
                        Text(event.crossing_id, font_size=14).next_to(
                            [event.point[0], event.point[1], 0], direction=np.array([0.1, 0.1, 0.0])
                        ) for event in self.crossings
                    ])
                    animations.append(FadeIn(labels, run_time=0.4))
                    animations.append(Wait(0.4))
                    animations.append(FadeOut(labels, run_time=0.2))
                animations.append(FadeOut(marks, run_time=0.25))
        if "topology" in stage_names and mode in {"algorithm", "debug"}:
            texts = VGroup()
            for event in self.crossings:
                assignment = self.result.topology.assignment_for(event.crossing_id)
                if assignment:
                    upper_path = event.path_a if assignment.over_side == "a" else event.path_b
                    text = Text(f"{event.crossing_id}: {upper_path} 在上", font_size=16)
                    text.move_to([event.point[0], event.point[1] + 0.25, 0])
                    texts.add(text)
            if len(texts):
                animations.extend([FadeIn(texts, run_time=0.5), Wait(0.5), FadeOut(texts, run_time=0.25)])
        if "diagnostics" in stage_names and self.result.diagnostics:
            lines = [f"{item.code}: {item.message}" for item in self.result.diagnostics[:5]]
            if len(self.result.diagnostics) > 5:
                lines.append(f"… 另有 {len(self.result.diagnostics) - 5} 条诊断")
            diagnostic_group = VGroup(*[
                Text(line[:92], font_size=12, color=RED)
                for line in lines
            ]).arrange(DOWN, aligned_edge=LEFT, buff=0.08).to_edge(DOWN)
            animations.extend([
                FadeIn(diagnostic_group, run_time=0.4),
                Wait(0.8),
                FadeOut(diagnostic_group, run_time=0.25),
            ])
        if "construction" in stage_names:
            animations.append(FadeOut(source_layer, run_time=0.4))
            animations.append(Create(self.ribbons.copy(), run_time=1.5))
        if "complete" in stage_names:
            animations.append(Wait(0.5))
        return Succession(*animations) if animations else Wait(0.1)


def _polyline_to_vmobject(points: np.ndarray, *, closed: bool = False) -> VMobject:
    xyz = np.column_stack((np.asarray(points, dtype=float)[:, :2], np.zeros(len(points))))
    if closed and not np.allclose(xyz[0], xyz[-1]):
        xyz = np.vstack((xyz, xyz[0]))
    mob = VMobject()
    mob.set_points_as_corners(xyz)
    return mob
