"""Renderer gallery: stroke caps, draw order and area-based ribbons.

Run:

    manim -pql examples/scene_gallery.py CapStyleGallery
    manim -pql examples/scene_gallery.py DrawOrderGallery
    manim -pql examples/scene_gallery.py RibbonGallery
    manim -pql examples/scene_gallery.py CircleLineGallery
    manim -pql examples/scene_gallery.py SineLineGallery
    manim -pql examples/scene_gallery.py TrefoilGallery
    manim -pql examples/scene_gallery.py StarGallery
    manim -pql examples/scene_gallery.py SpiralGallery
    manim -pql examples/scene_gallery.py GridGallery
    manim -pql examples/scene_gallery.py CrossGallery
    manim -pql examples/scene_gallery.py InfinityGallery
    manim -pql examples/scene_gallery.py ChainGallery

``CapStyleGallery`` renders the same two-strand weave three times to show how the end
caps change the cut: ``round`` and ``square`` paint half the ribbon width past the
centerline endpoint, so the gap widens by ``offset`` (reported as
``RENDER-CAP-EXTENSION``). ``DrawOrderGallery`` creates the pieces in the renderer's
painter order, which is computed from the over/under assignments. ``RibbonGallery``
shows the three backends side by side for the same input; the two ribbon ones need the
optional ``shapely`` extra.

The remaining classes are all **ribbon-backend** weaves on a white background with
black strokes — the canonical "lace on paper" look. Every one of them is described
once, as a :class:`GalleryEntry`, so the scene that renders it and
``examples/build_gallery.py`` (which writes ``examples/gallery.html`` and prints the
numbers on its cards) build exactly the same weave from the same code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from manim import *  # noqa: F403

from manim_lace import Lace
from manim_lace.benchmarks import piece_digest


def _two_strand_source() -> VGroup:
    """A closed curve and a straight line: the classic two-strand weave."""
    return VGroup(
        Circle(radius=1.0, color=GREY_B),
        Line(LEFT * 1.6, RIGHT * 1.6, color=GREY_B),
    )


# ---------------------------------------------------------------------------
# Style preset: white background, black outlines, light-grey fills — so the
# ribbon edges (stroke) are clearly visible against the fill.
#
# The default stroke_width computed by Lace from `offset` is `max(1.0, 200*offset)`,
# which is fine when stroke_color == fill_color (no visible seam), but it covers
# the fill completely when the two differ. Override with a thin explicit
# `stroke_width` (Manim units; ~2.0 ≈ 2.7 px at 1080p / frame=8) so the
# black outline reads as a thin border on top of the grey ribbon body.
# ---------------------------------------------------------------------------
_RIBBON_STYLE = dict(
    render="ribbon",
    stroke_color=BLACK,
    stroke_width=2.0,
    fill_color=LIGHT_GREY,
    hole_color=WHITE,
    fill_opacity=1.0,
    stroke_opacity=1.0,
    draw_holes=True,
)


@dataclass(frozen=True)
class GalleryEntry:
    """One showcase weave: how to build it, how to draw it, how to describe it.

    ``build`` is the single source of truth for the weave: the scene renders the
    ``Lace`` it returns and the gallery page reads its crossings, regions and
    diagnostics from it, so the numbers on the page always describe the picture
    next to them.
    """

    key: str
    title: str
    blurb: str
    build: Callable[[], Lace]
    tags: tuple[str, ...] = ()
    scale: float = 1.0
    run_time: float = 1.5


# ---------------------------------------------------------------------------
# Weave builders (the single source of truth for each showcase pattern)
# ---------------------------------------------------------------------------


def build_circle_line() -> Lace:
    source = VGroup(
        Circle(radius=1.2, color=GREY_B),
        Line(LEFT * 1.8, RIGHT * 1.8, color=GREY_B),
    )
    return Lace(source, offset=0.18, **_RIBBON_STYLE)


def build_sine_line() -> Lace:
    """Sine curve crossing a straight line — free-mode weave.

    The sine completes 3 periods across the range, so it meets the horizontal line
    seven times; the two outermost of those are the path's own endpoints sitting on
    the line, which the detector reports as endpoint touches rather than crossings.
    """
    source = VGroup(
        ParametricFunction(
            lambda t: np.array([t, 0.6 * np.sin(np.pi * t), 0]),
            t_range=[-3, 3],
            color=GREY_B,
        ),
        Line(LEFT * 3, RIGHT * 3, color=GREY_B),
    )
    return Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)


def build_trefoil() -> Lace:
    """Three overlapping circles forming a trefoil-like knot pattern."""
    source = VGroup()
    for angle in (0, 2 * PI / 3, 4 * PI / 3):
        center = 0.7 * np.array([np.cos(angle), np.sin(angle), 0])
        source.add(Circle(radius=1.0, color=GREY_B).move_to(center))
    return Lace(source, offset=0.14, weave_mode="free", **_RIBBON_STYLE)


def build_star() -> Lace:
    """A real pentagram ``{5/2}``: one closed path that crosses itself five times.

    A single path cannot be over and under itself, so these self-crossings are not
    solvable by alternation: the ribbon backend cuts the path into sections and lets
    the paint order decide, which it reports as ``REGION-DRAW-ORDER-CYCLE`` and
    ``REGION-OVERLAPPING-SECTIONS`` instead of pretending to have resolved them.
    """
    angles = [PI / 2 + i * 2 * PI / 5 for i in range(5)]
    outer = [np.array([1.4 * np.cos(a), 1.4 * np.sin(a), 0]) for a in angles]
    order = (0, 2, 4, 1, 3)
    verts = [outer[i] for i in order] + [outer[order[0]]]
    star = VMobject()
    star.set_points_as_corners(np.array(verts))
    star.set_stroke(GREY_B, width=2)
    return Lace(VGroup(star), offset=0.12, weave_mode="free", **_RIBBON_STYLE)


def build_spiral() -> Lace:
    """Archimedean spiral crossing a horizontal line — multi-turn weave.

    Angular range covers ~3.5 full turns so the spiral crosses the horizontal
    line ~7 times (twice per turn plus the initial crossing) while staying
    inside the camera frame.
    """
    spiral = ParametricFunction(
        lambda t: np.array([0.18 * t * np.cos(t), 0.18 * t * np.sin(t), 0]),
        t_range=[0.5, 7 * PI],
        color=GREY_B,
    )
    line = Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B)
    return Lace(VGroup(spiral, line), offset=0.10, weave_mode="free", **_RIBBON_STYLE)


def build_grid() -> Lace:
    """A 2×2 grid of really overlapping circles — multi-path weave.

    The centres sit 1.5 apart with radius 0.9, so neighbour circles cross in two
    points each (eight crossings in total) while the diagonals stay apart. Pushing
    the centres to ±1.0 would make the circles exactly tangent, which is not a
    weave at all.
    """
    source = VGroup()
    for pos in (
        0.75 * UP + 0.75 * LEFT, 0.75 * UP + 0.75 * RIGHT,
        0.75 * DOWN + 0.75 * LEFT, 0.75 * DOWN + 0.75 * RIGHT,
    ):
        source.add(Circle(radius=0.9, color=GREY_B).move_to(pos))
    return Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)


def build_cross() -> Lace:
    """Two perpendicular line pairs forming a cross — four-way intersection."""
    source = VGroup(
        Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B),
        Line(UP * 2.5, DOWN * 2.5, color=GREY_B),
        Line(LEFT * 2.5 + UP * 0.8, RIGHT * 2.5 + UP * 0.8, color=GREY_B),
        Line(LEFT * 2.5 + DOWN * 0.8, RIGHT * 2.5 + DOWN * 0.8, color=GREY_B),
    )
    return Lace(source, offset=0.15, weave_mode="free", **_RIBBON_STYLE)


def build_infinity() -> Lace:
    """Lemniscate (infinity) curve crossing a horizontal line."""
    lemniscate = ParametricFunction(
        lambda t: np.array([
            2.0 * np.cos(t) / (1 + np.sin(t) ** 2),
            2.0 * np.sin(t) * np.cos(t) / (1 + np.sin(t) ** 2),
            0,
        ]),
        t_range=[0, 2 * PI],
        color=GREY_B,
    )
    line = Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B)
    return Lace(VGroup(lemniscate, line), offset=0.13, weave_mode="free", **_RIBBON_STYLE)


def build_chain() -> Lace:
    """Three interlocked circles — chain-link pattern."""
    source = VGroup()
    for i, x in enumerate((-1.3, 0, 1.3)):
        source.add(Circle(radius=0.9, color=GREY_B).move_to(RIGHT * x + UP * 0.3 * (i % 2)))
    return Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)


def build_backend_trio() -> tuple[tuple[str, Lace], ...]:
    """The same two strands through all three backends (for ``RibbonGallery``)."""
    source = _two_strand_source()
    return (
        ("stroke", Lace(source, offset=0.22, render="stroke", stroke_color=TEAL)),
        ("boolean", Lace(
            source, offset=0.22, render="ribbon", stroke_color=TEAL,
            fill_color=TEAL, hole_color=BLACK,
        )),
        ("arrangement", Lace(
            source, offset=0.22, render="ribbon", ribbon_backend="arrangement",
            stroke_color=TEAL, fill_color=TEAL, hole_color=BLACK,
        )),
    )


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


class _WhiteScene(Scene):
    """Scene with a white background — use as the base for ribbon galleries."""

    def setup(self) -> None:
        self.camera.background_color = WHITE


class _WeaveGallery(_WhiteScene):
    """Shared drawing for the showcase weaves: title, framing, painter order."""

    entry: GalleryEntry

    def construct(self):
        lace = self.entry.build()
        print(f"{self.entry.key} diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text(self.entry.title, font_size=28).to_edge(UP))
        if self.entry.scale != 1.0:
            lace.scale(self.entry.scale)
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=self.entry.run_time)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class CapStyleGallery(Scene):
    def construct(self):
        self.add(Text("cap_style changes the cut, not the crossing", font_size=26).to_edge(UP))
        panels = VGroup()
        for cap_style in ("butt", "round", "square"):
            lace = Lace(_two_strand_source(), offset=0.16, cap_style=cap_style, stroke_color=TEAL)
            label = Text(cap_style, font_size=24).next_to(lace, DOWN, buff=0.35)
            panels.add(VGroup(lace, label))
        panels.arrange(RIGHT, buff=0.9).scale(0.8)
        self.play(Create(panels[0][0].ribbons), run_time=0.8)
        self.play(
            *[Create(panel[0].ribbons) for panel in panels[1:]],
            FadeIn(panels[0][1]),
            run_time=0.8,
        )
        self.play(FadeIn(VGroup(*[panel[1] for panel in panels[1:]])), run_time=0.4)
        self.wait()


class RibbonGallery(Scene):
    """The three backends side by side for the same two strands."""

    def construct(self):
        self.add(
            Text("stroke / ribbon (boolean) / ribbon (arrangement)", font_size=24).to_edge(UP)
        )
        panels = VGroup()
        for label, lace in build_backend_trio():
            lace.scale(0.7).shift(DOWN * 0.2)
            print(label, "diagnostics:", [diagnostic.code for diagnostic in lace.diagnostics])
            panels.add(VGroup(lace, Text(label, font_size=20).next_to(lace, DOWN, buff=0.3)))
        panels.arrange(RIGHT, buff=0.9)
        self.play(*[Create(panel[0].ribbons) for panel in panels], run_time=1.0)
        self.play(FadeIn(VGroup(*[panel[1] for panel in panels])), run_time=0.4)
        self.wait()


class DrawOrderGallery(Scene):
    def construct(self):
        source = VGroup(
            Line(np.array([-1.4, -1.4, 0.0]), np.array([2.4, 0.3, 0.0])),
            Line(np.array([-1.4, 0.7, 0.0]), np.array([2.4, -1.4, 0.0])),
            Line(np.array([-0.7, -1.6, 0.0]), np.array([0.3, 1.8, 0.0])),
        )
        lace = Lace(source, offset=0.1, stroke_color=TEAL)
        print("diagnostics:", [diagnostic.code for diagnostic in lace.diagnostics])
        print("piece digest:", piece_digest(lace.result.pieces))

        self.add(
            Text("pieces are created in painter order", font_size=26).to_edge(UP)
        )
        # ``lace.ribbons`` is already ordered by StrokePiece.draw_index.
        animations = [
            Create(mob, run_time=0.6) for mob in lace.ribbons
        ]
        labels = VGroup(*[
            Text(str(mob.z_index), font_size=18).move_to(mob.get_center() + UP * 0.35)
            for mob in lace.ribbons
        ])
        self.play(LaggedStart(*animations, lag_ratio=0.3))
        self.play(FadeIn(labels), run_time=0.4)
        self.wait()


# ===========================================================================
# Ribbon-backend galleries — white background, black strokes (lace on paper)
# ===========================================================================


class CircleLineGallery(_WeaveGallery):
    """Circle + straight line: the simplest two-strand weave."""

    entry = GalleryEntry(
        key="circle_line", title="圆与直线",
        blurb="闭合圆与水平直线交叉两次，是最简单的双路径交替编织。",
        tags=("交替模式", "参数曲线"), build=build_circle_line, run_time=1.2,
    )


class SineLineGallery(_WeaveGallery):
    """Sine curve crossing a straight line — free-mode weave."""

    entry = GalleryEntry(
        key="sine_line", title="正弦曲线与直线",
        blurb="正弦曲线与水平直线反复相交，自由模式编织；曲线两端正好压在直线上，"
              "会被如实报为端点接触而不是硬当成交叉。",
        tags=("自由模式", "参数曲线"), build=build_sine_line, scale=0.8,
    )


class TrefoilGallery(_WeaveGallery):
    """Three overlapping circles forming a trefoil-like knot pattern."""

    entry = GalleryEntry(
        key="trefoil", title="三叶结",
        blurb="三个相互交叠的圆构成三叶结拓扑，六处交叉点交替编织。",
        tags=("自由模式", "3 路径"), build=build_trefoil, scale=0.85,
    )


class StarGallery(_WeaveGallery):
    """Five-pointed star (self-intersecting closed polygon)."""

    entry = GalleryEntry(
        key="star", title="五角星",
        blurb="真正的五角星（{5/2}）：一条闭合路径自交五次。单路径没法用交替约束解决"
              "自己压自己，于是切成段、由绘制顺序决定谁在上，并把这件事报出来。",
        tags=("自由模式", "自相交", "分段 + 绘制顺序"), build=build_star,
    )


class SpiralGallery(_WeaveGallery):
    """Archimedean spiral crossing a horizontal line — multi-turn weave."""

    entry = GalleryEntry(
        key="spiral", title="螺旋与直线",
        blurb="阿基米德螺线绕数圈反复穿过水平线，交叉沿半径一次次向外推进。",
        tags=("自由模式", "参数曲线"), build=build_spiral, run_time=1.8,
    )


class GridGallery(_WeaveGallery):
    """A 2×2 grid of interlaced circles — multi-path weave."""

    entry = GalleryEntry(
        key="grid", title="四圆格栅",
        blurb="2×2 排列的四个圆两两相交，相邻的每一对都形成两处交叉，"
              "对角方向互不接触。",
        tags=("自由模式", "4 路径"), build=build_grid, scale=0.8, run_time=2.0,
    )


class CrossGallery(_WeaveGallery):
    """Two perpendicular line pairs forming a cross — four-way intersection."""

    entry = GalleryEntry(
        key="cross", title="十字格栅",
        blurb="三条水平线与一条垂直线交叉，构成四路交叉节点。",
        tags=("自由模式", "4 路径"), build=build_cross,
    )


class InfinityGallery(_WeaveGallery):
    """Lemniscate (infinity) curve crossing a horizontal line."""

    entry = GalleryEntry(
        key="infinity", title="双纽线与直线",
        blurb="双纽线（∞ 形）在中点穿过水平线，参数曲线编织。",
        tags=("自由模式", "参数曲线"), build=build_infinity, scale=0.8,
    )


class ChainGallery(_WeaveGallery):
    """Three interlocked circles — chain-link pattern."""

    entry = GalleryEntry(
        key="chain", title="链条",
        blurb="三个交错排列的圆模拟链环连接，每对相邻圆交叉编织。",
        tags=("自由模式", "3 路径"), build=build_chain, scale=0.8, run_time=1.8,
    )


#: The showcase order used by ``examples/build_gallery.py`` (scene name, entry).
GALLERY: tuple[tuple[str, GalleryEntry], ...] = (
    ("CircleLineGallery", CircleLineGallery.entry),
    ("SineLineGallery", SineLineGallery.entry),
    ("TrefoilGallery", TrefoilGallery.entry),
    ("StarGallery", StarGallery.entry),
    ("SpiralGallery", SpiralGallery.entry),
    ("GridGallery", GridGallery.entry),
    ("CrossGallery", CrossGallery.entry),
    ("InfinityGallery", InfinityGallery.entry),
    ("ChainGallery", ChainGallery.entry),
)
