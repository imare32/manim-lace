"""把同一花型的相邻若干阶叠加在同一张图上, 用于观察高阶如何从低阶"长"出来。

与 ``rosette_gallery.py`` 不同, 这里**不做归一化**: 同一张图内的所有阶共用一套
坐标系, 因此可以直接比较各阶的绝对尺度; 每阶的最大半径也会标注在图上。每张图还会用
"实线 + 顶点圆点"叠加该阶的 **petal**(花瓣单元: kernel 沿 x 轴镜像合围的未旋转单元),
可用 ``--no-petal`` 关闭。画 petal 而不是 kernel 骨架, 是为了让"整个图形由这一片旋转
``n`` 份拼成"这件事一眼可见, 也避免把朝负半轴的 kernel 骨架误读成画错。

默认配色是**三原色**: 窗口内最低阶 = 红, 其次 = 绿, 再高 = 蓝, 因此颜色本身就告诉你
谁在内圈谁在外圈(``--color absolute`` 可换回"同一阶在所有图中同色")。各阶共用同一
套线型(``--style band``: 只有半透明描边, 实线留给 petal), 绘制时半径大的先画, 于是最小的
那一阶落在最上层, 不会被外圈描边盖住。

**默认每张图只叠两阶**(``--window 2``): 三阶叠加时半透明描边互相压叠, 肉眼很难判断某条
线属于哪一阶。需要更多阶时用 ``--window`` 指定。

用法::

    uv run python examples/rosette_levels.py --star-type PA
    uv run python examples/rosette_levels.py --star-type PA --n 9 12 --window 3
    uv run python examples/rosette_levels.py --star-type PA --window 8 --step 8   # 所有阶一次画完
    uv run python examples/rosette_levels.py --star-type PA --frame n             # 整个 n 共用取景
    uv run python examples/rosette_levels.py --star-type PA --frame inner         # 放大内圈细节(裁最外圈)
    uv run python examples/rosette_levels.py --star-type PA --n 7 --only 2 --frame inner --style core

输出目录默认 ``media/rosette_levels/``(已被 ``.gitignore`` 忽略), 文件名形如
``PA_n09_L3-5.png``, 并生成 ``index.html`` 便于连续翻阅。

注意: 并非所有 ``(n, level)`` 组合都存在 —— 高阶骨架由"旋转 + 与 x 轴求交"迭代
得到, 当旋转后的线段与 x 轴平行时该阶不可实现, 库会抛出 ``ValueError``;
本脚本会自动跳过不可实现的阶。经验规律: 偶数 ``n`` 的可行上限约为 ``n/2``
(``PO`` 约为 ``n/2 + 3``), 奇数 ``n`` 的可行阶数大得多, 且图形以 ``n`` 为周期循环。
"""

from __future__ import annotations

import argparse
import html
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from manim import (
    BLACK,
    BLUE,
    DARK_BROWN,
    DARK_GREY,
    DOWN,
    GOLD,
    GREEN,
    LEFT,
    LIGHT_BROWN,
    MAROON,
    ORANGE,
    PINK,
    PURPLE,
    RED,
    TEAL,
    UP,
    WHITE,
    Circle,
    DashedVMobject,
    Dot,
    LineJointType,
    Scene,
    Text,
    VGroup,
    VMobject,
    tempconfig,
)

from manim_lace import STAR_TYPE_VALUES, StarRosette
from manim_lace.rosette import cal_kernels, get_petals_by_kernel

#: 窗口内三条曲线的颜色: Manim 的基础红/绿/蓝常量(不带 ``_A``~``_E`` 后缀)。
#: 按窗口内位置(最低/居中/最高阶)分配, 因此一眼就能由颜色读出"谁在最内圈、谁在最外圈"。
POSITION_COLORS = (RED, GREEN, BLUE)

#: ``--color absolute`` 时使用的固定配色: 同一颜色在任何图里都代表同一个阶。
#: 同样全部使用不带后缀的基础常量。
LEVEL_COLORS = (
    BLUE,
    RED,
    GREEN,
    PURPLE,
    ORANGE,
    TEAL,
    MAROON,
    GOLD,
    DARK_BROWN,
    PINK,
    DARK_GREY,
    LIGHT_BROWN,
)

#: 线型方案: 每条曲线都按"若干层 **(输出图片上的像素宽度, 不透明度)**"从宽到窄叠加绘制,
#: 三条曲线使用**同一套**线型, 只靠颜色区分:
#:
#: * ``band``(默认): 只有半透明描边 —— 实心线留给 kernel;
#: * ``faint``: 更透的描边, 叠加处更容易看出是两层;
#: * ``core``: 描边 + 同色实心芯线(需要曲线本身也带实线时用)。
#:
#: .. important::
#:    Manim 的 ``stroke_width`` 是**相对画幅**定义的(逻辑宽度 ≈ ``stroke_width × 0.01``
#:    个单位), 因此同一个 ``stroke_width`` 在越大的画幅/越低的导出分辨率下就越细:
#:    实测在本脚本的 ``±16.22`` 画幅 + 720px 输出下, ``stroke_width=9`` 只有 **2 像素**,
#:    ``1.6`` 直接掉到亚像素。所以这里一律用"输出像素"定义, 再用
#:    :func:`px_to_stroke_width` 换算, 这样无论放大取景还是提高分辨率, 粗细都保持一致。
STROKE_STYLES: dict[str, tuple[tuple[float, float], ...]] = {
    "band": ((11.0, 0.7),),
    "faint": ((11.0, 0.45),),
    "core": ((11.0, 0.55), (2.2, 1.0)),
}
DEFAULT_STYLE = "band"
DEFAULT_FRAME = "window"
DEFAULT_COLOR = "position"
DEFAULT_PETAL_STYLE = "solid"

#: Manim 中 ``stroke_width=1`` 对应的逻辑宽度(单位: 画幅高度) —— 见 ``Camera.cairo_line_width_multiple``。
MANIM_STROKE_UNIT = 0.01
#: petal 顶点圆点半径 / petal 线宽 / 参考圆线宽(均为输出像素)。
PETAL_DOT_RADIUS_PX = 5.5
PETAL_LINE_WIDTH_PX = 3.4
REFERENCE_CIRCLE_WIDTH_PX = 1.4


def px_to_stroke_width(px_width: float, half_frame: float, pixel_size: int) -> float:
    """把"输出图片上的像素宽度"换算成 Manim 的 ``stroke_width``。

    推导: 像素厚度 = ``0.01 × stroke_width × 像素高度 / 画幅高度``, 反解得
    ``stroke_width = 像素宽度 × 画幅高度 / (0.01 × 像素高度)``。
    """
    return px_width * (2 * half_frame) / (MANIM_STROKE_UNIT * pixel_size)


def px_to_units(px_length: float, half_frame: float, pixel_size: int) -> float:
    """把"输出图片上的像素长度"换算成画幅内的逻辑长度(用于圆点半径等几何量)。"""
    return px_length * (2 * half_frame) / pixel_size


DEFAULT_N = (6, 7, 8, 9, 10, 12)
#: 默认每张图叠加**两阶**: 三阶叠加时半透明色带互相压叠, 肉眼很难判断某条线属于哪一阶。
DEFAULT_WINDOW = 2
DEFAULT_MAX_LEVEL = 12
#: 取景半径 = 最大半径 × 该系数, 用于留出边距。
FRAME_MARGIN = 1.12
DEFAULT_OUTPUT = Path("media") / "rosette_levels"


def feasible_levels(star_type: str, n: int, max_level: int) -> list[int]:
    """返回该 ``(star_type, n)`` 下从 0 开始连续可实现的阶数列表。

    构建是逐阶迭代的, 某一阶不可实现则更高阶也一定不可实现, 因此可以提前中断。
    """
    levels = []
    for level in range(max_level + 1):
        try:
            cal_kernels(n, level, star_type)
        except ValueError:
            break
        levels.append(level)
    return levels


def figure_radius(star_type: str, n: int, level: int) -> float:
    """该阶图形的最大半径(用于取景与标注)。"""
    points = np.array(StarRosette(n, level, star_type).get_anchors())[:, :2]
    return float(np.linalg.norm(points, axis=1).max())


def build_petal_overlay(
    star_type: str,
    n: int,
    level: int,
    color,
    half_frame: float,
    pixel_size: int,
    petal_style: str = DEFAULT_PETAL_STYLE,
) -> VGroup:
    """把该阶的 **petal**(花瓣单元)画成实线 + 顶点圆点。

    petal 是 :func:`~manim_lace.rosette.get_petals_by_kernel` 的第 0 片 —— 由该阶
    kernel 沿 x 轴镜像而成的**未旋转**单元。整个图形就是把它旋转 ``n`` 份后按
    ``level + 1`` 的步长连接起来的结果, 因此画 petal 比画 kernel 更能说明"图形是怎么
    拼出来的", 也不会让人误以为那条朝左的 kernel 骨架是画错了。

    注意**不闭合**: 花瓣的天然边界就是 "kernel 半边 + 镜像半边" 这两段折线, 再补一条
    首尾连线只会在图形中央多出一根突兀的直线。接头用圆角, 避免尖角处出现毛刺。

    **实心线只留给 petal**(曲线本身只画半透明描边), 所以这里用满不透明度;
    ``petal_style="dashed"`` 可改成虚线。
    """
    kernel = cal_kernels(n, level, star_type)[level]
    petal = np.pad(get_petals_by_kernel(kernel, n)[0], ((0, 0), (0, 1)))

    line = VMobject(
        stroke_width=px_to_stroke_width(PETAL_LINE_WIDTH_PX, half_frame, pixel_size),
        fill_opacity=0,
        joint_type=LineJointType.ROUND,
    )
    line.set_points_as_corners(petal)
    line.set_stroke(color=color, opacity=1.0)

    if petal_style == "dashed":
        group = VGroup(DashedVMobject(line, num_dashes=24))
    else:
        group = VGroup(line)

    dot_radius = px_to_units(PETAL_DOT_RADIUS_PX, half_frame, pixel_size)
    for point in petal:
        group.add(Dot(point, radius=dot_radius, color=color))
    return group


def level_color(level: int):
    """阶数 -> 颜色(``--color absolute`` 时使用, 同一阶在所有图中保持同色)。"""
    return LEVEL_COLORS[level % len(LEVEL_COLORS)]


def window_colors(levels: list[int], color_mode: str = DEFAULT_COLOR) -> dict[int, object]:
    """窗口内各阶的配色。

    ``position``: 按窗口内位置取三原色(最低阶 = 红, 居中 = 绿, 最高 = 蓝);
    ``absolute``: 按绝对阶数取固定调色板。
    """
    if color_mode == "absolute":
        return {level: level_color(level) for level in levels}
    return {level: POSITION_COLORS[index % len(POSITION_COLORS)] for index, level in enumerate(levels)}


def resolve_half_frame(
    frame_mode: str,
    group_levels: list[int],
    radii: dict[int, float],
    full_frame: float,
    zoom: float = 1.0,
) -> float:
    """按取景方式计算画面半宽(曲线半径超过它的部分会被裁掉)。

    * ``window``: 装下本窗口的全部曲线;
    * ``n``: 装下该 ``n`` 的所有可行阶(所有图共用一套尺度, 便于跨图比较);
    * ``half``: 取**最小半径与最大半径的中点** —— 推荐档: 内圈足够大、外圈仍可辨认;
    * ``mid``: 取"居中那一圈"与"最外那圈"半径的中点 —— 只适合"最外层明显比中间层大"的情形;
    * ``inner``: 直接按**本窗口最小那一阶**取景 —— 最狠, 保证最小阶撑满画面, 但外圈几乎全被裁掉。

    最后再乘上 ``zoom`` 系数, 便于手工微调。
    """
    if frame_mode == "n":
        return full_frame * FRAME_MARGIN * zoom
    if frame_mode == "window":
        return max(radii[level] for level in group_levels) * FRAME_MARGIN * zoom

    ranked = sorted(radii[level] for level in group_levels)
    if frame_mode == "half":
        return (ranked[0] + ranked[-1]) / 2 * zoom
    if frame_mode == "mid":
        return (ranked[len(ranked) // 2] + ranked[-1]) / 2 * zoom
    return ranked[0] * FRAME_MARGIN * zoom


def build_scene_objects(
    star_type: str,
    n: int,
    levels: list[int],
    radii: dict[int, float],
    half_frame: float,
    style: str = DEFAULT_STYLE,
    cropped: Sequence[int] = (),
    draw_petal: bool = True,
    pixel_size: int = 720,
    colors: dict[int, object] | None = None,
    petal_style: str = DEFAULT_PETAL_STYLE,
) -> VGroup:
    """构造"多阶叠加 + 图例 + 单位参考圆"的场景对象。"""
    # Manim 的文字大小与画幅无关(固定 0.285 units/22pt), 因此要把字号与间距
    # 按取景范围等比放大, 否则大尺度图里的标注会小到看不见。
    unit = half_frame / 4.0
    colors = colors if colors is not None else window_colors(levels)
    layers = STROKE_STYLES[style]

    # 每条曲线的各层展开后统一排序绘制: 线宽大的(半透明描边)沉在下面,
    # 线宽小的(实心芯线)压在上面; 同样线宽时**半径大的先画**, 于是半径最小、细节最密
    # 的那一阶落在最上层, 不会被外圈的描边盖住(否则它的颜色会被染成一团)。
    pending: list[tuple[float, float, object, int]] = []
    for level in levels:
        color = colors[level]
        for px_width, opacity in layers:
            pending.append((px_to_stroke_width(px_width, half_frame, pixel_size), opacity, color, level))

    curves = VGroup()
    for width, opacity, color, level in sorted(pending, key=lambda item: (-item[0], -radii[item[3]])):
        figure = StarRosette(n, level, star_type, stroke_width=width, fill_opacity=0)
        figure.set_stroke(color=color, opacity=opacity)
        curves.add(figure)

    petal_group = VGroup()
    if draw_petal:
        for level in levels:
            petal_group.add(
                build_petal_overlay(star_type, n, level, colors[level], half_frame, pixel_size, petal_style),
            )

    title = Text(f"{star_type}   n={n}   levels {levels[0]}-{levels[-1]}", font_size=round(22 * unit), color=BLACK)
    title.to_edge(UP, buff=0.25 * unit)

    legend = VGroup()
    for level in levels:
        legend.add(Text(f"level {level}    r={radii[level]:.2f}", font_size=round(18 * unit), color=colors[level]))
    if draw_petal:
        legend.add(Text("实线+圆点: 该阶 petal 花瓣单元", font_size=round(16 * unit), color=DARK_GREY))
    legend.add(Text("灰色圆: r=1 参考", font_size=round(16 * unit), color=DARK_GREY))
    if cropped:
        levels_text = ", ".join(str(level) for level in cropped)
        legend.add(
            Text(
                f"已放大: level {levels_text} 超出 r={half_frame:.2f} 的部分在图外",
                font_size=round(16 * unit),
                color=DARK_GREY,
            ),
        )
    legend.arrange(DOWN, aligned_edge=LEFT, buff=0.16 * unit).to_corner([-1, -1, 0], buff=0.3 * unit)

    scale_note = Text(f"frame=±{half_frame:.2f}", font_size=round(18 * unit), color=DARK_GREY)
    scale_note.to_corner([1, 1, 0], buff=0.3 * unit)

    reference = Circle(
        radius=1.0,
        stroke_color=DARK_GREY,
        stroke_width=px_to_stroke_width(REFERENCE_CIRCLE_WIDTH_PX, half_frame, pixel_size),
        stroke_opacity=0.35,
    )

    # 曲线绘制在最底层, 标注直接压在曲线之上(不加白色衬底)
    return VGroup(curves, petal_group, reference, title, scale_note, legend)


def render_overlay(
    star_type: str,
    n: int,
    levels: list[int],
    radii: dict[int, float],
    half_frame: float,
    output_dir: Path,
    size: int,
    style: str = DEFAULT_STYLE,
    cropped: Sequence[int] = (),
    draw_petal: bool = True,
    colors: dict[int, object] | None = None,
    petal_style: str = DEFAULT_PETAL_STYLE,
) -> Path:
    """渲染一张叠加图并保存。"""
    # 画质只由 pixel_width/height 决定(仍是一张普通 PNG); 线宽与圆点半径都按"输出像素"
    # 定义并通过 px_to_* 换算, 所以换成其它分辨率时粗细与观感保持一致。
    config = {
        "pixel_width": size,
        "pixel_height": size,
        "frame_width": 2 * half_frame,
        "frame_height": 2 * half_frame,
        "background_color": WHITE,
        "verbosity": "ERROR",
    }
    with tempconfig(config):
        scene = Scene()
        scene.add(
            build_scene_objects(
                star_type,
                n,
                levels,
                radii,
                half_frame,
                style,
                cropped,
                draw_petal,
                size,
                colors,
                petal_style,
            ),
        )
        scene.renderer.update_frame(scene)
        image = scene.renderer.camera.get_image()

    path = output_dir / f"{star_type}_n{n:02d}_L{levels[0]}-{levels[-1]}.png"
    image.save(path)
    return path


def write_index(output_dir: Path, entries: list[tuple[str, str]]) -> Path:
    """生成一个简单的索引页。"""
    cards = "\n".join(
        f'      <figure><a href="{html.escape(name)}"><img src="{html.escape(name)}" loading="lazy"'
        f' alt="{html.escape(caption)}"></a><figcaption>{html.escape(caption)}</figcaption></figure>'
        for name, caption in entries
    )
    page = f"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>StarRosette 相邻阶叠加</title>
<style>
  body {{ margin: 0; padding: 16px; background: #1b1b1f; color: #e8e8ea;
         font: 14px/1.4 system-ui, sans-serif; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }}
  figure {{ margin: 0; background: #26262c; border-radius: 8px; overflow: hidden; }}
  img {{ display: block; width: 100%; height: auto; background: #fff; }}
  figcaption {{ padding: 6px 8px; color: #b9b9c0; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>StarRosette 相邻阶叠加(共 {len(entries)} 张, 同图内各阶共用坐标系)</h1>
<div class="grid">
{cards}
</div>
</body>
</html>
"""
    index_path = output_dir / "index.html"
    index_path.write_text(page, encoding="utf-8")
    return index_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把相邻若干阶的玫瑰线叠加在同一张图上")
    parser.add_argument("--star-type", default="PA", choices=list(STAR_TYPE_VALUES), help="花型")
    parser.add_argument("--n", type=int, nargs="+", default=list(DEFAULT_N), help="花瓣数量列表")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="每张图叠加的阶数")
    parser.add_argument("--step", type=int, default=1, help="窗口滑动步长, 1 表示相邻窗口重叠")
    parser.add_argument("--max-level", type=int, default=DEFAULT_MAX_LEVEL, help="最多尝试到哪一阶")
    parser.add_argument(
        "--only",
        type=int,
        default=None,
        metavar="START",
        help="只渲染从该阶开始的窗口, 便于快速预览(不生成索引页以外的任何其他图)",
    )
    parser.add_argument(
        "--frame",
        choices=["window", "n", "half", "mid", "inner"],
        default=DEFAULT_FRAME,
        help=(
            "取景方式: window=装下本窗口全部曲线; n=同一 n 的所有图共用取景(便于跨图比较); "
            "half=最小圈与最外圈半径的中点(推荐折中); mid=居中圈与最外圈半径的中点; "
            "inner=按本窗口最小那一阶取景(裁得最狠)"
        ),
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=1.0,
        help="在取景方式算出的半宽上再乘一个系数(<1 更放大), 便于微调",
    )
    parser.add_argument(
        "--color",
        choices=["position", "absolute"],
        default=DEFAULT_COLOR,
        help="配色: position=窗口内三阶分别用三原色(红/绿/蓝); absolute=同一阶在所有图中同色",
    )
    parser.add_argument(
        "--style",
        choices=list(STROKE_STYLES),
        default=DEFAULT_STYLE,
        help="曲线线型: band=只有半透明描边(默认); faint=更透; core=描边+同色实心芯",
    )
    parser.add_argument(
        "--petal",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否叠加各阶的 petal 花瓣单元(实线+顶点圆点)",
    )
    parser.add_argument(
        "--petal-style",
        choices=["solid", "dashed"],
        default=DEFAULT_PETAL_STYLE,
        help="petal 的线型: solid=实线(默认, 实线只留给 petal); dashed=虚线",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出目录")
    parser.add_argument("--size", type=int, default=1440, help="图片边长(像素); 越大越清晰")
    parser.add_argument("--no-index", action="store_true", help="不生成 index.html")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {args.output.resolve()}")

    entries: list[tuple[str, str]] = []
    for n in args.n:
        levels = feasible_levels(args.star_type, n, args.max_level)
        if not levels:
            print(f"跳过 n={n}: 该花型没有任何可实现的阶")
            continue
        radii = {level: figure_radius(args.star_type, n, level) for level in levels}
        radius_text = "  ".join(f"L{level}:{radii[level]:.2f}" for level in levels)
        print(f"n={n}  可行阶 {levels[0]}~{levels[-1]}  最大半径  {radius_text}")

        window = min(args.window, len(levels))
        if args.only is None:
            starts = list(range(0, max(len(levels) - window, 0) + 1, args.step)) or [0]
        elif args.only in levels:
            starts = [levels.index(args.only)]
        else:
            print(f"  跳过 n={n}: level {args.only} 在此组合下不可实现")
            continue
        full_frame = max(radii.values())
        for start in starts:
            group_levels = levels[start : start + window]
            half_frame = resolve_half_frame(args.frame, group_levels, radii, full_frame, args.zoom)
            cropped = [level for level in group_levels if radii[level] > half_frame * 1.001]
            path = render_overlay(
                args.star_type,
                n,
                group_levels,
                radii,
                half_frame,
                args.output,
                args.size,
                args.style,
                cropped,
                args.petal,
                window_colors(group_levels, args.color),
                args.petal_style,
            )
            entries.append((path.name, f"{args.star_type}  n={n}  levels {group_levels[0]}-{group_levels[-1]}"))
        print(f"  -> 已导出 {len(entries)} 张")

    if not args.no_index and entries:
        print(f"索引页: {write_index(args.output, entries)}")
    print(f"完成, 共 {len(entries)} 张图片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
