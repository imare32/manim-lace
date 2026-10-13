"""``Lace`` 的示例场景与可视化脚本。

用法(在仓库根目录执行, 内部通过 ``uv run`` 保证 ``manim_lace`` 可导入)::

    uv run python examples/lace_scenes.py                 # 渲染全部场景
    uv run python examples/lace_scenes.py TestLaceScene0  # 只渲染一个场景
    uv run python examples/lace_scenes.py -q low_quality -p

输出默认写入 ``media/`` 目录。
"""

from __future__ import annotations

import argparse

import numpy as np
from manim import (
    BLACK,
    BLUE,
    DOWN,
    RIGHT,
    TAU,
    WHITE,
    Dot,
    NumberPlane,
    ParametricFunction,
    Rectangle,
    Scene,
    Star,
    Text,
    VGroup,
    tempconfig,
)

from manim_lace import Lace, StarRosette

DEFAULT_CONFIG = {"preview": False, "verbosity": "WARNING", "background_color": WHITE}


class TestLaceScene0(Scene):
    """10 点 2 阶玫瑰线。"""

    def construct(self):
        star = StarRosette(10, 2)
        lace = Lace(star, offset=0.1, stroke_color=BLACK, stroke_width=1)
        self.add(lace)


class TestLaceScene1(Scene):
    """10 点 3 阶玫瑰线, 内部连接更复杂。"""

    def construct(self):
        star = StarRosette(10, 3)
        lace = Lace(star, offset=0.1, stroke_color=BLACK, stroke_width=1)
        self.add(lace)


class TestLaceScene2(Scene):
    """坐标网格: 展示按距离分组着色。"""

    def construct(self):
        grid = NumberPlane().background_lines
        lace = Lace(
            grid,
            offset=0.1,
            stroke_color=BLACK,
            stroke_width=1,
            hole_opacity=0.5,
            hole_group_method="by_distance",
        )
        self.add(lace)


class TestLaceScene3(Scene):
    """矩形与星形叠加: 多条闭合路径混合。"""

    def construct(self):
        obj = VGroup(Rectangle(width=5, height=5), Star(outer_radius=4))
        lace = Lace(obj, offset=0.1, stroke_color=BLACK, stroke_width=1)
        self.add(lace)


class TestLaceScene4(Scene):
    """李萨如曲线: 开放路径, 并标出锚点便于调试。"""

    @staticmethod
    def func(t: float):
        return np.sin(2 * t), np.sin(3 * t), 0

    def construct(self):
        curve = ParametricFunction(self.func, t_range=(0, TAU, np.pi / 20), use_smoothing=False).scale(3)
        curve.shift(DOWN * 0.5)
        curve.set_color(BLACK)
        curve.set_stroke(width=1)

        lace = Lace(curve, offset=0.1, stroke_color=BLACK, stroke_width=1)
        self.add(lace)
        for point in curve.get_anchors():
            self.add(Dot(point, color=BLUE))


class TestLaceScene5(Scene):
    """把编号标注到画面上, 便于对比不同偏移宽度。"""

    def construct(self):
        group = VGroup()
        for index, offset in enumerate((0.05, 0.1, 0.2)):
            rosette = StarRosette(12, 2).scale(0.28)
            plain = Lace(rosette, offset=offset, stroke_color=BLACK, stroke_width=1)
            label = Text(f"offset={offset}", font_size=20).next_to(plain, DOWN)
            group.add(VGroup(plain, label).shift((index - 1) * RIGHT * 4))
        self.add(group)


SCENES: dict[str, type[Scene]] = {
    "TestLaceScene0": TestLaceScene0,
    "TestLaceScene1": TestLaceScene1,
    "TestLaceScene2": TestLaceScene2,
    "TestLaceScene3": TestLaceScene3,
    "TestLaceScene4": TestLaceScene4,
    "TestLaceScene5": TestLaceScene5,
}


def render(scene_names: list[str], quality: str = "medium_quality", preview: bool = False) -> None:
    """渲染指定的场景。"""
    for name in scene_names:
        config = {"quality": quality, **DEFAULT_CONFIG, "preview": preview}
        print(f"--- rendering {name} ({quality}) ---")
        with tempconfig(config):
            SCENES[name]().render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染 manim_lace 的示例场景")
    parser.add_argument(
        "scene",
        nargs="*",
        choices=list(SCENES),
        default=[],
        help="要渲染的场景名, 缺省表示全部",
    )
    parser.add_argument(
        "-q",
        "--quality",
        default="medium_quality",
        choices=["low_quality", "medium_quality", "high_quality", "fourk_quality"],
        help="渲染质量",
    )
    parser.add_argument("-p", "--preview", action="store_true", help="渲染完成后自动播放")
    args = parser.parse_args(argv)

    render(args.scene or list(SCENES), args.quality, args.preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
