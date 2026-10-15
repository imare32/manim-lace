"""Run: manim -pql examples/scene_weave.py WeaveDemo SamplingTraceDemo"""

import numpy as np
from manim import *

from manim_lace import Lace


class WeaveDemo(Scene):
    def construct(self):
        source = VGroup(
            ParametricFunction(
                lambda t: np.array([t, 0.9 * np.sin(1.5 * t), 0]),
                t_range=[-3, 3],
                color=GREY_B,
            ),
            Line(LEFT * 3 + UP * 1.1, RIGHT * 3 + DOWN * 1.1, color=GREY_B),
        )
        lace = Lace(source, offset=0.12, render="stroke", weave_mode="free", stroke_color=TEAL)
        self.play(lace.build_animation(mode="algorithm", show_sampling=True))
        self.wait()


class SamplingTraceDemo(Scene):
    """The same animation for a curve the engine sampled itself.

    ``mode="algorithm"`` also overlays the fine-grained read-outs of the trace
    (``sampling.subdivision`` for the adaptive sampling, ``region.face_walk`` for the
    ribbon traversal), so the numbers on screen are the recursion that actually ran.
    """

    def construct(self):
        lace = Lace.from_parametric(
            lambda t: (np.cos(t), 0.6 * np.sin(2.0 * t)),
            (0.0, 2.0 * np.pi),
            offset=0.1,
            max_step=0.4,
            max_error=1e-4,
            stroke_width_px=3.0,
        )
        self.play(lace.build_animation(mode="algorithm", show_sampling=True))
        self.wait()
