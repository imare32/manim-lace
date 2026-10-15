"""Run: manim -pql examples/scene_weave.py WeaveDemo"""

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
