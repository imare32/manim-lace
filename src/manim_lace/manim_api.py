"""Optional Manim convenience API. Install with ``pip install .[manim]``."""

from __future__ import annotations

from typing import Any

import numpy as np
from manim import (  # type: ignore[import-not-found]
    BLACK,
    BLUE,
    DOWN,
    GREY_B,
    LEFT,
    ORANGE,
    RED,
    WHITE,
    CapStyleType,
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
from .model import EventPolicy, LaceResult, PolylinePath


class Lace(VGroup):
    """Turn a Manim 2D vector object into a weave.

    This is a Manim VGroup facade over the renderer-neutral :class:`LaceEngine`.
    ``render='stroke'`` builds cut centerline strokes; ``render='ribbon'`` builds
    area-based regions (fill plus outline) and needs the optional ``shapely`` extra.
    In ribbon mode the holes are separate mobjects (Manim has no even-odd fill), filled
    with ``hole_color`` so they read as gaps; pick a colour that matches your scene
    background, or set ``draw_holes=False`` and handle them yourself.
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
        fill_color: Any = None,
        fill_opacity: float = 1.0,
        hole_color: Any = BLACK,
        draw_holes: bool = True,
        sample_error: float = 1e-3,
        min_sin: float = 0.2,
        min_piece_length: float = 1e-7,
        candidate_strategy: str = "grid",
        refine: bool = True,
        event_policy: EventPolicy | dict[str, str] | str | None = None,
        conflict_strategy: str = "error",
        cap_style: str = "butt",
        join: str = "miter",
        miter_limit: float = 5.0,
        **extra: Any,
    ) -> None:
        super().__init__()
        if extra:
            raise TypeError(f"unsupported Lace options in starter kit: {sorted(extra)}")
        if render not in ("stroke", "ribbon"):
            raise ValueError("render must be 'stroke' or 'ribbon'")
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
            min_piece_length=min_piece_length,
            candidate_strategy=candidate_strategy,  # type: ignore[arg-type]
            refine=refine,
            event_policy=event_policy,
            conflict_strategy=conflict_strategy,  # type: ignore[arg-type]
            cap_style=cap_style,  # type: ignore[arg-type]
            join=join,  # type: ignore[arg-type]
            miter_limit=miter_limit,
        )
        self.result: LaceResult = self.engine.solve()
        self.interlacing = self.result.topology  # migration-friendly discoverability
        self.crossings = self.result.crossings
        self.diagnostics = self.result.diagnostics
        self.trace = self.result.trace
        self._attach_rendered({
            "stroke_color": stroke_color,
            "stroke_width": stroke_width,
            "stroke_opacity": stroke_opacity,
            "fill_color": fill_color,
            "fill_opacity": fill_opacity,
            "hole_color": hole_color,
            "draw_holes": draw_holes,
        })

    def _attach_rendered(self, style: dict[str, Any]) -> None:
        """Build the output mobjects for the active backend and add them to the group."""
        self.source_paths = VGroup(*[
            _polyline_to_vmobject(path.points, closed=path.closed) for path in self.paths
        ])
        for mob in self.source_paths:
            mob.set_stroke(GREY_B, width=1.5, opacity=0.45)
        stroke_width = style["stroke_width"]
        width = stroke_width if stroke_width is not None else max(1.0, 200.0 * self.offset)
        if self.render_mode == "ribbon":
            self.ribbons, self.holes = _region_groups(
                self.result.pieces,
                fill_color=style["fill_color"] if style["fill_color"] is not None else style["stroke_color"],
                fill_opacity=style["fill_opacity"],
                stroke_color=style["stroke_color"],
                stroke_width=width,
                stroke_opacity=style["stroke_opacity"],
                hole_color=style["hole_color"],
                draw_holes=style["draw_holes"],
            )
        else:
            self.holes = VGroup()
            self.ribbons = _ribbon_group(
                self.result.pieces, color=style["stroke_color"], width=width,
                opacity=style["stroke_opacity"], cap_style=self.engine.cap_style,
            )
        self.add(self.ribbons, self.holes)

    @classmethod
    def _from_engine(cls, engine: LaceEngine, *, render: str, style: dict[str, Any]) -> Lace:
        """Wrap a solved engine into a facade object (shared by the factory methods)."""
        obj = cls.__new__(cls)
        VGroup.__init__(obj)
        obj.target_mobject = None
        obj.offset = engine.offset
        obj.render_mode = render
        obj.paths = engine.paths
        obj.engine = engine
        obj.result = engine.solve()
        obj.interlacing = obj.result.topology
        obj.crossings = obj.result.crossings
        obj.diagnostics = obj.result.diagnostics
        obj.trace = obj.result.trace
        obj._attach_rendered(style)
        return obj

    @classmethod
    def from_parametric(
        cls, func: Any, t_range: tuple[float, float], *, offset: float = 0.1, **kwargs: Any
    ) -> Lace:
        """Create a Manim VGroup directly from a parametric function.

        Geometry options are forwarded to ``LaceEngine.from_parametric``; style options
        (``stroke_color``, ``stroke_width``, ``stroke_opacity``, ``fill_color``,
        ``fill_opacity``, ``hole_color``, ``draw_holes``) are consumed by this wrapper.
        """
        style = _pop_style(kwargs)
        render = _pop_render(kwargs)
        sample_error = kwargs.pop("sample_error", kwargs.pop("max_error", 1e-3))
        engine = LaceEngine.from_parametric(
            func, t_range, offset=offset, max_error=sample_error, render_mode=render, **kwargs
        )
        return cls._from_engine(engine, render=render, style=style)

    @classmethod
    def from_graph(
        cls, func: Any, x_range: tuple[float, float], *, offset: float = 0.1, **kwargs: Any
    ) -> Lace:
        """Create a Manim VGroup directly from ``y = f(x)``."""
        style = _pop_style(kwargs)
        render = _pop_render(kwargs)
        sample_error = kwargs.pop("sample_error", kwargs.pop("max_error", 1e-3))
        engine = LaceEngine.from_graph(
            func, x_range, offset=offset, max_error=sample_error, render_mode=render, **kwargs
        )
        return cls._from_engine(engine, render=render, style=style)

    def as_mobject(self) -> Lace:
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


def _pop_render(kwargs: dict[str, Any]) -> str:
    """Take the backend selector out of the keyword arguments."""
    render = kwargs.pop("render", "stroke")
    if render not in ("stroke", "ribbon"):
        raise ValueError("render must be 'stroke' or 'ribbon'")
    return render


def _pop_style(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Take the style-only options out of the keyword arguments."""
    return {
        "stroke_color": kwargs.pop("stroke_color", WHITE),
        "stroke_width": kwargs.pop("stroke_width", None),
        "stroke_opacity": kwargs.pop("stroke_opacity", 1.0),
        "fill_color": kwargs.pop("fill_color", None),
        "fill_opacity": kwargs.pop("fill_opacity", 1.0),
        "hole_color": kwargs.pop("hole_color", BLACK),
        "draw_holes": kwargs.pop("draw_holes", True),
    }


def _region_groups(
    regions: list[Any],
    *,
    fill_color: Any,
    fill_opacity: float,
    stroke_color: Any,
    stroke_width: float,
    stroke_opacity: float,
    hole_color: Any,
    draw_holes: bool,
) -> tuple[VGroup, VGroup]:
    """Turn ribbon regions into a filled VGroup plus a separate hole VGroup.

    Manim has no even-odd fill, so a hole is painted as its own polygon on top of the
    ribbon. Ring roles stay available on the geometry side for anything more exact.
    """
    ordered = sorted(regions, key=lambda region: (region.draw_index, region.region_id))
    ribbons = VGroup()
    holes = VGroup()
    for index, region in enumerate(ordered):
        mob = _polyline_to_vmobject(region.exterior.points, closed=True)
        mob.set_fill(fill_color, opacity=fill_opacity)
        mob.set_stroke(stroke_color, width=stroke_width, opacity=stroke_opacity)
        # Overlapping sections of a self-crossing path are resolved by this order.
        mob.z_index = index
        ribbons.add(mob)
        if draw_holes:
            for hole in region.holes:
                hole_mob = _polyline_to_vmobject(hole.points, closed=True)
                hole_mob.set_fill(hole_color, opacity=1.0)
                hole_mob.set_stroke(width=0)
                hole_mob.z_index = index
                holes.add(hole_mob)
    return ribbons, holes


def _polyline_to_vmobject(points: np.ndarray, *, closed: bool = False) -> VMobject:
    xyz = np.column_stack((np.asarray(points, dtype=float)[:, :2], np.zeros(len(points))))
    if closed and not np.allclose(xyz[0], xyz[-1]):
        xyz = np.vstack((xyz, xyz[0]))
    mob = VMobject()
    mob.set_points_as_corners(xyz)
    return mob


#: Manim's name for each cap style the geometry layer knows about.
_MANIM_CAP_STYLES = {
    "butt": CapStyleType.BUTT,
    "round": CapStyleType.ROUND,
    "square": CapStyleType.SQUARE,
}


def _ribbon_group(
    pieces: list[Any], *, color: Any, width: float, opacity: float, cap_style: str
) -> VGroup:
    """One VMobject per piece, in the renderer's draw order, with the cap style set.

    The order of the group members is the painter order computed by the geometry
    layer (under paths first), so an imperfect cut end stays covered by the path that
    is over it. ``z_index`` repeats that order for scenes that re-sort mobjects.
    """
    group = VGroup()
    for index, piece in enumerate(sorted(pieces, key=lambda item: (item.draw_index, item.piece_id))):
        mob = _polyline_to_vmobject(piece.points, closed=piece.closed)
        mob.set_stroke(color, width=width, opacity=opacity)
        mob.set_cap_style(_MANIM_CAP_STYLES[cap_style])
        mob.z_index = index
        group.add(mob)
    return group
