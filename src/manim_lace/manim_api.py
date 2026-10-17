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
    YELLOW,
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
from .animation.plan import AnimationPlan, build_animation_plan
from .engine import LaceEngine
from .model import EventPolicy, LaceResult, PolylinePath
from .render.pixels import px_to_stroke_width
from .style import (
    BorderSpec,
    DensityPolicy,
    Palette,
    StylePlan,
    StylePolicy,
    apply_style,
    build_border,
    pattern_bounds,
    simplify_for_density,
)


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
        stroke_width_px: float | None = None,
        stroke_opacity: float = 1.0,
        fill_color: Any = None,
        fill_opacity: float = 1.0,
        hole_color: Any = BLACK,
        draw_holes: bool = True,
        palette: str | Palette | None = None,
        style_policy: StylePolicy | None = None,
        border: BorderSpec | None = None,
        border_color: Any = None,
        paper: bool = False,
        density_policy: DensityPolicy | None = None,
        sample_error: float = 1e-3,
        min_sin: float = 0.2,
        min_piece_length: float = 1e-7,
        candidate_strategy: str = "grid",
        refine: bool = True,
        event_policy: EventPolicy | dict[str, str] | str | None = None,
        conflict_strategy: str = "relax",
        cap_style: str = "butt",
        cover_allowance: float = 0.0,
        join: str = "miter",
        miter_limit: float = 5.0,
        ribbon_backend: str = "boolean",
        pixel_height: int = 720,
        frame_height: float = 4.0,
        **extra: Any,
    ) -> None:
        super().__init__()
        if extra:
            raise TypeError(f"unsupported Lace options in starter kit: {sorted(extra)}")
        if render not in ("stroke", "ribbon"):
            raise ValueError("render must be 'stroke' or 'ribbon'")
        if palette is not None and style_policy is not None:
            raise ValueError("pass either palette or style_policy, not both")
        self.target_mobject = target_mobject
        self.offset = float(offset)
        self.render_mode = render
        self._pixel_height = pixel_height
        self._frame_height = frame_height
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
            cover_allowance=cover_allowance,
            join=join,  # type: ignore[arg-type]
            miter_limit=miter_limit,
            ribbon_backend=ribbon_backend,  # type: ignore[arg-type]
        )
        self.result: LaceResult = self.engine.solve()
        self.interlacing = self.result.topology  # migration-friendly discoverability
        self.crossings = self.result.crossings
        self.diagnostics = self.result.diagnostics
        self.trace = self.result.trace
        self._attach_rendered({
            "stroke_color": stroke_color,
            "stroke_width": stroke_width,
            "stroke_width_px": stroke_width_px,
            "stroke_opacity": stroke_opacity,
            "fill_color": fill_color,
            "fill_opacity": fill_opacity,
            "hole_color": hole_color,
            "draw_holes": draw_holes,
            "palette": palette,
            "style_policy": style_policy,
            "border": border,
            "border_color": border_color,
            "paper": paper,
            "density_policy": density_policy,
        })

    def _attach_rendered(self, style: dict[str, Any]) -> None:
        """Build the output mobjects for the active backend and add them to the group."""
        self.source_paths = VGroup(*[
            _polyline_to_vmobject(path.points, closed=path.closed) for path in self.paths
        ])
        for mob in self.source_paths:
            mob.set_stroke(GREY_B, width=1.5, opacity=0.45)
        width = self._stroke_width(style)
        self._resolve_aesthetics(style)
        drawn = (
            self.density.kept(self.result) if self.density is not None else list(self.result.pieces)
        )
        if self.render_mode == "ribbon":
            self.ribbons, self.holes, self.outlines = _region_groups(
                drawn,
                fill_color=style["fill_color"] if style["fill_color"] is not None else style["stroke_color"],
                fill_opacity=style["fill_opacity"],
                stroke_color=style["stroke_color"],
                stroke_width=width,
                stroke_opacity=style["stroke_opacity"],
                hole_color=style["hole_color"],
                draw_holes=style["draw_holes"],
                plan=self.style_plan,
                overlay_edges=getattr(self.result, "outline_edges", ()),
                underlay_regions=getattr(self.result, "fill_underlay", ()),
                outline_above_fills=self.engine.ribbon_backend == "arrangement",
            )
        else:
            self.holes = VGroup()
            self.outlines = VGroup()
            self.ribbons = _ribbon_group(
                drawn, color=style["stroke_color"], width=width,
                opacity=style["stroke_opacity"], cap_style=self.engine.cap_style,
                plan=self.style_plan,
            )
        self.paper_layer = self._build_paper(style) if style.get("paper") else None
        self.border_layer = self._build_border_layer(style)
        layers = [
            layer
            for layer in (
                self.paper_layer, self.ribbons, self.holes, self.outlines, self.border_layer,
            )
            if layer is not None
        ]
        self.add(*layers)

    def _stroke_width(self, style: dict[str, Any]) -> float:
        """The Manim stroke width of the strands, honouring ``stroke_width_px``."""
        if style.get("stroke_width_px") is not None:
            return px_to_stroke_width(
                style["stroke_width_px"],
                pixel_height=self._pixel_height,
                frame_height=self._frame_height,
            )
        if style.get("stroke_width") is not None:
            return float(style["stroke_width"])
        return max(1.0, 200.0 * self.offset)

    def _resolve_aesthetics(self, style: dict[str, Any]) -> None:
        """Resolve the M6 layer: palette/policy, density simplification and frame.

        All of it is decoration: the result's crossings, assignments and geometry
        are already final and are not touched here (SPEC FR-062). The only extra
        geometry a policy can ask for — the paper rectangle and the border — is a
        separate layer, never a re-solve.
        """
        policy = style.get("style_policy")
        palette = style.get("palette")
        if policy is not None and not isinstance(policy, StylePolicy):
            raise ValueError(f"style_policy must be a StylePolicy; got {type(policy).__name__}")
        if policy is not None and palette is not None:
            raise ValueError("pass either palette or style_policy, not both")
        if policy is None and palette is not None:
            policy = StylePolicy(palette=palette)
        self.style: StylePolicy | None = policy
        self.style_plan: StylePlan | None = apply_style(self.result, policy) if policy else None
        density_policy = style.get("density_policy")
        if density_policy is not None and not isinstance(density_policy, DensityPolicy):
            raise ValueError(f"density_policy must be a DensityPolicy; got {type(density_policy).__name__}")
        self.density = (
            simplify_for_density(self.result, density_policy) if density_policy is not None else None
        )
        border = style.get("border")
        if border is not None and not isinstance(border, BorderSpec):
            raise ValueError(f"border must be a BorderSpec; got {type(border).__name__}")
        self.border_geometry = build_border(self.result, border) if border is not None else None
        self.style_diagnostics = [
            *(self.style_plan.diagnostics if self.style_plan is not None else ()),
            *(self.density.diagnostics if self.density is not None else ()),
        ]
        self.diagnostics = [*self.result.diagnostics, *self.style_diagnostics]

    def _build_paper(self, style: dict[str, Any]) -> Any:
        """A filled rectangle behind the pattern, in the policy's paper colour."""
        color = WHITE
        if self.style is not None and self.style.has_paper and self.style_plan is not None:
            color = self.style_plan.background
        margin = 0.25
        if self.border_geometry is not None:
            margin = self.border_geometry.spec.margin + self.border_geometry.spec.thickness
        return _paper_group(self.result, color=color, margin=margin)

    def _build_border_layer(self, style: dict[str, Any]) -> Any:
        """Stroke the frame centerlines; colour from the palette unless overridden."""
        if self.border_geometry is None:
            return None
        color = style.get("border_color")
        if color is None and self.style is not None and self.style.palette is not None:
            color = self.style.palette.color(self.border_geometry.color_index)
        if color is None:
            color = style["stroke_color"]
        return _border_group(
            self.border_geometry.centerlines,
            color=color,
            # BorderSpec.thickness is a world-space thickness and Manim's stroke_width
            # is 100x that (the same convention as the 200*offset strand heuristic).
            width=100.0 * self.border_geometry.spec.thickness,
        )

    @classmethod
    def _from_engine(cls, engine: LaceEngine, *, render: str, style: dict[str, Any]) -> Lace:
        """Wrap a solved engine into a facade object (shared by the factory methods)."""
        obj = cls.__new__(cls)
        VGroup.__init__(obj)
        obj.target_mobject = None
        obj.offset = engine.offset
        obj.render_mode = render
        obj._pixel_height = style.get("pixel_height", 720)
        obj._frame_height = style.get("frame_height", 4.0)
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

    @classmethod
    def from_implicit(
        cls,
        func: Any,
        x_range: tuple[float, float],
        y_range: tuple[float, float],
        *,
        level: float = 0.0,
        offset: float = 0.1,
        **kwargs: Any,
    ) -> Lace:
        """Create a Manim VGroup directly from ``F(x, y) = level`` (SPEC FR-008).

        No ``ImplicitFunction`` object is needed: the isocontour sampler extracts the curve
        itself, and each connected branch of the level set becomes its own strand. Geometry
        options are forwarded to ``LaceEngine.from_implicit`` (``resolution``, ``max_error``,
        ``orientation``, ...); style options are consumed by this wrapper as usual.
        """
        style = _pop_style(kwargs)
        render = _pop_render(kwargs)
        engine = LaceEngine.from_implicit(
            func, x_range, y_range, level=level, offset=offset, render_mode=render, **kwargs
        )
        return cls._from_engine(engine, render=render, style=style)

    @classmethod
    def from_paths(cls, paths: Any, *, offset: float = 0.1, **kwargs: Any) -> Lace:
        """Create a Manim VGroup from already-normalized polylines or coordinate arrays.

        Every entry may be a :class:`~manim_lace.model.PolylinePath` — so its closed
        state, source metadata, source parameters and optional source-curve probe are
        kept — or an ``(N, 2)``/``(N, 3)`` array, which becomes an open path. Unlike
        ``Lace(source)`` this does not run the Manim extraction adapter, so it is the
        entry point for geometry that was never a Manim object (benchmark sets, test
        fixtures, captured traced paths). The output layers are the same as for any
        other ``Lace``.

        Geometry options go to :class:`~manim_lace.engine.LaceEngine`; style options
        (``stroke_color``, ``stroke_width_px``, ``palette``, ...) are consumed here.
        """
        style = _pop_style(kwargs)
        render = _pop_render(kwargs)
        engine = LaceEngine(paths, offset=offset, render_mode=render, **kwargs)
        return cls._from_engine(engine, render=render, style=style)

    def as_mobject(self) -> Lace:
        return self

    def build_animation(
        self,
        mode: str = "overview",
        *,
        show_sampling: bool = False,
        show_crossing_ids: bool = True,
        durations: dict[str, float] | None = None,
        stage_modes: dict[str, tuple[str, ...]] | None = None,
    ) -> Any:
        """Compose a Manim Succession from actual solver data and trace events.

        Modes: overview, algorithm, construction, debug, custom. This first adapter is
        intentionally simple; users may create custom scenes from ``self.trace``.

        Parameters
        ----------
        mode:
            One of :data:`~manim_lace.animation.ANIMATION_MODES`.
        show_sampling:
            Also fade in sample points on the source paths.
        show_crossing_ids:
            Show crossing ID labels at each crossing.
        durations:
            Override per-stage durations (seconds). Keys are stage names
            (``input``, ``crossings``, ``topology``, ``construction``,
            ``diagnostics``, ``complete``). Unspecified stages use
            :data:`~manim_lace.animation.DEFAULT_STAGE_DURATIONS`.
        stage_modes:
            Override which modes a stage appears in.

        ``algorithm`` and ``debug`` mode also overlay a short read-out of the
        fine-grained trace (``sampling.subdivision`` while the paths are shown,
        ``region.face_walk`` while the regions are built), taken verbatim from the
        events the engine emitted. ``overview``, ``construction`` and ``custom``
        stay quiet about them.
        """
        plan = build_animation_plan(
            self.result,
            mode=mode,  # type: ignore[arg-type]
            durations=durations,
            stage_modes=stage_modes,
        )
        animations = []
        stage_names = {stage.name for stage in plan.stages}
        # Build a lookup so every animation gets its duration from the plan.
        stage_dur = {stage.name: stage.duration for stage in plan.stages}
        source_layer = self.source_paths.copy()
        if "input" in stage_names:
            d = stage_dur["input"]
            animations.append(Create(source_layer, run_time=d))
            if show_sampling or mode in {"algorithm", "debug"}:
                dots = VGroup()
                for path in self.paths:
                    stride = max(1, len(path.points) // 40)
                    for point in path.points[::stride]:
                        dots.add(Dot([point[0], point[1], 0], radius=0.018, color=BLUE))
                if len(dots):
                    animations.append(FadeIn(dots, run_time=d * 0.4))
                    animations.append(FadeOut(dots, run_time=d * 0.2))
            animations.extend(
                self._trace_note(plan, "input", "sampling.subdivision", mode=mode, run_time=d)
            )
        if "crossings" in stage_names:
            d = stage_dur["crossings"]
            marks = VGroup(*[
                Dot([event.point[0], event.point[1], 0], radius=0.055,
                    color=ORANGE if event.kind == "transverse" else BLUE)
                for event in self.crossings
            ])
            if len(marks):
                animations.append(FadeIn(marks, run_time=d * 0.35))
                if show_crossing_ids or mode in {"algorithm", "debug"}:
                    labels = VGroup(*[
                        Text(event.crossing_id, font_size=14).next_to(
                            [event.point[0], event.point[1], 0], direction=np.array([0.1, 0.1, 0.0])
                        ) for event in self.crossings
                    ])
                    animations.append(FadeIn(labels, run_time=d * 0.25))
                    animations.append(Wait(d * 0.3))
                    animations.append(FadeOut(labels, run_time=d * 0.15))
                animations.append(FadeOut(marks, run_time=d * 0.2))
        if "topology" in stage_names and mode in {"algorithm", "debug"}:
            d = stage_dur.get("topology", 1.0)
            texts = VGroup()
            for event in self.crossings:
                assignment = self.result.topology.assignment_for(event.crossing_id)
                if assignment:
                    upper_path = event.path_a if assignment.over_side == "a" else event.path_b
                    text = Text(f"{event.crossing_id}: {upper_path} 在上", font_size=16)
                    text.move_to([event.point[0], event.point[1] + 0.25, 0])
                    texts.add(text)
            if len(texts):
                animations.extend([
                    FadeIn(texts, run_time=d * 0.35),
                    Wait(d * 0.35),
                    FadeOut(texts, run_time=d * 0.2),
                ])
        if "diagnostics" in stage_names and self.result.diagnostics:
            d = stage_dur.get("diagnostics", 1.0)
            lines = [f"{item.code}: {item.message}" for item in self.result.diagnostics[:5]]
            if len(self.result.diagnostics) > 5:
                lines.append(f"… 另有 {len(self.result.diagnostics) - 5} 条诊断")
            diagnostic_group = VGroup(*[
                Text(line[:92], font_size=12, color=RED)
                for line in lines
            ]).arrange(DOWN, aligned_edge=LEFT, buff=0.08).to_edge(DOWN)
            animations.extend([
                FadeIn(diagnostic_group, run_time=d * 0.3),
                Wait(d * 0.6),
                FadeOut(diagnostic_group, run_time=d * 0.2),
            ])
        if "construction" in stage_names:
            d = stage_dur["construction"]
            animations.append(FadeOut(source_layer, run_time=d * 0.25))
            animations.append(Create(self.ribbons.copy(), run_time=d))
            if self.render_mode == "ribbon" and len(self.outlines):
                # Pieces whose exterior has flush chords are stroked by their runs in the
                # outline layer, so it has to be created with the fills, not instead of them.
                animations.append(Create(self.outlines.copy(), run_time=d))
            animations.extend(
                self._trace_note(plan, "construction", "region.face_walk", mode=mode, run_time=d)
            )
        if "complete" in stage_names:
            animations.append(Wait(stage_dur.get("complete", 1.0) * 0.5))
        return Succession(*animations) if animations else Wait(0.1)

    def _trace_note(
        self,
        plan: AnimationPlan,
        stage_name: str,
        event_type: str,
        *,
        mode: str,
        run_time: float,
    ) -> list[Any]:
        """A short, real read-out of a fine-grained trace event (SPEC M5).

        Only ``algorithm`` and ``debug`` show it, and every number comes from the
        event the engine emitted: the note never restates a count the algorithm did
        not actually produce.
        """
        if mode not in {"algorithm", "debug"}:
            return []
        events = [
            event
            for stage in plan.stages if stage.name == stage_name
            for event in stage.events if event.event_type == event_type
        ]
        if not events:
            return []
        lines: list[str] = []
        for event in events[:3]:
            data = event.data
            if event_type == "sampling.subdivision":
                lines.append(
                    f"细分 {data.get('path_id', '?')}：{data.get('node_count', 0)} 个递归节点"
                    f"（细分 {data.get('split_count', 0)}／接受 {data.get('accepted_count', 0)}），"
                    f"最深 {data.get('max_depth_reached', 0)} 层"
                )
            else:
                lines.append(
                    f"面域遍历（{data.get('backend', '?')}）：{data.get('node_count', 0)} 个节点，"
                    f"{data.get('crossing_count', 0)} 个交叉，归给 {data.get('owner_count', 0)} 条股线"
                )
        if len(events) > 3:
            lines.append(f"… 另有 {len(events) - 3} 条记录")
        note = VGroup(*[
            Text(line[:96], font_size=14, color=YELLOW) for line in lines
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.08).to_corner(LEFT + DOWN, buff=0.4)
        return [
            FadeIn(note, run_time=run_time * 0.3),
            Wait(run_time * 0.4),
            FadeOut(note, run_time=run_time * 0.2),
        ]


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
        "stroke_width_px": kwargs.pop("stroke_width_px", None),
        "stroke_opacity": kwargs.pop("stroke_opacity", 1.0),
        "fill_color": kwargs.pop("fill_color", None),
        "fill_opacity": kwargs.pop("fill_opacity", 1.0),
        "hole_color": kwargs.pop("hole_color", BLACK),
        "draw_holes": kwargs.pop("draw_holes", True),
        "palette": kwargs.pop("palette", None),
        "style_policy": kwargs.pop("style_policy", None),
        "border": kwargs.pop("border", None),
        "border_color": kwargs.pop("border_color", None),
        "paper": kwargs.pop("paper", False),
        "density_policy": kwargs.pop("density_policy", None),
        "pixel_height": kwargs.pop("pixel_height", 720),
        "frame_height": kwargs.pop("frame_height", 4.0),
    }


def _object_id(item: Any) -> str:
    """The stable ID of a stroke piece or a ribbon region."""
    identifier = getattr(item, "piece_id", None) or getattr(item, "region_id", None)
    if identifier is None:
        raise ValueError(f"unsupported piece object without piece_id/region_id: {type(item).__name__}")
    return str(identifier)


def _paint_order(pieces: list[Any], plan: StylePlan | None) -> list[Any]:
    """The pieces in the order they should be painted.

    Without a plan this is the geometry layer's own order (under strands first).
    With a plan it is the plan's order, which may have been re-declared by the
    style policy — that decision, and its visual consequence, is already reported
    through ``STYLE-DRAW-ORDER-OVERRIDE``.
    """
    if plan is None:
        return sorted(
            pieces,
            key=lambda item: (getattr(item, "draw_index", 0), _object_id(item)),
        )
    positions = {object_id: index for index, object_id in enumerate(plan.order)}
    return sorted(
        pieces,
        key=lambda item: (positions.get(_object_id(item), len(positions)), _object_id(item)),
    )


#: ``z_index`` of the fill-coloured hairline that closes the seams between abutting pieces
#: of one strand. It has to sit below the fills (0 and up) but above the paper (-1): each
#: fill then covers it again except exactly in the antialiased seam, and, being below the
#: outlines too, it cannot nick the strokes that are drawn on top.
_SEAM_FILL_Z = -0.5


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
    plan: StylePlan | None = None,
    overlay_edges: Any = (),
    underlay_regions: Any = (),
    outline_above_fills: bool = False,
) -> tuple[VGroup, VGroup, VGroup]:
    """Turn ribbon regions into a filled VGroup, a hole VGroup and an outline VGroup.

    Manim has no even-odd fill, so a hole is painted as its own polygon on top of the
    ribbon. Ring roles stay available on the geometry side for anything more exact.

    A piece whose exterior has flush edges (see ``RibbonRegion.flush_edges``) is filled
    without an outline stroke and its outline goes into the returned outline group as open
    runs instead: those chords are seams of the section split, and stroking them would draw
    a tick across a strand that runs straight through. The fill of such a piece is closed
    over the seams with a hairline in the fill's own colour, drawn one layer below the
    fills — two abutting polygons each paint only part of the pixels on their shared edge,
    so an unstroked seam would otherwise show the background through as a light line across
    the strand. That hairline shares the "close what the outline leaves open" job, so it is
    a member of the outline group too, told apart by its ``z_index``.

    A style plan, when given, supplies per-region colours and opacity instead of the
    uniform ones. ``underlay_regions`` are fill-only repairs drawn below every primary
    region; the experimental hybrid backend uses them to close area the Boolean cut
    genuinely missed without promoting any repair boundary to an outline.
    ``outline_above_fills`` is for the arrangement backend, whose regions are
    interior-disjoint: there is no later fill that is allowed to cover an under strand,
    so every visible outline has to be painted after every fill. Without that flag the
    interleaved painter order is kept for the Boolean and hybrid backends.
    """
    ordered = _paint_order(regions, plan)
    ribbons = VGroup()
    holes = VGroup()
    outlines = VGroup()
    for index, region in enumerate(sorted(
        underlay_regions,
        key=lambda item: (getattr(item, "draw_index", 0), _object_id(item)),
    )):
        assignment = plan.assignment_for(_object_id(region)) if plan is not None else None
        if assignment is None and plan is not None:
            assignment = plan.assignment_for_path(getattr(region, "path_id", ""))
        fill = assignment.paint_color if assignment is not None else (
            fill_color if fill_color is not None else stroke_color
        )
        opacity = assignment.fill_opacity if assignment is not None else fill_opacity
        mob = _polyline_to_vmobject(region.exterior.points, closed=True)
        mob.set_fill(fill, opacity=opacity)
        mob.set_stroke(width=0)
        # Paper is -1 and the seam-closing hairline is -0.5. Keep repair fills between
        # them and the real regions so they only show where a primary fill is absent.
        mob.z_index = -0.75 - index * 1e-9
        ribbons.add(mob)
        if draw_holes:
            for hole_index, hole in enumerate(region.holes):
                patch_hole = _polyline_to_vmobject(hole.points, closed=True)
                patch_hole.set_fill(hole_color, opacity=1.0)
                patch_hole.set_stroke(width=0)
                patch_hole.z_index = -0.7 - index * 1e-9 - hole_index * 1e-12
                holes.add(patch_hole)
    for index, region in enumerate(ordered):
        assignment = plan.assignment_for(_object_id(region)) if plan is not None else None
        if assignment is None and plan is not None:
            assignment = plan.assignment_for_path(getattr(region, "path_id", ""))
        piece_opacity = assignment.opacity if assignment is not None else stroke_opacity
        paint_color = assignment.paint_color if assignment is not None else fill_color
        paint_opacity = assignment.fill_opacity if assignment is not None else fill_opacity
        mob = _polyline_to_vmobject(region.exterior.points, closed=True)
        mob.set_fill(paint_color, opacity=paint_opacity)
        runs = _outline_mobjects(
            region, color=stroke_color, width=stroke_width,
            opacity=piece_opacity, z_index=index,
        )
        if not region.flush_edges:
            if outline_above_fills:
                # The arrangement has no painter-order hiding: a face's whole ring is
                # visible unless it is marked flush, so keep it as a stroke-only object
                # in the unified outline layer instead of stroking the fill in place.
                mob.set_stroke(width=0)
                ring = _polyline_to_vmobject(region.exterior.points, closed=True)
                ring.set_fill(opacity=0)
                ring.set_stroke(stroke_color, width=stroke_width, opacity=piece_opacity)
                outlines.add(ring)
            else:
                mob.set_stroke(stroke_color, width=stroke_width, opacity=piece_opacity)
        else:
            # The seams are seams of the split, not boundaries of the strand: no outline
            # stroke goes along them and the outline layer draws the runs in between. A piece
            # whose every edge is a seam has no outline of its own at all, which is correct —
            # the strand continues on all sides.
            #
            # The pieces are still separate polygons, and two polygons paint only part of the
            # pixels along their shared edge, so an untouched seam would show the background
            # as a hairline straight through the strand. Stroking the chord itself in the
            # fill's own colour one layer below the fills closes it: every fill covers that
            # line again except exactly in the seam. It belongs to no piece's outline, so it
            # goes into the outline group as well, one layer down.
            if paint_opacity > 0.0 and stroke_width > 0.0:
                for chord in _seam_chords(region):
                    seam = _polyline_to_vmobject(chord, closed=False)
                    seam.set_fill(opacity=0)
                    seam.set_stroke(paint_color, width=stroke_width, opacity=paint_opacity)
                    seam.z_index = _SEAM_FILL_Z
                    outlines.add(seam)
            mob.set_stroke(width=0)
            outlines.add(*runs)
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
    max_z = max((float(getattr(mob, "z_index", 0.0)) for mob in ribbons), default=0.0)
    if outline_above_fills:
        # Faces never overlap, so every visible boundary must be painted after every
        # fill. A shared boundary stroked by one face used to be cut in half by the
        # next face's fill, which made one side of the same line look thinner.
        for offset, mob in enumerate(outlines):
            if float(getattr(mob, "z_index", 0.0)) != _SEAM_FILL_Z:
                mob.z_index = max_z + 1.0 + offset * 1e-9
        for offset, hole in enumerate(holes):
            hole.z_index = max_z + 0.5 + offset * 1e-9
    for index, edge in enumerate(overlay_edges):
        start = np.asarray(edge.start, dtype=float)
        end = np.asarray(edge.end, dtype=float)
        # Explicit overlay edges are drawn on top of all fills, but their butt caps
        # can still leave an antialiased hairline against the stroke they repair.
        # Reuse the same half-line-width extension as the normal outline runs.
        extension = 0.5 * _STROKE_WIDTH_TO_UNITS * max(float(stroke_width), 0.0)
        overlay = _polyline_to_vmobject(
            _extend_ends(
                np.array([start, end]),
                extension,
                cap_to_half_length=False,
            ),
            closed=False,
        )
        overlay.set_fill(opacity=0)
        overlay.set_stroke(stroke_color, width=stroke_width, opacity=stroke_opacity)
        overlay.z_index = (
            max_z + 2.0 + index * 1e-9 if outline_above_fills else max_z + 1.0 + index * 1e-9
        )
        outlines.add(overlay)
    return ribbons, holes, outlines


def _paper_group(result: LaceResult, *, color: Any, margin: float) -> VGroup:
    """A filled rectangle behind the pattern, in the policy's paper colour."""
    min_x, min_y, max_x, max_y = pattern_bounds(result)
    points = np.array([
        [min_x - margin, min_y - margin],
        [max_x + margin, min_y - margin],
        [max_x + margin, max_y + margin],
        [min_x - margin, max_y + margin],
    ])
    mob = _polyline_to_vmobject(points, closed=True)
    mob.set_fill(color, opacity=1.0)
    mob.set_stroke(width=0)
    mob.z_index = -1
    return VGroup(mob)


def _border_group(centerlines: tuple[np.ndarray, ...], *, color: Any, width: float) -> VGroup:
    """Stroke the border centerlines (closed rings) as one VGroup."""
    group = VGroup()
    for index, ring in enumerate(centerlines):
        mob = _polyline_to_vmobject(ring, closed=True)
        mob.set_stroke(color, width=width, opacity=1.0)
        mob.set_fill(opacity=0)
        mob.z_index = index
        group.add(mob)
    return group


def _polyline_to_vmobject(points: np.ndarray, *, closed: bool = False) -> VMobject:
    xyz = np.column_stack((np.asarray(points, dtype=float)[:, :2], np.zeros(len(points))))
    if closed and not np.allclose(xyz[0], xyz[-1]):
        xyz = np.vstack((xyz, xyz[0]))
    mob = VMobject()
    mob.set_points_as_corners(xyz)
    return mob


def _distance_to_line(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    direction = end - start
    length = float(np.hypot(direction[0], direction[1]))
    if length == 0.0:
        return float(np.hypot(*(point - start)))
    normal = np.array([-direction[1], direction[0]]) / length
    return abs(float(np.dot(point - start, normal)))


def _rejoin_collinear(points: np.ndarray, tolerance: float = 1e-7) -> np.ndarray:
    """Drop the vertices that lie on the straight line through their neighbours.

    Boolean subtraction and polygonisation cut one straight edge into several collinear
    pieces — the corner of a lens, the chord of a section split. Stroking each piece on its
    own turns what should be a single line across the strand into a row of ticks, so the
    run is re-joined first. A real corner is nowhere near collinear and survives.

    A vertex the boundary walks *back* along (a zero-width spike, which polygonisation of a
    self-touching region does produce) is kept even though it is collinear: dropping it
    would shorten the stroke by the length of the spike and leave a gap in the outline.
    """
    if len(points) < 3:
        return points
    kept: list[np.ndarray] = [points[0]]
    for index in range(1, len(points) - 1):
        previous, current, following = kept[-1], points[index], points[index + 1]
        reverses = float(np.dot(current - previous, following - current)) <= 0.0
        if reverses or _distance_to_line(current, previous, following) > tolerance:
            kept.append(current)
    kept.append(points[-1])
    return np.array(kept)


def _ring_paths(region: Any, *, seams: bool) -> list[list[np.ndarray]]:
    """Maximal polylines of a piece's exterior ring, split at the section seams.

    Splitting a self-crossing path into sections leaves chords across the strand where two
    pieces of the *same* strand carry the same material (``RibbonRegion.flush_edges``). With
    ``seams=False`` the returned paths are the runs of boundary *between* those chords; with
    ``seams=True`` they are those chords themselves.

    Callers must look at ``flush_edges`` to tell "no seams at all" from "all seams": a piece
    without seams has no seam path, and its whole closed ring is its outline, which is not a
    path this function returns.
    """
    flush = set(region.flush_edges)
    if not flush:
        return []
    points = np.asarray(region.exterior.points, dtype=float)
    count = len(points) - 1  # the exterior repeats its first point at the end
    start = min(flush)
    paths: list[list[np.ndarray]] = []
    current: list[np.ndarray] = []
    for step in range(count):
        vertex = (start + 1 + step) % count
        following = (vertex + 1) % count
        if (vertex in flush) is seams:
            if not current:
                current = [points[vertex]]
            current.append(points[following])
        elif current:
            paths.append(current)
            current = []
    if current:
        paths.append(current)
    return paths


def _stroke_runs(region: Any) -> list[np.ndarray]:
    """The parts of a piece's outline that are a real boundary, as open polylines.

    The strand runs straight through a seam, so stroking it draws a tick across the ribbon
    and makes the ribbon look cut although it is not. The outline is therefore drawn as the
    runs *between* those chords; a piece all of whose edges are seams yields no run at all.
    """
    return [_rejoin_collinear(np.array(path)) for path in _ring_paths(region, seams=False)]


def _seam_chords(region: Any) -> list[np.ndarray]:
    """The seams of a piece as open polylines, one per run of seam edges.

    These are the chords the fill has to be closed over: they are not part of the strand's
    boundary, so nothing may be stroked along them in the outline colour.
    """
    return [np.array(path) for path in _ring_paths(region, seams=True)]


#: Manim's own line-width multiple: a ``stroke_width`` of 1 is 0.01 world units thick, see
#: :mod:`manim_lace.render.pixels`.
_STROKE_WIDTH_TO_UNITS = 0.01


def _extend_ends(
    points: np.ndarray,
    extension: float,
    *,
    cap_to_half_length: bool = True,
) -> np.ndarray:
    """Push both ends of a stroke run outwards by ``extension`` world units.

    A run stops at a seam and the next run takes over on the far side of it, so their butt
    caps meet in a single point. Polygon antialiasing leaves that joint partly uncovered and
    the fill underneath shows through as a dot on the outline; letting the two runs overlap a
    little closes it. Each end is extended along its own last edge, which is a strand edge
    rather than the seam, so the extra length lands on the line the outline already draws.
    """
    if extension <= 0.0 or len(points) < 2:
        return points
    extended = points.copy()
    for end, neighbour in ((0, 1), (-1, -2)):
        direction = points[end] - points[neighbour]
        length = float(np.hypot(direction[0], direction[1]))
        if length > 0.0:
            reach = min(extension, 0.5 * length) if cap_to_half_length else extension
            extended[end] = points[end] + direction * (reach / length)
    return extended


def _outline_mobjects(
    region: Any, *, color: Any, width: float, opacity: float, z_index: int
) -> list[VMobject]:
    """Stroke-only mobjects for the outline runs of a piece, one per run.

    One mobject per run instead of one mobject with several subpaths: ``start_new_path``
    links the new subpath to the previous one with a line, which is exactly the seam this
    is meant to leave out.
    """
    extension = 0.5 * _STROKE_WIDTH_TO_UNITS * max(float(width), 0.0)
    mobjects = []
    for run in _stroke_runs(region):
        mob = _polyline_to_vmobject(_extend_ends(run, extension), closed=False)
        mob.set_fill(opacity=0)
        mob.set_stroke(color, width=width, opacity=opacity)
        mob.z_index = z_index
        mobjects.append(mob)
    return mobjects


#: Manim's name for each cap style the geometry layer knows about.
_MANIM_CAP_STYLES = {
    "butt": CapStyleType.BUTT,
    "round": CapStyleType.ROUND,
    "square": CapStyleType.SQUARE,
}


def _ribbon_group(
    pieces: list[Any],
    *,
    color: Any,
    width: float,
    opacity: float,
    cap_style: str,
    plan: StylePlan | None = None,
) -> VGroup:
    """One VMobject per piece, in the renderer's draw order, with the cap style set.

    The order of the group members is the painter order computed by the geometry
    layer (under paths first), so an imperfect cut end stays covered by the path that
    is over it. ``z_index`` repeats that order for scenes that re-sort mobjects. A
    style plan, when given, supplies the per-piece colour and opacity.
    """
    group = VGroup()
    for index, piece in enumerate(_paint_order(pieces, plan)):
        assignment = plan.assignment_for(_object_id(piece)) if plan is not None else None
        mob = _polyline_to_vmobject(piece.points, closed=piece.closed)
        mob.set_stroke(
            assignment.color if assignment is not None else color,
            width=width,
            opacity=assignment.opacity if assignment is not None else opacity,
        )
        mob.set_cap_style(_MANIM_CAP_STYLES[cap_style])
        mob.z_index = index
        group.add(mob)
    return group
