"""Style gallery: palettes, frames, cut-end treatments and density simplification.

Run:

    manim -pql examples/scene_style.py PaletteGallery
    manim -pql examples/scene_style.py BorderGallery
    manim -pql examples/scene_style.py CutEndGallery
    manim -pql examples/scene_style.py DensityGallery

Every scene here is still the same two-channel weave — the style layer only
changes colours, the frame and which slivers are drawn. ``DensityGallery`` is the
one scene whose *geometry* differs, and it prints the ``RENDER-DENSITY-SIMPLIFIED``
diagnostic in the corner so the simplification is never hidden.
"""

import numpy as np
from manim import *  # noqa: F403

from manim_lace import Lace
from manim_lace.style import BorderSpec, CapTreatment, DensityPolicy


class _PaperScene(Scene):
    """A warm off-white stage, so the palettes' own paper colours read clearly."""

    def setup(self) -> None:
        self.camera.background_color = "#F2EFE6"


def _weave_source() -> VGroup:
    """A closed curve crossed by two straight strands."""
    return VGroup(
        Circle(radius=0.85),
        Line(LEFT * 1.5 + UP * 0.25, RIGHT * 1.5 + UP * 0.25),
        Line(LEFT * 1.5 + DOWN * 0.4, RIGHT * 1.5 + DOWN * 0.4),
    )


def _dense_source() -> VGroup:
    """The dense window only: one strand crossed eight times in a narrow x range."""
    corners = np.array([
        [x, y, 0.0]
        for x, y in (
            (0.35, -0.4), (0.35, 0.4), (0.5, -0.4), (0.5, 0.4), (0.65, -0.4),
            (0.65, 0.4), (0.8, -0.4), (0.8, 0.4), (0.95, -0.4),
        )
    ])
    return VGroup(
        Line(np.array([0.25, 0.0, 0.0]), np.array([1.05, 0.0, 0.0])),
        VMobject().set_points_as_corners(corners),  # noqa: F405
    )


class PaletteGallery(_PaperScene):
    """The same weave in four seasonal palettes, each on its own paper."""

    def construct(self):
        names = ("haru", "natsu", "aki", "fuyu")
        panels = VGroup()  # noqa: F405
        for name in names:
            lace = Lace(
                _weave_source(),
                offset=0.075,
                palette=name,
                paper=True,
                border=BorderSpec(margin=0.12, thickness=0.02, corner="round", radius=0.08),
                stroke_width_px=3.0,
                pixel_height=1080,
                frame_height=6.0,
            )
            palette = lace.style.palette
            caption = Text(  # noqa: F405
                f"{palette.label}  {palette.name}", font_size=22, color=BLACK  # noqa: F405
            ).next_to(lace, DOWN, buff=0.18)
            panels.add(VGroup(lace, caption))  # noqa: F405
        panels.arrange(RIGHT, buff=0.35).scale(0.62)
        self.add(panels)  # noqa: F405
        self.wait()


class BorderGallery(_PaperScene):
    """Four frame designs around one weave."""

    def construct(self):
        specs = (
            ("square frame", BorderSpec(margin=0.18, thickness=0.02, corner="square")),
            (
                "rounded double frame",
                BorderSpec(margin=0.14, thickness=0.018, corner="round", radius=0.1, bands=2, gap=0.05),
            ),
            ("bevel frame", BorderSpec(margin=0.18, thickness=0.02, corner="bevel", radius=0.12)),
            (
                "inset frame",
                BorderSpec(margin=0.3, thickness=0.015, corner="round", radius=0.14, inset=0.1),
            ),
        )
        panels = VGroup()  # noqa: F405
        for label, spec in specs:
            lace = Lace(
                _weave_source(),
                offset=0.06,
                palette="wabi",
                paper=True,
                border=spec,
                stroke_width_px=2.5,
                pixel_height=1080,
                frame_height=6.0,
            )
            panels.add(  # noqa: F405
                VGroup(  # noqa: F405
                    lace,
                    Text(label, font_size=20, color=BLACK).next_to(lace, DOWN, buff=0.15),  # noqa: F405
                )
            )
        panels.arrange(RIGHT, buff=0.3).scale(0.62)
        self.add(panels)  # noqa: F405
        self.wait()


class CutEndGallery(_PaperScene):
    """The same crossing with butt caps, a cover allowance, and round caps.

    The third panel also draws the real paint outline of every piece
    (``stroke_piece_outline``), so the end treatment is verified geometry instead
    of an assumption about how a stroked line is painted.
    """

    def construct(self):
        offset = 0.09
        variants = (
            (CapTreatment(style="butt", cover_allowance=0.0), None),
            (CapTreatment(style="butt", cover_allowance=0.03), None),
            (CapTreatment(style="round", samples=16), "outline"),
        )
        panels = VGroup()  # noqa: F405
        for treatment, extra in variants:
            lace = Lace(
                _weave_source(),
                offset=offset,
                palette="matsuri",
                cap_style=treatment.style,
                cover_allowance=treatment.cover_allowance,
                stroke_width_px=4.0,
                pixel_height=1080,
                frame_height=6.0,
            )
            panel = VGroup(lace)  # noqa: F405
            if extra == "outline":
                paper = VGroup()  # noqa: F405
                for piece in lace.result.pieces:
                    outline = treatment.outline(piece, offset)
                    mob = VMobject()  # noqa: F405
                    mob.set_points_as_corners(
                        np.column_stack((outline.outer[:, :2], np.zeros(len(outline.outer))))
                    )
                    mob.set_fill(lace.style_plan.color_for(piece.piece_id), opacity=0.16)
                    mob.set_stroke(width=0)
                    paper.add(mob)
                panel.add(paper)
            caption = Text(  # noqa: F405
                f"{treatment.style} · 余量 {treatment.cover_allowance:g}", font_size=18, color=BLACK  # noqa: F405
            ).next_to(panel, DOWN, buff=0.15)
            panels.add(VGroup(panel, caption))  # noqa: F405
        panels.arrange(RIGHT, buff=0.4).scale(0.6)
        self.add(panels)  # noqa: F405
        self.wait()


class DensityGallery(_PaperScene):
    """The same dense weave: what would be drawn, and what the policy omits.

    The left panel draws every visible piece and marks the ones the policy would
    hide in red (taken from ``DensitySimplification.dropped_ids``, so the marks are
    the real decision); the right panel draws what the policy actually keeps. Three
    0.05-long slivers inside the cluster is a small difference, which is exactly why
    it is marked instead of being left to the eye.
    """

    def construct(self):
        offset = 0.05
        # The density defaults are relative to the *drawing's* extent, so a pattern
        # this short needs an explicit world-space cluster radius to mean anything
        # (see ``DensityPolicy``); here the crossings sit 0.15 apart.
        policy = DensityPolicy(cluster_radius=0.2)
        plain = Lace(
            _dense_source(), offset=offset, palette="ayame",
            stroke_width_px=4.0, pixel_height=1080, frame_height=6.0,
        )
        simplified = Lace(
            _dense_source(), offset=offset, palette="ayame",
            density_policy=policy, stroke_width_px=4.0,
            pixel_height=1080, frame_height=6.0,
        )
        dropped = set(simplified.density.dropped_ids)
        marked = VGroup(*[  # noqa: F405
            VMobject()  # noqa: F405
            .set_points_as_corners(
                np.column_stack((piece.points, np.zeros(len(piece.points))))
            )
            .set_stroke(RED, width=5.0, opacity=0.9)  # noqa: F405
            for piece in plain.result.pieces
            if piece.piece_id in dropped
        ])
        note = Text(  # noqa: F405
            f"RENDER-DENSITY-SIMPLIFIED: 省略 {simplified.density.dropped_count} 个极短片段"
            f"（红色 = 将被省略，阈值 {simplified.density.threshold:.3f}）",
            font_size=18,
            color=BLACK,  # noqa: F405
        )
        left = VGroup(plain, marked).scale(3.0)  # noqa: F405
        right = simplified.scale(3.0)
        panels = VGroup(  # noqa: F405
            VGroup(  # noqa: F405
                left, Text("全部片段（红=将被省略）", font_size=20, color=BLACK).next_to(left, DOWN, buff=0.15)  # noqa: F405
            ),
            VGroup(  # noqa: F405
                right, Text("密度简化后", font_size=20, color=BLACK).next_to(right, DOWN, buff=0.15),  # noqa: F405
            ),
        ).arrange(RIGHT, buff=1.0)
        note.next_to(panels, DOWN, buff=0.45)
        self.add(panels, note)  # noqa: F405
        self.wait()
