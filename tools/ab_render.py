"""A/B 渲染: 同一份场景源码分别驱动"基线实现"与"当前实现", 输出可直接比 md5。

这是仓库**唯一的硬回归证据**(见 `PROGRESS.md` §0.3): 对正常输入, 任何改动都必须让这 4 个
场景的输出**逐字节一致**。

用法::

    # 1) 准备基线快照(一次性; 快照本身不入库, 因为它是"另一份完整源码")
    git archive <基线 ref> | tar -x -C media/_review/head_tree

    # 2) 两边各渲一遍
    uv run python tools/ab_render.py --root media/_review/head_tree --out media/_review/ab_old
    uv run python tools/ab_render.py --root .                        --out media/_review/ab_new

    # 3) 比 md5(任选, PowerShell)
    Get-ChildItem media/_review/ab_old -Recurse -Filter *.png | ForEach-Object {
        (Get-FileHash $_.FullName -Algorithm MD5).Hash + " " + $_.Name }

配色固定(不用随机色卡), 因此两边输出可以直接逐像素对比。

注意: `ABScene0` / `ABScene1` 用**可选模块** `manim_lace.rosette` 生成输入。若哪天把玫瑰线
物理拆成独立包, 这两个场景要换成非玫瑰线的固定输入(见 `AGENTS.md` 的抽离清单), 否则基线
脚本会跟着一起失效。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="A/B 渲染蕾丝展示图")
parser.add_argument("--root", default=".", help="manim_lace 包所在目录(会被放到 sys.path 最前)")
parser.add_argument("--out", required=True, help="输出目录(作为 media_dir)")
args, _unknown = parser.parse_known_args()

sys.path.insert(0, str(Path(args.root).resolve()))

from manim import (  # noqa: E402
    BLACK,
    BLUE,
    GREEN,
    RED,
    WHITE,
    NumberPlane,
    Rectangle,
    Scene,
    Star,
    VGroup,
    tempconfig,
)

import manim_lace  # noqa: E402
from manim_lace import Lace  # noqa: E402

SWATCH = (BLUE, GREEN, RED)
QUALITY = {"0": "medium_quality", "1": "medium_quality", "2": "low_quality", "3": "low_quality"}


def _star_rosette(*args, **kwargs):
    """延迟取用可选模块 rosette(拆走时只需要改这一个函数)。"""
    from manim_lace import StarRosette

    return StarRosette(*args, **kwargs)


class ABScene0(Scene):
    """StarRosette(10, 2) 蕾丝。"""

    def construct(self):
        star = _star_rosette(10, 2).scale(1)
        self.add(Lace(star, offset=0.1, stroke_color=BLACK, stroke_width=1, hole_swatch=SWATCH))


class ABScene1(Scene):
    """StarRosette(10, 3) 蕾丝。"""

    def construct(self):
        star = _star_rosette(10, 3).scale(1)
        self.add(Lace(star, offset=0.1, stroke_color=BLACK, stroke_width=1, hole_swatch=SWATCH))


class ABScene2(Scene):
    """坐标网格(开放式多条线), 按距离分组着色。"""

    def construct(self):
        grid = NumberPlane().background_lines
        self.add(
            Lace(
                grid,
                offset=0.1,
                stroke_color=BLACK,
                stroke_width=1,
                hole_opacity=0.5,
                hole_group_method="by_distance",
                hole_swatch=SWATCH,
            ),
        )


class ABScene3(Scene):
    """矩形 + 六角星叠加。"""

    def construct(self):
        obj = VGroup(Rectangle(width=5, height=5), Star(outer_radius=4))
        self.add(Lace(obj, offset=0.1, stroke_color=BLACK, stroke_width=1, hole_swatch=SWATCH))


SCENES = (ABScene0, ABScene1, ABScene2, ABScene3)


def main() -> int:
    print(f"manim_lace from: {manim_lace.__file__}")
    for scene_cls in SCENES:
        key = scene_cls.__name__[-1]
        config = {
            "quality": QUALITY[key],
            "preview": False,
            "verbosity": "ERROR",
            "background_color": WHITE,
            "save_last_frame": True,
            "format": "png",
            "media_dir": args.out,
            # 指定输出名, 避免 manim 追加 "_ManimCE_v<版本>" 后缀
            "output_file": scene_cls.__name__,
        }
        print(f"--- rendering {scene_cls.__name__} ({QUALITY[key]}) -> {args.out} ---")
        with tempconfig(config):
            scene_cls().render()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
