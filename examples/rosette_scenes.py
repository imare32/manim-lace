"""``StarRosette`` 的示例场景与可视化脚本。

用法(在仓库根目录执行)::

    uv run python examples/rosette_scenes.py                    # 渲染全部场景
    uv run python examples/rosette_scenes.py StarRosetteGallery # 只渲染一个场景
    uv run python examples/rosette_scenes.py -q low_quality

输出默认写入 ``media/`` 目录。
"""

from __future__ import annotations

import argparse

from manim import (
    BLACK,
    BLUE,
    DOWN,
    LEFT,
    LIGHT_PINK,
    ORANGE,
    PINK,
    RIGHT,
    TEAL,
    UP,
    YELLOW,
    Create,
    Scene,
    Text,
    VGroup,
    linear,
    tempconfig,
)

from manim_lace import STAR_TYPE_VALUES, Lace, StarRosette

DEFAULT_CONFIG = {"preview": False, "verbosity": "WARNING"}


class TestStarRosetteScene(Scene):
    """同一花型下不同 ``n`` / ``level`` 的对比。"""

    def construct(self):
        title = Text("StarRosette Algorithm Test", font_size=36)
        title.to_edge(UP)
        self.add(title)

        rosette1 = StarRosette(7, 0, "CA", stroke_color=TEAL, fill_color=BLUE, fill_opacity=0.5)
        rosette1.shift(LEFT * 5)
        label1 = Text("n=7, level=0", font_size=24).next_to(rosette1, DOWN)

        rosette2 = StarRosette(10, 1, "CA", stroke_color=PINK, fill_color=LIGHT_PINK, fill_opacity=0.5)
        rosette2.shift(LEFT * 1).scale(0.6)
        label2 = Text("n=10, level=1", font_size=24).next_to(rosette2, DOWN)

        rosette3 = StarRosette(10, 3, "CA", stroke_color=ORANGE, fill_color=YELLOW, fill_opacity=0.5)
        rosette3.scale(0.6).shift(RIGHT * 3.5)
        label3 = Text("n=10, level=3", font_size=24).next_to(rosette3, DOWN)

        self.add(label1, label2, label3)
        self.play(
            Create(rosette1),
            Create(rosette2),
            Create(rosette3),
            run_time=5,
            rate_func=linear,
        )
        self.wait(1)


class StarRosetteGallery(Scene):
    """遍历全部 ``star_type``, 展示花型之间的差异。"""

    def construct(self):
        title = Text("Star types", font_size=36).to_edge(UP)
        self.add(title)

        group = VGroup()
        for star_type in STAR_TYPE_VALUES:
            rosette = StarRosette(9, 2, star_type, fill_opacity=0.4)
            rosette.scale(0.25)
            label = Text(star_type, font_size=20).next_to(rosette, DOWN)
            group.add(VGroup(rosette, label))
        group.arrange(RIGHT, buff=0.35).shift(DOWN * 0.3)

        self.play(Create(group), run_time=3)
        self.wait(1)


class StarRosetteLaceScene(Scene):
    """把玫瑰线交给 Lace 编织, 展示组合用法。"""

    def construct(self):
        rosette = StarRosette(12, 2, "PA")
        lace = Lace(
            rosette,
            offset=0.08,
            stroke_color=BLACK,
            stroke_width=1,
            hole_group_method="by_distance",
        )
        self.play(Create(lace), run_time=4)
        self.wait(1)


SCENES: dict[str, type[Scene]] = {
    "TestStarRosetteScene": TestStarRosetteScene,
    "StarRosetteGallery": StarRosetteGallery,
    "StarRosetteLaceScene": StarRosetteLaceScene,
}


def render(scene_names: list[str], quality: str = "medium_quality", preview: bool = False) -> None:
    """渲染指定的场景。"""
    for name in scene_names:
        config = {"quality": quality, **DEFAULT_CONFIG, "preview": preview}
        print(f"--- rendering {name} ({quality}) ---")
        with tempconfig(config):
            SCENES[name]().render()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染 StarRosette 的示例场景")
    parser.add_argument("scene", nargs="*", choices=list(SCENES), default=[], help="要渲染的场景名, 缺省表示全部")
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
