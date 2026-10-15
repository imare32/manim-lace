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

``CapStyleGallery`` renders the same two-strand weave three times to show how the end
caps change the cut: ``round`` and ``square`` paint half the ribbon width past the
centerline endpoint, so the gap widens by ``offset`` (reported as
``RENDER-CAP-EXTENSION``). ``DrawOrderGallery`` creates the pieces in the renderer's
painter order, which is computed from the over/under assignments. ``RibbonGallery``
shows the area backend next to the stroke backend for the same input; it needs the
optional ``shapely`` extra.

The remaining classes are all **ribbon-backend** weaves on a white background with
black strokes — the canonical "lace on paper" look.
"""

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


class _WhiteScene(Scene):
    """Scene with a white background — use as the base for ribbon galleries."""

    def setup(self) -> None:
        self.camera.background_color = WHITE


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
        source = _two_strand_source()
        variants = (
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
        panels = VGroup()
        for label, lace in variants:
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


class CircleLineGallery(_WhiteScene):
    """Circle + straight line: the simplest two-strand weave."""

    def construct(self):
        source = VGroup(
            Circle(radius=1.2, color=GREY_B),
            Line(LEFT * 1.8, RIGHT * 1.8, color=GREY_B),
        )
        lace = Lace(source, offset=0.18, **_RIBBON_STYLE)
        print("CircleLine diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("圆与直线", font_size=28).to_edge(UP))
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.2)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class SineLineGallery(_WhiteScene):
    """Sine curve crossing a straight line — free-mode weave.

    Frequency chosen so the sine completes ~3 full periods across the range,
    giving 6 crossings with the horizontal line (y=0).
    """

    def construct(self):
        source = VGroup(
            ParametricFunction(
                lambda t: np.array([t, 0.6 * np.sin(np.pi * t), 0]),
                t_range=[-3, 3],
                color=GREY_B,
            ),
            Line(LEFT * 3, RIGHT * 3, color=GREY_B),
        )
        lace = Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)
        print("SineLine diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("正弦曲线与直线", font_size=28).to_edge(UP))
        lace.scale(0.8).shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.5)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class TrefoilGallery(_WhiteScene):
    """Three overlapping circles forming a trefoil-like knot pattern."""

    def construct(self):
        source = VGroup()
        for angle in (0, 2 * PI / 3, 4 * PI / 3):
            center = 0.7 * np.array([np.cos(angle), np.sin(angle), 0])
            source.add(Circle(radius=1.0, color=GREY_B).move_to(center))
        lace = Lace(source, offset=0.14, weave_mode="free", **_RIBBON_STYLE)
        print("Trefoil diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("三叶结", font_size=28).to_edge(UP))
        lace.scale(0.85).shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.5)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class StarGallery(_WhiteScene):
    """Five-pointed star (self-intersecting closed polygon)."""

    def construct(self):
        angles = [PI / 2 + i * 2 * PI / 5 for i in range(5)]
        outer = [np.array([1.4 * np.cos(a), 1.4 * np.sin(a), 0]) for a in angles]
        inner = [
            np.array([0.55 * np.cos(a + PI / 5), 0.55 * np.sin(a + PI / 5), 0])
            for a in angles
        ]
        verts = []
        for i in range(5):
            verts.append(outer[i])
            verts.append(inner[i])
        star = VMobject()
        star.set_points_as_corners(np.array(verts + [verts[0]]))
        star.set_stroke(GREY_B, width=2)
        source = VGroup(star)
        lace = Lace(source, offset=0.12, **_RIBBON_STYLE)
        print("Star diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("五角星", font_size=28).to_edge(UP))
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.5)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class SpiralGallery(_WhiteScene):
    """Archimedean spiral crossing a horizontal line — multi-turn weave.

    Angular range covers ~3.5 full turns so the spiral crosses the horizontal
    line ~7 times (twice per turn plus the initial crossing) while staying
    inside the camera frame.
    """

    def construct(self):
        spiral = ParametricFunction(
            lambda t: np.array([
                0.18 * t * np.cos(t),
                0.18 * t * np.sin(t),
                0,
            ]),
            t_range=[0.5, 7 * PI],
            color=GREY_B,
        )
        line = Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B)
        source = VGroup(spiral, line)
        lace = Lace(source, offset=0.10, weave_mode="free", **_RIBBON_STYLE)
        print("Spiral diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("螺旋与直线", font_size=28).to_edge(UP))
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.8)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class GridGallery(_WhiteScene):
    """A 2×2 grid of interlaced circles — multi-path weave."""

    def construct(self):
        source = VGroup()
        positions = [UP + LEFT, UP + RIGHT, DOWN + LEFT, DOWN + RIGHT]
        for pos in positions:
            source.add(Circle(radius=0.9, color=GREY_B).move_to(pos))
        lace = Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)
        print("Grid diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("四圆格栅", font_size=28).to_edge(UP))
        lace.scale(0.8).shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=2.0)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class CrossGallery(_WhiteScene):
    """Two perpendicular line pairs forming a cross — four-way intersection."""

    def construct(self):
        source = VGroup(
            Line(LEFT * 2.5, RIGHT * 2.5, color=GREY_B),
            Line(UP * 2.5, DOWN * 2.5, color=GREY_B),
            Line(LEFT * 2.5 + UP * 0.8, RIGHT * 2.5 + UP * 0.8, color=GREY_B),
            Line(LEFT * 2.5 + DOWN * 0.8, RIGHT * 2.5 + DOWN * 0.8, color=GREY_B),
        )
        lace = Lace(source, offset=0.15, weave_mode="free", **_RIBBON_STYLE)
        print("Cross diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("十字格栅", font_size=28).to_edge(UP))
        lace.shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.5)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class InfinityGallery(_WhiteScene):
    """Lemniscate (infinity) curve crossing a horizontal line."""

    def construct(self):
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
        source = VGroup(lemniscate, line)
        lace = Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)
        print("Infinity diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("双纽线与直线", font_size=28).to_edge(UP))
        lace.scale(0.8).shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.5)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()


class ChainGallery(_WhiteScene):
    """Three interlocked circles — chain-link pattern."""

    def construct(self):
        source = VGroup()
        for i, x in enumerate((-1.3, 0, 1.3)):
            source.add(Circle(radius=0.9, color=GREY_B).move_to(RIGHT * x + UP * 0.3 * (i % 2)))
        lace = Lace(source, offset=0.13, weave_mode="free", **_RIBBON_STYLE)
        print("Chain diagnostics:", [d.code for d in lace.diagnostics])
        self.add(Text("链条", font_size=28).to_edge(UP))
        lace.scale(0.8).shift(DOWN * 0.2)
        self.play(Create(lace.ribbons), run_time=1.8)
        self.play(FadeIn(lace.holes), run_time=0.5)
        self.wait()
