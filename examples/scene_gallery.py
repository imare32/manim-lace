"""Renderer gallery: stroke caps, draw order and area-based ribbons.

Run:

    manim -pql examples/scene_gallery.py CapStyleGallery
    manim -pql examples/scene_gallery.py DrawOrderGallery
    manim -pql examples/scene_gallery.py RibbonGallery

``CapStyleGallery`` renders the same two-strand weave three times to show how the end
caps change the cut: ``round`` and ``square`` paint half the ribbon width past the
centerline endpoint, so the gap widens by ``offset`` (reported as
``RENDER-CAP-EXTENSION``). ``DrawOrderGallery`` creates the pieces in the renderer's
painter order, which is computed from the over/under assignments. ``RibbonGallery``
shows the area backend next to the stroke backend for the same input; it needs the
optional ``shapely`` extra.
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
