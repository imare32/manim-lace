"""批量导出 ``StarRosette`` 各种参数组合的预览图, 形成一份"图形大全"。

用法::

    uv run python examples/rosette_gallery.py                        # 默认导出全部组合
    uv run python examples/rosette_gallery.py --star-type PA CA --n 5 7 9 --level 0 1 2
    uv run python examples/rosette_gallery.py --overlay petal --size 1440
    uv run python examples/rosette_gallery.py --overlay none         # 只画图形本身

每张图由三部分组成:

* **图形**: 该 ``(花型, n, level)`` 的花瓣轮廓, 统一缩放到画幅的 84%(便于横向对比),
  标签还会给出它的**真实最大半径** ``r``;
* **骨架** (``--overlay``): ``kernel``=原始核骨架 或 ``petal``=花瓣单元, 实线 + 顶点圆点,
  与图形使用同一套平移/缩放, 因此能直接看出"整张图是怎么由它长出来的";
* 很淡的**水平参考轴**: 即 kernel / petal 的对称轴(单位圆上的起点与 x 轴上的尖端都在其中)。

.. important::
    Manim 的 ``stroke_width`` 是**相对画幅**定义的(逻辑宽度 ≈ ``stroke_width × 0.01`` 个
    单位), 直接写死一个数在大画幅/低分辨率下会细成发丝。这里所有线宽与圆点半径都按
    "输出图片上的像素"定义, 再用 :func:`px_to_stroke_width` / :func:`px_to_units` 换算,
    换分辨率时粗细观感保持一致。

图片默认写入 ``media/rosette_gallery/``(该目录已被 ``.gitignore`` 忽略), 文件名形如
``PA_n09_l2.png``; 同时在输出目录生成 ``index.html`` —— 默认是一个**可按键筛选**的浏览页
(按花型 / N / 等级过滤, 点缩略图放大后用 ←/→ 连续翻看), 模板见 ``examples/gallery_page.html``;
``--index simple`` 可换回静态网格, ``--index none`` 则不生成。
"""

from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from manim import (
    BLACK,
    BLUE,
    DARK_GREY,
    ORIGIN,
    RED,
    WHITE,
    DashedVMobject,
    Dot,
    Line,
    LineJointType,
    Scene,
    Text,
    VGroup,
    VMobject,
    tempconfig,
)

from manim_lace import STAR_TYPE_VALUES, StarRosette
from manim_lace.rosette import cal_kernels, get_petals_by_kernel

#: 默认扫过的花瓣(角)数量。小的 n 逐个列出(图形差异明显); 大的 n 只取几个有代表性的值,
#: 再多对观察算法没有增益。
DEFAULT_N = (4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 20, 36)
#: 默认扫过的阶数。对 ``n <= 18`` 而言 0~12 已覆盖完整可行范围; 更大的 ``n`` 还有更高
#: 的可行阶(偶数为 ``n/2`` 上下, 见 README), 需要时用 ``--level`` 显式指定。
DEFAULT_LEVELS = tuple(range(13))
#: 逻辑坐标系下的画面宽高(正方形), 图形会被缩放至其 84%。
FRAME_SIZE = 9.0
FIGURE_HEIGHT = FRAME_SIZE * 0.84
DEFAULT_OUTPUT = Path("media") / "rosette_gallery"
#: 索引页风格: ``filter`` = 可按键筛选的浏览页(默认), ``simple`` = 静态缩略图网格, ``none`` = 不生成。
DEFAULT_INDEX_STYLE = "filter"
#: 可筛选浏览页的模板(与本脚本同目录)。
BROWSER_TEMPLATE = Path(__file__).with_name("gallery_page.html")

#: 配色: 用 Manim 的基础常量(不带 ``_A``~``_E`` 后缀)。
SHAPE_COLOR = BLUE
OVERLAY_COLOR = RED
AXIS_COLOR = DARK_GREY
#: 线宽 / 圆点半径 / 参考轴(均为**输出图片上的像素**)。
SHAPE_LINE_WIDTH_PX = 3.2
OVERLAY_LINE_WIDTH_PX = 3.4
OVERLAY_DOT_RADIUS_PX = 5.5
AXIS_LINE_WIDTH_PX = 1.0
AXIS_OPACITY = 0.3

#: Manim 中 ``stroke_width=1`` 对应的逻辑宽度(单位: 画幅高度) —— 见 ``Camera.cairo_line_width_multiple``。
MANIM_STROKE_UNIT = 0.01


def px_to_stroke_width(px_width: float, half_frame: float, pixel_size: int) -> float:
    """把"输出图片上的像素宽度"换算成 Manim 的 ``stroke_width``。

    推导: 像素厚度 = ``0.01 × stroke_width × 像素高度 / 画幅高度``, 反解得
    ``stroke_width = 像素宽度 × 画幅高度 / (0.01 × 像素高度)``。
    """
    return px_width * (2 * half_frame) / (MANIM_STROKE_UNIT * pixel_size)


def px_to_units(px_length: float, half_frame: float, pixel_size: int) -> float:
    """把"输出图片上的像素长度"换算成画幅内的逻辑长度(用于圆点半径等几何量)。"""
    return px_length * (2 * half_frame) / pixel_size


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 StarRosette 参数组合预览图")
    parser.add_argument("--n", type=int, nargs="+", default=list(DEFAULT_N), help="花瓣数量列表")
    parser.add_argument("--level", type=int, nargs="+", default=list(DEFAULT_LEVELS), help="阶数列表")
    parser.add_argument(
        "--star-type",
        nargs="+",
        default=list(STAR_TYPE_VALUES),
        choices=list(STAR_TYPE_VALUES),
        help="花型列表",
    )
    parser.add_argument(
        "--overlay",
        choices=["kernel", "petal", "none"],
        default="kernel",
        help="叠加的骨架: kernel=核(实线)+其镜像(虚线, 默认); petal=花瓣轮廓(实线); none=只画图形",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出目录")
    parser.add_argument("--size", type=int, default=720, help="图片边长(像素); 越大越清晰")
    parser.add_argument(
        "--index",
        choices=["filter", "simple", "none"],
        default=DEFAULT_INDEX_STYLE,
        help="index.html 风格: filter=可筛选浏览页(默认); simple=静态网格; none=不生成",
    )
    return parser.parse_args(argv)


def build_overlay(
    kernel: np.ndarray,
    n: int,
    overlay: str,
    anchor: np.ndarray,
    scale: float,
    half_frame: float,
    pixel_size: int,
) -> VGroup:
    """把骨架画成红色实线 + 顶点圆点。

    * ``kernel``: **核**用实线, 它的**镜像**(沿 x 轴翻转)用虚线 —— 线型本身就区分了
      "哪半边是原始核、哪半边是镜像", 两条合起来正好拼出花瓣轮廓;
    * ``petal``: 直接把花瓣轮廓画成一条实线(不闭合)。
    """
    stroke_width = px_to_stroke_width(OVERLAY_LINE_WIDTH_PX, half_frame, pixel_size)
    kernel_points = (np.pad(kernel, ((0, 0), (0, 1))) - anchor) * scale

    if overlay == "petal":
        halves = [(False, (np.pad(get_petals_by_kernel(kernel, n)[0], ((0, 0), (0, 1))) - anchor) * scale)]
    else:
        # kernel[::-1] * (1, -1): 反转后沿 x 轴镜像, 于是从 x 轴上的尖端回到单位圆上的起点
        mirror_points = (np.pad(kernel[::-1] * np.array([1, -1]), ((0, 0), (0, 1))) - anchor) * scale
        halves = [(False, kernel_points), (True, mirror_points)]

    group = VGroup()
    for dashed, points in halves:
        line = VMobject(stroke_width=stroke_width, fill_opacity=0, joint_type=LineJointType.ROUND)
        line.set_points_as_corners(points)
        line.set_stroke(color=OVERLAY_COLOR, opacity=1.0)
        if dashed:
            # 虚线密度按屏幕长度算, 换分辨率/缩放时观感一致
            length = float(np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1).sum())
            num_dashes = max(4, round(length * pixel_size / (2 * half_frame) / 12))
            group.add(DashedVMobject(line, num_dashes=num_dashes))
        else:
            group.add(line)

    # 顶点圆点: 实线与虚线的每个拐点都标出来(镜像与核共用的交点只标一次)
    dot_radius = px_to_units(OVERLAY_DOT_RADIUS_PX, half_frame, pixel_size)
    dot_points: list[np.ndarray] = []
    for _, points in halves:
        for point in points:
            if not any(np.allclose(point, existing) for existing in dot_points):
                dot_points.append(point)
    for point in dot_points:
        group.add(Dot(point, radius=dot_radius, color=OVERLAY_COLOR))
    return group


def build_axis(half_frame: float, pixel_size: int) -> Line:
    """水平参考轴 —— kernel / petal 的对称轴, 画得很淡。"""
    return Line(
        [-half_frame, 0, 0],
        [half_frame, 0, 0],
        color=AXIS_COLOR,
        stroke_width=px_to_stroke_width(AXIS_LINE_WIDTH_PX, half_frame, pixel_size),
        stroke_opacity=AXIS_OPACITY,
    )


def render_combination(
    star_type: str,
    n: int,
    level: int,
    output_dir: Path,
    pixel_size: int,
    overlay: str,
) -> Path:
    """渲染单个参数组合并保存为 PNG, 返回文件路径。"""
    half_frame = FRAME_SIZE / 2
    kernel = cal_kernels(n, level, star_type)[level]

    figure = StarRosette(n, level, star_type)
    radius = float(np.linalg.norm(np.array(figure.get_anchors())[:, :2], axis=1).max())
    # 以图形自身的对称中心为基准平移+缩放: 骨架用同一套变换, 因此两者始终对齐
    anchor = figure.get_center()
    scale = FIGURE_HEIGHT / figure.height
    figure.set_stroke(
        color=SHAPE_COLOR,
        width=px_to_stroke_width(SHAPE_LINE_WIDTH_PX, half_frame, pixel_size),
        opacity=1.0,
    )
    figure.shift(-anchor).scale(scale, about_point=ORIGIN)

    parts = VGroup(figure, build_axis(half_frame, pixel_size))
    if overlay != "none":
        parts.add(build_overlay(kernel, n, overlay, anchor, scale, half_frame, pixel_size))

    unit = half_frame / 4.0  # 文字大小与画幅无关, 需按取景范围等比放大
    label = Text(
        f"{star_type}   n={n}   level={level}   r={radius:.2f}",
        font_size=round(22 * unit),
        color=BLACK,
    )
    label.to_corner([-1, 1, 0], buff=0.3 * unit)

    scene = Scene()
    scene.add(VGroup(parts, label))
    scene.renderer.update_frame(scene)
    image = scene.renderer.camera.get_image()

    path = output_dir / f"{star_type}_n{n:02d}_l{level}.png"
    image.save(path)
    return path


def write_index(output_dir: Path, entries: list[tuple[str, str]], style: str = DEFAULT_INDEX_STYLE) -> Path:
    """在输出目录生成 ``index.html``。

    * ``filter``: 可按键筛选(**花型 / N / 等级**)的浏览页, 点缩略图可放大并用 ←/→ 连续翻看;
      模板见 ``examples/gallery_page.html``;
    * ``simple``: 静态缩略图网格。
    """
    index_path = output_dir / "index.html"

    if style == "filter":
        names = [name for name, _ in entries]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")  # noqa: DTZ005 - 仅用于页面脚注
        page = BROWSER_TEMPLATE.read_text(encoding="utf-8")
        page = page.replace("/*__FILES__*/", json.dumps(names, ensure_ascii=False))
        page = page.replace("<!--__GENERATED__-->", f"共 {len(names)} 张 · 生成于 {stamp}")
        index_path.write_text(page, encoding="utf-8")
        return index_path

    cards = "\n".join(
        f'      <figure><a href="{html.escape(name)}"><img src="{html.escape(name)}" loading="lazy"'
        f' alt="{html.escape(caption)}"></a><figcaption>{html.escape(caption)}</figcaption></figure>'
        for name, caption in entries
    )
    page = f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>StarRosette gallery</title>
<style>
  body {{ margin: 0; padding: 16px; background: #1b1b1f; color: #e8e8ea;
         font: 14px/1.4 system-ui, sans-serif; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
  figure {{ margin: 0; background: #26262c; border-radius: 8px; overflow: hidden; }}
  img {{ display: block; width: 100%; height: auto; background: #fff; }}
  figcaption {{ padding: 6px 8px; color: #b9b9c0; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>StarRosette 参数组合预览(共 {len(entries)} 张)</h1>
<div class="grid">
{cards}
</div>
</body>
</html>
"""
    index_path.write_text(page, encoding="utf-8")
    return index_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    combos = [(star_type, n, level) for star_type in args.star_type for n in args.n for level in args.level]
    total = len(combos)
    print(f"输出目录: {args.output.resolve()}")
    print(f"组合数量: {total}  骨架: {args.overlay}  分辨率: {args.size}px")

    # 画质只由 pixel_width/height 决定(仍是一张普通 PNG); 线宽与圆点半径按"输出像素"定义
    config = {
        "pixel_width": args.size,
        "pixel_height": args.size,
        "frame_width": FRAME_SIZE,
        "frame_height": FRAME_SIZE,
        "background_color": WHITE,
        "verbosity": "ERROR",
    }

    entries: list[tuple[str, str]] = []
    skipped: dict[tuple[str, int], list[int]] = defaultdict(list)
    with tempconfig(config):
        for index, (star_type, n, level) in enumerate(combos, start=1):
            try:
                path = render_combination(star_type, n, level, args.output, args.size, args.overlay)
            except ValueError:
                # 该阶在此 (n, star_type) 下不可实现(旋转后的核线段与 x 轴平行)
                skipped[(star_type, n)].append(level)
                continue
            except Exception as error:  # noqa: BLE001 - 单个组合失败不应中断整体导出
                print(f"[{index}/{total}] {star_type} n={n} level={level} 失败: {type(error).__name__}: {error}")
                continue
            entries.append((path.name, f"{star_type}  n={n}  level={level}"))
            if index % 25 == 0 or index == total:
                print(f"[{index}/{total}] 已导出 {len(entries)} 张")

    if skipped:
        count = sum(len(levels) for levels in skipped.values())
        print(f"跳过 {count} 个不可实现的组合:")
        for (star_type, n), levels in sorted(skipped.items()):
            print(f"  {star_type} n={n}: level {min(levels)}~{max(levels)}")

    if args.index != "none" and entries:
        print(f"索引页: {write_index(args.output, entries, args.index)}")
    print(f"完成, 共 {len(entries)} 张图片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
