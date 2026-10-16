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
from typing import Any

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
    """Sine curve crossing a straight line — alternating weave.

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
    return Lace(source, offset=0.13, **_RIBBON_STYLE)


def build_trefoil() -> Lace:
    """Three overlapping circles forming a trefoil-like knot pattern."""
    source = VGroup()
    for angle in (0, 2 * PI / 3, 4 * PI / 3):
        center = 0.7 * np.array([np.cos(angle), np.sin(angle), 0])
        source.add(Circle(radius=1.0, color=GREY_B).move_to(center))
    return Lace(source, offset=0.14, **_RIBBON_STYLE)


def _star_source() -> VGroup:
    """A ``{5/2}`` pentagram: one closed path that crosses itself five times."""
    angles = [PI / 2 + i * 2 * PI / 5 for i in range(5)]
    outer = [np.array([1.4 * np.cos(a), 1.4 * np.sin(a), 0]) for a in angles]
    order = (0, 2, 4, 1, 3)
    verts = [outer[i] for i in order] + [outer[order[0]]]
    star = VMobject()
    star.set_points_as_corners(np.array(verts))
    star.set_stroke(GREY_B, width=2)
    return VGroup(star)


def _fit_frame(composed: Mobject, *, margin: float = 1.0) -> Mobject:
    """Shrink a composed layout so it fits the camera frame.

    Not a formatting nicety: a row of panels silently overflows the frame otherwise,
    and the overflow is invisible in the still until someone looks at it. (Same helper
    as in ``scene_rosette.py``; the example modules stay importable on their own.)
    """
    if composed.width > config.frame_width - margin:
        composed.scale_to_fit_width(config.frame_width - margin)
    if composed.height > config.frame_height - margin:
        composed.scale_to_fit_height(config.frame_height - margin)
    return composed


def build_star() -> Lace:
    """A real pentagram ``{5/2}``: one closed path that crosses itself five times.

    A self-crossing is an ordinary transverse event here: the path visits each of the
    five crossings twice, so travelling the strand gives 10 passes and the strict
    alternation constraint has a solution (measured: every visit alternates, all five
    assignments carry ``source='alternating'``, no relaxation). Each pass belongs to a
    different section of the same ribbon, so the under pass is cut by the local overlap
    of the two offset bands exactly like a cross-path crossing — the weave is decided by
    geometry, not by paint order.
    """
    return Lace(_star_source(), offset=0.12, **_RIBBON_STYLE)


def build_spiral() -> Lace:
    """Archimedean spiral crossing a horizontal line — multi-turn weave.

    Angular range covers ~3.5 full turns so the spiral crosses the horizontal
    line ~7 times (twice per turn plus the initial crossing) while staying
    inside the camera frame. Strict alternation cannot hold at every crossing of
    this source, so the engine's default (alternating, relaxing only what has to
    give) reports the two relaxed crossings and keeps the rest alternating.
    """
    spiral = ParametricFunction(
        lambda t: np.array([0.18 * t * np.cos(t), 0.18 * t * np.sin(t), 0]),
        t_range=[0.5, 7 * PI],
        color=GREY_B,
    )
    line = Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B)
    return Lace(VGroup(spiral, line), offset=0.10, **_RIBBON_STYLE)


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
    return Lace(source, offset=0.13, **_RIBBON_STYLE)


def build_cross() -> Lace:
    """Three horizontal lines and one vertical one — a four-way intersection.

    The vertical crosses three times, so the alternating solution is what the eye
    expects there: over, under, over (or the mirror), never two in a row.
    """
    source = VGroup(
        Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B),
        Line(UP * 2.5, DOWN * 2.5, color=GREY_B),
        Line(LEFT * 2.5 + UP * 0.8, RIGHT * 2.5 + UP * 0.8, color=GREY_B),
        Line(LEFT * 2.5 + DOWN * 0.8, RIGHT * 2.5 + DOWN * 0.8, color=GREY_B),
    )
    return Lace(source, offset=0.15, **_RIBBON_STYLE)


def build_infinity() -> Lace:
    """Lemniscate (infinity) crossing a horizontal line.

    The curve crosses *itself* at the centre, exactly where the line passes through: a
    coincident crossing, which is the case the diagnostic
    ``REGION-COINCIDENT-CROSSINGS`` warns about (two crossings at one point cannot both
    claim their cut area). The self-crossing is woven like any other one, by cutting the
    under pass where the two offset bands overlap locally.
    Strict alternation makes the two crossings at that shared point remove their overlap
    in opposite directions, which the area accounting then reports as
    ``REGION-AREA-MISMATCH``; the card asks for ``weave_mode="free"`` and says so.
    """
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
    return Lace(source, offset=0.13, **_RIBBON_STYLE)


#: Palette for the backend comparison card. Two clearly different strand colours are
#: load-bearing there: ribbon mode removes the under strand's footprint from the
#: geometry, and that cut is visible *only* as a colour change (see `build_backend_trio`).
_BACKEND_PALETTE = "natsu"


#: The hairline border the ribbon panels carry, in output pixels (``stroke_width_px``).
HAIRLINE_PX: float = 2.0


class StrokePanel(Lace):
    """The stroke channel's panel, at the strand width the ribbon panels show.

    The channel draws each cut piece as one *stroke*, so its strands are stroke widths
    rather than geometry — and a card that fits its composition into the frame scales
    geometry, while ``Mobject.scale`` leaves stroke widths alone. The strands would then
    come out wider than the ribbon bands beside them (measured on the ``RosetteWeave``
    card: 22 px against 11 px); :meth:`refit` re-strokes them for the scale the fit
    applied, so the three panels stay the same input at any size.

    The panel deliberately carries **no border**, although the ribbon panels do (their
    ``stroke_width_px`` hairline). The pieces are cut to abut exactly at every crossing,
    so a border cannot separate the strands there without inventing a line the geometry
    does not have: parked under all the pieces it is painted over by the neighbouring
    piece's body and the junction comes out seamless, and drawn per piece — so that the
    piece painted later outlines itself against the earlier one — it outlines the
    abutting ends as well, which reads as "both strands outlined, same layer": the one
    thing the weave is not. The panel shows the channel's plain output instead. Whether
    the crossings read as over/under there is then a matter of the cut geometry; a gap
    around the strand on top is what ``cover_allowance`` buys, at the price of drawing
    the panels differently.
    """

    def __init__(self, source: Any, offset: float, *, palette: Any = None, **style: Any) -> None:
        super().__init__(source, offset=offset, render="stroke", palette=palette, **style)

    def refit(self, factor: float) -> None:
        """Re-stroke the strands for the scale a frame fit applied."""
        widths = [float(np.max(np.asarray(mob.get_stroke_width()))) for mob in self.ribbons]
        body = (max(widths) if widths else max(1.0, 200.0 * self.offset)) * factor
        for mob in self.ribbons:
            mob.set_stroke(width=body)


def build_backend_trio() -> tuple[tuple[str, Lace], ...]:
    """The same two strands through all three backends (for ``RibbonGallery``).

    The two strands deliberately get different colours. Ribbon mode cuts the under
    strand where the over strand passes, so the weave shows up as one colour
    interrupting another; with a shared colour both ribbon panels collapse into a
    single silhouette and the card stops comparing anything. ``stroke_color`` stays
    black for the ribbon panels (a hairline border that makes the cuts readable);
    stroke mode ignores it and takes its strand colour from the palette.
    """
    source = _two_strand_source()
    fill = dict(palette=_BACKEND_PALETTE, hole_color=WHITE, fill_opacity=1.0)
    return (
        ("stroke", StrokePanel(source, 0.22, palette=_BACKEND_PALETTE)),
        ("boolean", Lace(
            source, offset=0.22, render="ribbon",
            stroke_color=BLACK, stroke_width_px=2.0, **fill,
        )),
        ("arrangement", Lace(
            source, offset=0.22, render="ribbon", ribbon_backend="arrangement",
            stroke_color=BLACK, stroke_width_px=2.0, **fill,
        )),
    )


#: One mechanism line per channel, printed under the panel label on the card.
CHANNEL_CAPTIONS: dict[str, str] = {
    "stroke": "中心线切口，靠遮挡读上下",
    "boolean": "下股减掉重叠区",
    "arrangement": "平面剖分，按交叉归面",
}


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


class _WhiteScene(Scene):
    """Scene with a white background — use as the base for ribbon galleries."""

    def setup(self) -> None:
        self.camera.background_color = WHITE


def _outline_animations(lace: Lace) -> list[Animation]:
    """Animations for the outline layer, which exists only where a piece has flush seams.

    Ribbon mode strokes a piece through its outline layer when its exterior contains the
    chords where the section split meets itself: the open runs in the outline colour, plus
    those same seams restated in the fill colour one layer below the fills, so abutting
    pieces of one strand do not show a hairline between them. A scene that draws
    ``lace.ribbons`` must draw ``lace.outlines`` with it or the strands lose their outlines.
    """
    return [FadeIn(lace.outlines, run_time=0.5)] if len(lace.outlines) else []


class _WeaveGallery(_WhiteScene):
    """Shared drawing for the showcase weaves: title, framing, painter order."""

    entry: GalleryEntry

    def construct(self):
        lace = self.entry.build()
        print(f"{self.entry.key} diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text(self.entry.title, font_size=28, color=BLACK).to_edge(UP))
        if self.entry.scale != 1.0:
            lace.scale(self.entry.scale)
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), *_outline_animations(lace), run_time=self.entry.run_time)
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


class RibbonGallery(_WhiteScene):
    """The three backends side by side for the same two strands.

    White paper rather than the default black: the ribbon channel paints each
    strand's fill and a hairline border, and only against the page does the border
    read as an edge. Each panel carries the mechanism it uses, because the three
    are supposed to *agree* on the weave and differ only in how they get there.
    """

    def construct(self):
        self.add(
            Text("同一份交叉与上下关系，三个绘制通道", font_size=24, color=BLACK).to_edge(UP)
        )
        trio = build_backend_trio()
        # The laces are arranged on their own and not scaled: their geometry is identical,
        # so they land congruent and the three weaves can be compared position by position.
        # ``Mobject.scale()`` leaves stroke widths alone, so scaling here would fatten the
        # stroke panel's strands (whose width *is* a stroke) while the ribbon bands shrank —
        # the panels would no longer be the same input. Captions are attached afterwards,
        # because a wider caption must not push its panel sideways either.
        laces = VGroup(*[lace.shift(DOWN * 0.2) for _, lace in trio])
        laces.arrange(RIGHT, buff=1.0)
        captions = VGroup()
        for (label, lace), arranged in zip(trio, laces, strict=True):
            print(label, "diagnostics:", [diagnostic.code for diagnostic in lace.diagnostics])
            captions.add(VGroup(
                Text(label, font_size=20, color=BLACK),
                Text(CHANNEL_CAPTIONS[label], font_size=14, color=GREY_B),
            ).arrange(DOWN, buff=0.08).next_to(arranged, DOWN, buff=0.3))
        animations: list[Animation] = []
        for lace in laces:
            animations.append(Create(lace.ribbons))
            animations.extend(_outline_animations(lace))
        self.play(*animations, run_time=1.0)
        self.play(FadeIn(captions), run_time=0.4)
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
    """Sine curve crossing a straight line — alternating weave."""

    entry = GalleryEntry(
        key="sine_line", title="正弦曲线与直线",
        blurb="正弦曲线与水平直线反复相交，逐次上下交替；曲线两端正好压在直线上，"
              "会被如实报为端点接触而不是硬当成交叉。",
        tags=("交替模式", "参数曲线"), build=build_sine_line, scale=0.8,
    )


class TrefoilGallery(_WeaveGallery):
    """Three overlapping circles forming a trefoil-like knot pattern."""

    entry = GalleryEntry(
        key="trefoil", title="三叶结",
        blurb="三个相互交叠的圆构成三叶结拓扑，六处交叉点交替编织。",
        tags=("交替模式", "3 路径"), build=build_trefoil, scale=0.85,
    )


class StarGallery(_WeaveGallery):
    """Five-pointed star (self-intersecting closed polygon)."""

    entry = GalleryEntry(
        key="star", title="五角星",
        blurb="真正的五角星（{5/2}）：一条闭合路径自交五次。自交把路径切成分段，"
              "沿路径数下去是 10 遍（偶数），所以严格交替仍然可解：每一遍与上一遍相反，"
              "五个自交点都拿到确定的上下关系，不需要退化。两遍各属于不同分段，"
              "交叉处由偏移带在局部求交得到的切口决定上下，与跨路径交叉同一套处理。",
        tags=("交替模式", "自相交", "偏移带求交切口"), build=build_star,
    )


class SpiralGallery(_WeaveGallery):
    """Archimedean spiral crossing a horizontal line — multi-turn weave."""

    entry = GalleryEntry(
        key="spiral", title="螺旋与直线",
        blurb="阿基米德螺线绕数圈反复穿过水平线，交叉沿半径一次次向外推进。"
              "严格交替在这个输入上无法全程成立，引擎的默认策略只在必需的两处放宽并逐条标记"
              "（TOPOLOGY-ALTERNATION-RELAXED），其余交叉仍严格交替——"
              "也就是「能交替的都交替」。",
        tags=("交替模式", "少量放宽", "参数曲线"), build=build_spiral, scale=0.8, run_time=1.8,
    )


class GridGallery(_WeaveGallery):
    """A 2×2 grid of interlaced circles — multi-path weave."""

    entry = GalleryEntry(
        key="grid", title="四圆格栅",
        blurb="2×2 排列的四个圆两两相交，相邻的每一对都形成两处交叉，"
              "对角方向互不接触；每个圆上的交叉逐次上下交替。",
        tags=("交替模式", "4 路径"), build=build_grid, scale=0.8, run_time=2.0,
    )


class CrossGallery(_WeaveGallery):
    """Three horizontal lines and one vertical line — four-way intersection."""

    entry = GalleryEntry(
        key="cross", title="十字格栅",
        blurb="三条水平线与一条垂直线交叉，构成四路交叉节点；"
              "垂直线穿过三次，逐次上下交替（上—下—上），不会连着两次同侧。",
        tags=("交替模式", "4 路径"), build=build_cross,
    )


class InfinityGallery(_WeaveGallery):
    """Lemniscate (infinity) curve crossing a horizontal line."""

    entry = GalleryEntry(
        key="infinity", title="双纽线与直线",
        blurb="双纽线（∞ 形）在中点穿过水平线；难点在于曲线在那里同时自交，"
              "与直线的交点落在同一点上（共点交叉）。自交按偏移带局部求交切口编织，"
              "共点这一处会照例给出 REGION-COINCIDENT-CROSSINGS 警告；"
              "严格交替会让共点的两个交叉互相反向扣除、面积核算失衡"
              "（REGION-AREA-MISMATCH），因此这里声明自由模式。",
        tags=("自由模式", "共点交叉", "自交切口"), build=build_infinity, scale=0.8,
    )


class ChainGallery(_WeaveGallery):
    """Three interlocked circles — chain-link pattern."""

    entry = GalleryEntry(
        key="chain", title="链条",
        blurb="三个交错排列的圆模拟链环连接，每对相邻圆交叉编织；"
              "中间那个圆上的四处交叉逐次上下交替。",
        tags=("交替模式", "3 路径"), build=build_chain, scale=0.8, run_time=1.8,
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
