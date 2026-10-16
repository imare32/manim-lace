"""Star rosette gallery, built on the migrated ``rosette.py`` module.

Run:

    manim -pql examples/scene_rosette.py RosetteGallery
    manim -pql examples/scene_rosette.py RosetteLevels
    manim -pql examples/scene_rosette.py RosetteConstruction
    manim -pql examples/scene_rosette.py RosetteWeave
    manim -pql examples/scene_rosette.py RosetteLimits

``rosette.py`` sits next to this file in ``examples/``: it is a support module for the
examples, nothing in ``manim_lace`` imports it, and it is not part of the installed
package. The path entry below keeps the import working whether the scenes are started
through the ``manim`` CLI or through ``python -m manim``. The pipeline it documents is
the one used here:

1. ``cal_kernels(n, level, star_type)`` builds the skeleton for each order;
2. ``get_petals_by_kernel`` mirrors the kernel across the x-axis and rotates it ``n``
   times into petals;
3. ``sort_petals`` reorders them so neighbours join head-to-tail;
4. ``merge_adjacent_petals`` merges the joins into continuous loops, which is what
   :class:`~rosette.StarRosette` hands to Manim's ``Polygram``.

``RosetteWeave`` is where the two projects meet: those merged loops are *closed
self-crossing strands*, so they can be fed to :class:`manim_lace.Lace` and woven.

Every scene prints the numbers it drew (petal counts, merged loops, crossings,
diagnostics), and ``examples/build_gallery.py`` reads the same objects for the
gallery page.
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from manim import *  # noqa: F403

EXAMPLES = Path(__file__).resolve().parent
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

from rosette import (  # noqa: E402
    MIN_PETALS,
    STAR_TYPE_VALUES,
    StarRosette,
    cal_kernels,
    get_petals_by_kernel,
    merge_adjacent_petals,
    sort_petals,
)
from scene_gallery import HAIRLINE_PX, StrokePanel  # noqa: E402

from manim_lace import Lace  # noqa: E402
from manim_lace.style import get_palette  # noqa: E402

#: How far the feasibility probe is allowed to look for the largest usable level.
LEVEL_PROBE_LIMIT = 12

_PALETTE = "ayame"


def max_usable_level(n: int, star_type: str, *, limit: int = LEVEL_PROBE_LIMIT) -> int:
    """The largest level ``cal_kernels`` can build for this ``(n, star_type)``.

    Feasibility is monotone in ``level`` (each order is built from the previous one),
    so probing upwards until the first ``ValueError`` gives the real boundary that
    ``cal_kernels`` reports — for even ``n`` it is finite: ``n = 10`` allows PA/CA up
    to 5, PR/CR to 6 and PO to 8, while odd ``n`` goes far beyond the probe limit.
    """
    best = 0
    for level in range(0, limit + 1):
        try:
            cal_kernels(n, level, star_type)
        except ValueError:
            break
        best = level
    return best


def rosette_loops(n: int, level: int, star_type: str) -> list[np.ndarray]:
    """The rosette's continuous loops as closed ``(N, 2)`` point arrays.

    This is the same pipeline ``StarRosette`` runs, exposed in 2D: the merged groups
    from ``merge_adjacent_petals`` do not repeat their first point (``Polygram``
    closes them itself), so they are closed here before being used as strands.
    """
    kernel = cal_kernels(n, level, star_type)[level]
    merged = merge_adjacent_petals(sort_petals(get_petals_by_kernel(kernel, n), level))
    return [np.vstack((group, group[0])) for group in merged]


def _loops_as_mobjects(loops: list[np.ndarray], **style: object) -> VGroup:  # noqa: F405
    """Closed 2D loops as Manim paths, ready to be used as weave sources."""
    group = VGroup()  # noqa: F405
    for loop in loops:
        path = VMobject().set_points_as_corners(  # noqa: F405
            np.column_stack((loop, np.zeros(len(loop))))
        )
        if style:
            path.set_stroke(**style)
        group.add(path)
    return group


def _fit_frame(composed: Mobject, *, margin: float = 1.0) -> Mobject:  # noqa: F405
    """Shrink a composed layout so it fits the camera frame, and centre it.

    The rosette panels are wide: a row of five ``n = 10`` stars overflows the default
    frame, so every scene ends by fitting its composition instead of hard-coding a
    scale that only works at one resolution. The fit scales about the composition's
    own centre, so a layout that is not centred (row labels hanging off one side, for
    instance) would keep its off-centre centre and hang out of the frame after being
    shrunk; moving it back afterwards is a no-op for the layouts that already are.
    """
    if composed.width > config.frame_width - margin:  # noqa: F405
        composed.scale_to_fit_width(config.frame_width - margin)  # noqa: F405
    if composed.height > config.frame_height - margin:  # noqa: F405
        composed.scale_to_fit_height(config.frame_height - margin)  # noqa: F405
    composed.move_to(ORIGIN)  # noqa: F405
    return composed


@dataclass(frozen=True)
class RosetteEntry:
    """One showcase rosette: how the page describes the scene that draws it."""

    key: str
    title: str
    blurb: str
    tags: tuple[str, ...] = ()


class _RosetteScene(Scene):
    """White paper background: rosettes read as lace on paper."""

    def setup(self) -> None:
        self.camera.background_color = WHITE


class RosetteGallery(_RosetteScene):
    """The five star types at ``n = 10``, level 2, side by side."""

    def construct(self):
        palette = get_palette(_PALETTE)
        panels = VGroup()  # noqa: F405
        for index, star_type in enumerate(STAR_TYPE_VALUES):
            rosette = StarRosette(
                10, level=2, star_type=star_type,
                fill_color=palette.color(index), fill_opacity=0.9,
                stroke_color=BLACK, stroke_width=2.0,  # noqa: F405
            )
            rosette.scale(0.75)
            top = max_usable_level(10, star_type)
            caption = VGroup(  # noqa: F405
                Text(f"{star_type}", font_size=24, color=BLACK),  # noqa: F405
                Text(f"最大阶 {top}", font_size=16, color=GREY_B),  # noqa: F405
            ).arrange(DOWN, buff=0.08)
            caption.next_to(rosette, DOWN, buff=0.15)
            print(f"rosette {star_type}: n=10 level=2, max usable level {top}")
            panels.add(VGroup(rosette, caption))  # noqa: F405
        self.add(_fit_frame(panels.arrange(RIGHT, buff=0.35)))  # noqa: F405
        self.wait()


class RosetteLevels(_RosetteScene):
    """``n = 10`` PA from level 0 to the largest level it supports."""

    def construct(self):
        palette = get_palette(_PALETTE)
        top = max_usable_level(10, "PA")
        panels = VGroup()  # noqa: F405
        for level in range(0, top + 1):
            rosette = StarRosette(
                10, level=level, star_type="PA",
                fill_color=palette.color(level % len(palette)), fill_opacity=0.9,
                stroke_color=BLACK, stroke_width=1.6,  # noqa: F405
            )
            rosette.scale(0.62)
            loops = rosette_loops(10, level, "PA")
            caption = VGroup(  # noqa: F405
                Text(f"level {level}", font_size=20, color=BLACK),  # noqa: F405
                Text(f"{len(loops)} 段 / {sum(len(x) for x in loops)} 点", font_size=14, color=GREY_B),  # noqa: F405
            ).arrange(DOWN, buff=0.06)
            caption.next_to(rosette, DOWN, buff=0.12)
            print(f"level {level}: {len(loops)} loops, {sum(len(x) for x in loops)} points")
            panels.add(VGroup(rosette, caption))  # noqa: F405
        # Bottom-aligned: the higher the level the bigger the star, so aligning centres
        # would scatter the captions; this keeps them on one baseline.
        self.add(_fit_frame(panels.arrange(RIGHT, buff=0.25, aligned_edge=DOWN)))  # noqa: F405
        self.wait()


class RosetteConstruction(_RosetteScene):
    """The documented pipeline, one panel per step, on ``n = 10`` PA level 2.

    kernel → mirrored petals → the order ``sort_petals`` puts them in → the merged
    continuous loops. The first two panels are what the module's docstring calls
    "核 + 镜像 + 旋转"; the last two are why the result is drawable as one path.
    """

    def construct(self):
        n, level, star_type = 10, 2, "PA"
        kernel = cal_kernels(n, level, star_type)[level]
        petals = get_petals_by_kernel(kernel, n)
        ordered = sort_petals(petals, level)
        merged = merge_adjacent_petals(ordered)

        def polyline(points: np.ndarray, **style: object) -> VMobject:  # noqa: F405
            path = VMobject().set_points_as_corners(  # noqa: F405
                np.column_stack((points, np.zeros(len(points))))
            )
            path.set_stroke(**style)
            return path

        panels = VGroup()  # noqa: F405
        # 1. the kernel and its mirror across the x-axis
        span = float(np.abs(kernel[:, 0]).max())
        kernel_panel = VGroup(  # noqa: F405
            polyline(kernel, color=BLACK, width=3.0),  # noqa: F405
            DashedVMobject(  # noqa: F405
                polyline(kernel * np.array([1, -1]), color=GREY_B, width=2.0), num_dashes=50  # noqa: F405
            ),
            Line(  # noqa: F405
                np.array([-0.25 * span, 0, 0]), np.array([1.1 * span, 0, 0]),
                color=GREY_B, stroke_width=1.0,
            ),
        )
        # 2. every rotated petal
        petals_panel = VGroup(*[  # noqa: F405
            polyline(petal, color=GREY_B, width=1.5) for petal in petals
        ])
        # 3. the order sort_petals picks, numbered so the head-to-tail joins show
        ordered_panel = VGroup()  # noqa: F405
        palette = get_palette(_PALETTE)
        for index, petal in enumerate(ordered):
            ordered_panel.add(polyline(petal, color=palette.color(index % len(palette)), width=2.0))
        # 4. the merged loops as the class itself draws them: the pipeline's output *is*
        #    what ``StarRosette`` wraps into a ``Polygram``.
        merged_panel = StarRosette(
            n, level=level, star_type=star_type,
            fill_color=palette.color(0), fill_opacity=0.9,
            stroke_color=BLACK, stroke_width=2.0,  # noqa: F405
        )
        captions = (
            f"核 {len(kernel)} 点 + x 轴镜像",
            f"旋转 {len(petals)} 片花瓣",
            f"sort_petals（步长 {level + 1}）",
            f"合并成 {len(merged)} 段 → StarRosette",
        )
        # The kernel is a thin sliver; widen it to the petals' width so the four panels
        # are comparable instead of one of them being a speck.
        kernel_panel.scale_to_fit_width(petals_panel.width)
        for panel, caption_text in zip(
            (kernel_panel, petals_panel, ordered_panel, merged_panel), captions, strict=True
        ):
            panel.scale(0.8)
            caption = Text(caption_text, font_size=16, color=BLACK).next_to(panel, DOWN, buff=0.12)  # noqa: F405
            panels.add(VGroup(panel, caption))  # noqa: F405
        print(
            f"construction n={n} {star_type} level={level}: kernel {len(kernel)} points, "
            f"{len(petals)} petals, {len(ordered)} ordered, {len(merged)} merged loops"
        )
        self.add(_fit_frame(panels.arrange(RIGHT, buff=0.3).scale(0.75)))  # noqa: F405
        self.wait()


def _weave_one(
    n: int,
    levels: tuple[int, ...],
    star_type: str,
    offset: float,
    channel: str,
) -> Lace:
    """One rosette weave in one drawing channel.

    The ribbon panels stroke their bands in black on the white paper — the facade's
    default stroke colour is white, which draws every strand edge in paper colour and
    leaves the weave looking soft. The stroke channel gets no explicit width: the
    facade's default is ``200 * offset``, i.e. the full ribbon width, which is what
    makes the panels of a card comparable.
    """
    loops: list[np.ndarray] = []
    for level in levels:
        loops.extend(rosette_loops(n, level, star_type))
    palette = get_palette(_PALETTE)
    source = _loops_as_mobjects(loops, color=palette.color(0), width=2.0)
    ribbon = dict(palette=_PALETTE, stroke_color=BLACK, stroke_width_px=HAIRLINE_PX,
                  fill_opacity=1.0, hole_color=WHITE)
    if channel == "stroke":
        return StrokePanel(source, offset, palette=_PALETTE)
    if channel == "boolean":
        return Lace(source, offset=offset, render="ribbon", **ribbon)
    if channel == "arrangement":
        return Lace(
            source, offset=offset, render="ribbon", ribbon_backend="arrangement", **ribbon,
        )
    raise ValueError(f"unknown drawing channel: {channel!r}")


def build_rosette_weave_trio(
    n: int = 10,
    levels: tuple[int, ...] = (1, 2),
    star_type: str = "PA",
    offset: float = 0.08,
    *,
    channels: tuple[str, ...] = ("stroke", "boolean", "arrangement"),
) -> tuple[tuple[str, Lace], ...]:
    """Merged rosettes through the drawing channels, for the rosette weave cards.

    Kept out of the scenes so a card's weave can be pinned by a test: the channels
    must get the *same* assignments (default alternation), and the ribbon panels
    must stroke their bands in a colour that is visible on the white paper.

    The defaults are the ``RosetteWeave`` card: two ``n = 10`` PA rosettes (levels 1
    and 2) at ``offset = 0.08``, a ribbon half-width wide enough to read as a band
    while every crossing stays a plain transverse event (0.02 is a hairline).

    Returns:
        ``(channel, lace)`` pairs in card order.
    """
    loops: list[np.ndarray] = []
    for level in levels:
        loops.extend(rosette_loops(n, level, star_type))
    print(f"weave source: n={n} {star_type} levels={list(levels)}, "
          f"{len(loops)} loops, {sum(len(loop) for loop in loops)} points")
    return tuple(
        (channel, _weave_one(n, levels, star_type, offset, channel))
        for channel in channels
    )


class _RosetteWeaveCard(_RosetteScene):
    """One rosette weave through the drawing channels, captioned with real numbers.

    ``RosetteWeave`` is the ``n = 10`` PA instance. The other cards pin the
    configurations the flush-edge audit walks (``docs/ROSETTE_RIBBON_OUTLINE_TICKS.md``
    §7): each of them used to draw a stroke inside its own ribbon, or lose one, before
    the marking was fixed — so they are the evidence that the fix holds, not more of
    the same picture.
    """

    #: ``(n, levels, star_type, offset)`` of the weave this card draws.
    SOURCE: tuple[int, tuple[int, ...], str, float] = (10, (1, 2), "PA", 0.08)
    #: The channels to draw, in panel order.
    CHANNELS: tuple[str, ...] = ("stroke", "boolean", "arrangement")

    def construct(self):
        variants = build_rosette_weave_trio(*self.SOURCE, channels=self.CHANNELS)
        laces = VGroup()  # noqa: F405
        labels = VGroup()  # noqa: F405
        for channel, lace in variants:
            print(
                f"weave {channel}: {len(lace.crossings)} crossings, "
                f"{len(lace.result.pieces)} visible, {[d.code for d in lace.diagnostics]}"
            )
            laces.add(lace)
            # Attached after the laces are arranged, so the panels stay congruent:
            # a wider label must not push a panel sideways.
            labels.add(VGroup(  # noqa: F405
                Text(channel, font_size=20, color=BLACK),  # noqa: F405
                Text(f"{len(lace.crossings)} 交叉 / {len(lace.result.pieces)} 可见",
                     font_size=13, color=GREY_B),  # noqa: F405
            ).arrange(DOWN, buff=0.06))
        laces.arrange(RIGHT, buff=0.6)
        for label, lace in zip(labels, laces, strict=True):
            label.next_to(lace, DOWN, buff=0.15)
        composed = VGroup(laces, labels)  # noqa: F405
        width = composed.width
        _fit_frame(composed)  # noqa: F405
        # The fit scales geometry, and ``Mobject.scale`` leaves stroke widths alone — so
        # the stroke panel's strands (whose width *is* a stroke) come out wider than the
        # ribbon bands beside them unless they are re-stroked for the fitted scale.
        factor = composed.width / width if width else 1.0
        for lace in laces:
            if isinstance(lace, StrokePanel):
                lace.refit(factor)
        self.add(composed)
        self.wait()


class RosetteWeave(_RosetteWeaveCard):
    """Two rosettes' continuous loops woven by ``manim_lace`` in all three channels.

    The merged loops are closed self-crossing strands, so the lace engine treats them
    like any other input: every crossing is an ordinary transverse event, including
    the 20 self-crossings, and default alternation solves all 70 of them with no
    relaxation (measured: zero same-side-in-a-row visits on every loop, and the strict
    ``conflict_strategy="error"`` produces the identical assignment).
    """

    SOURCE = (10, (1, 2), "PA", 0.08)


class RosetteWeaveCA7(_RosetteWeaveCard):
    """``n = 7`` CA level 2: the configuration that showed the marking bug first.

    Convergent tips put a crossing's two cut chords right onto a band's lateral edge,
    which is where one exterior edge comes out part seam and part notch — the case
    ``mark_flush_edges`` used to get wrong in both directions at once (a line across
    the ribbon *and* a missing outline). Measured on this card: one 29-point closed
    strand, 14 crossings, all of them self-crossings, default alternation with no
    relaxation (the strict ``conflict_strategy="error"`` produces the same assignment).
    """

    SOURCE = (7, (2,), "CA", 0.10)


class RosetteWeaveCR11(_RosetteWeaveCard):
    """``n = 11`` CR level 2: the configuration that showed the fold bug.

    A thin wedge between the two cut chords lost its tip to the fold removal and
    vanished from the ring — a hole in the painted ribbon that no fill test notices,
    because the area accounting is done on the geometry, not on the ring. Measured on
    this card: one 45-point closed strand, 22 crossings, all of them self-crossings,
    default alternation with no relaxation.
    """

    SOURCE = (11, (2,), "CR", 0.07)


class RosetteWeaveThin(_RosetteWeaveCard):
    """The ``RosetteWeave`` pattern at a thinner ribbon (``offset = 0.05``).

    Half the half-width makes the overlap at every crossing narrower than the miter
    corner that bounds it, so the lens sits strictly inside the under band — the
    shape the arrangement backend's face ownership and the area accounting have to
    get right. Same source loops as ``RosetteWeave`` (three strands, 63 points, 70
    crossings of which 20 are self-crossings), same assignments, more visible regions.
    """

    SOURCE = (10, (1, 2), "PA", 0.05)


class RosetteWeaveTypes(_RosetteWeaveCard):
    """All five flower types at ``n = 10`` level 2, in both ribbon backends.

    One row per backend, one column per flower type. The two rows must show the same
    weave everywhere — the same cuts, the same notches — because both backends cut
    the pass the assignment says is under; a disagreement between the rows is exactly
    the "one panel cuts what the other leaves whole" signature this family of fixes
    was about. Measured per panel: one 41-point closed strand, 20 crossings, all of
    them self-crossings, 0 diagnostics in the arrangement row.
    """

    CHANNELS = ("boolean", "arrangement")

    def construct(self):
        rows = VGroup()  # noqa: F405
        row_titles = VGroup()  # noqa: F405
        for channel in self.CHANNELS:
            panels = VGroup()  # noqa: F405
            captions = VGroup()  # noqa: F405
            for star_type in STAR_TYPE_VALUES:
                lace = _weave_one(10, (2,), star_type, 0.08, channel)
                print(
                    f"weave {channel} {star_type}: {len(lace.crossings)} crossings, "
                    f"{len(lace.result.pieces)} visible, {[d.code for d in lace.diagnostics]}"
                )
                panels.add(lace)
                captions.add(Text(star_type, font_size=20, color=BLACK))  # noqa: F405
            panels.arrange(RIGHT, buff=0.25)
            for caption, panel in zip(captions, panels, strict=True):
                caption.next_to(panel, DOWN, buff=0.12)
            rows.add(VGroup(panels, captions))  # noqa: F405
            # A row title, not a side label: labels hanging off the left would push the
            # composition's centre off the origin, and the frame fit scales about that
            # centre — the row would then hang out of the frame on the left.
            row_titles.add(Text(channel, font_size=22, color=BLACK))  # noqa: F405
        rows.arrange(DOWN, buff=0.85)
        for title, row in zip(row_titles, rows, strict=True):
            title.next_to(row, UP, buff=0.18)
        self.add(_fit_frame(VGroup(rows, row_titles)))  # noqa: F405
        self.wait()


class RosetteLimits(_RosetteScene):
    """The real feasibility boundary, printed instead of glossed over.

    ``cal_kernels`` raises ``ValueError`` when an order cannot be built (the rotated
    kernel segment ends up parallel to the x-axis). For even ``n`` that happens after
    a finite number of orders, so the scene shows the table and the actual message for
    one ``(n, star_type)`` that is asked for one order too many.
    """

    def construct(self):
        rows = []
        for n in (6, 8, 10, 12):
            cells = "  ".join(f"{star_type} {max_usable_level(n, star_type)}" for star_type in STAR_TYPE_VALUES)
            rows.append(f"n = {n:2d}   {cells}")
        table = VGroup(*[  # noqa: F405
            Text(row, font_size=18, color=BLACK, font="Consolas") for row in rows
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        title = VGroup(  # noqa: F405
            Text("偶数 n 的最大可用阶（逐阶探测 cal_kernels）", font_size=22, color=BLACK),  # noqa: F405
            Text(
                f"n < {MIN_PETALS} 被拒绝（n=3 时核退化成一条径向线段），奇数 n 远超本表探测上限",
                font_size=16, color=GREY_B,  # noqa: F405
            ),
        ).arrange(DOWN, buff=0.12)

        n, star_type = 6, "PA"
        beyond = max_usable_level(n, star_type) + 1
        try:
            cal_kernels(n, beyond, star_type)
        except ValueError as error:
            message = str(error)
        print(f"n={n} {star_type} level {beyond} → ValueError: {message}")
        wrapped = textwrap.wrap(message, 92)
        error_text = VGroup(  # noqa: F405
            Text(f"cal_kernels({n}, {beyond}, {star_type!r}) 抛出 ValueError：", font_size=16, color=RED),  # noqa: F405
            *[Text(line, font_size=14, color=GREY_B) for line in wrapped],  # noqa: F405
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1)

        content = VGroup(title, table, error_text).arrange(DOWN, buff=0.5).scale(0.9)  # noqa: F405
        self.add(_fit_frame(content, margin=1.4))  # noqa: F405
        self.wait()


#: The showcase order used by ``examples/build_gallery.py`` (scene name, entry).
GALLERY: tuple[tuple[str, RosetteEntry], ...] = (
    ("RosetteGallery", RosetteEntry(
        key="RosetteGallery", title="五种花型的玫瑰线",
        blurb="同样是 n=10、第 2 阶，只换花型标识：PA/PR 是平行尖端，CA/CR 收敛尖端，"
              "PO 的尖端线在 n=4 时不与 x 轴相交（模块会直接抛错）。标签上的“最大阶”由"
              "逐阶探测 cal_kernels 得到，是真实边界而不是估计。",
        tags=("n=10", "level=2", "5 种花型"),
    )),
    ("RosetteLevels", RosetteEntry(
        key="RosetteLevels", title="阶数阶梯：n=10 PA",
        blurb="从第 0 阶到第 5 阶（该组合的最大可用阶），每阶都标出合并后剩几段连续折线、"
              "共多少点。阶数越高内部连接越密，段数也随 sort_petals 的步长变化。",
        tags=("n=10", "PA", "level 0–5"),
    )),
    ("RosetteConstruction", RosetteEntry(
        key="RosetteConstruction", title="构造链：核 → 镜像 → 旋转 → 合并",
        blurb="四格对应模块文档里的四步：核与它关于 x 轴的镜像、旋转出的 n 片花瓣、"
              "sort_petals 按步长 level+1 重排（相邻花瓣首尾相接）、merge_adjacent_petals "
              "合并成连续折线。Manim 的 Polygram 会自动闭合，所以合并时会去掉重复末点。",
        tags=("n=10", "PA", "level=2"),
    )),
    ("RosetteWeave", RosetteEntry(
        key="RosetteWeave", title="把玫瑰线交给编织器",
        blurb="合并后的折线是闭合自交股线，于是可以直接喂给 manim_lace：两朵玫瑰线"
              "（level 1 与 level 2）在三个绘制通道里编织。三条股线共 70 个交叉（其中 20 处"
              "是自交），默认交替模式对它们全部有解、一处都不用放宽——自交在这里就是普通的"
              "横穿事件，ribbon 后端按偏移带把被压的那一遍切掉。",
        tags=("stroke / boolean / arrangement", "跨模块"),
    )),
    ("RosetteWeaveCA7", RosetteEntry(
        key="RosetteWeaveCA7", title="编织复查：n=7 CA",
        blurb="审计（docs/ROSETTE_RIBBON_OUTLINE_TICKS.md §7）第一个命中缺陷签名的配置："
              "收敛尖端把交叉的两刀切弦正好落到丝带侧边上，于是一条外边一半是接缝、一半是"
              "切口，mark_flush_edges 曾同时把它判反两个方向——丝带中间多一条线、真实轮廓"
              "又少一条。一个 29 点闭合 strand、14 处交叉全是自交，默认交替零放宽。",
        tags=("n=7", "CA", "缺陷签名已清零"),
    )),
    ("RosetteWeaveCR11", RosetteEntry(
        key="RosetteWeaveCR11", title="编织复查：n=11 CR",
        blurb="审计第二个命中的配置：两刀切弦之间那片薄楔形的楔尖，被 _drop_folds 当成"
              "“布尔运算留下的零面积折返”连顶点一起删掉——填充看上去没问题，环上却少了"
              "一整块（面积核算查几何、不查环，所以发现不了）。修法是一遍只删一个折返、"
              "删完重判。一个 45 点闭合 strand、22 处交叉全是自交。",
        tags=("n=11", "CR", "缺陷签名已清零"),
    )),
    ("RosetteWeaveThin", RosetteEntry(
        key="RosetteWeaveThin", title="编织复查：细丝带（offset 0.05）",
        blurb="和第一张卡同源（两朵 n=10 PA level 1+2、同样的 70 个交叉与上下关系），只把"
              "丝带半宽减半：每个交叉的重叠区比界定它的 miter 角更窄，透镜整个落在被压丝带"
              "内部——正是 arrangement 后端的面归属与面积核算要拿捏的形状，也曾是并集丢面、"
              "误报 REGION-AREA-MISMATCH 的那一档。",
        tags=("n=10", "PA", "offset 0.05"),
    )),
    ("RosetteWeaveTypes", RosetteEntry(
        key="RosetteWeaveTypes", title="编织复查：五种花型 × 两个 ribbon 后端",
        blurb="n=10 level 2 的五种花型各织一遍，上排布尔后端、下排平面剖分后端。两排必须在"
              "每一处都长出同一种编织——同样的切口、同样的缺口——因为两个后端切的都是"
              "“assignment 说被压的那一遍”；两排对不上就是这类问题的原始签名。每格一个 41 点"
              "闭合 strand、20 处交叉全是自交，下排 0 诊断。",
        tags=("五种花型", "boolean vs arrangement", "逐列对齐"),
    )),
    ("RosetteLimits", RosetteEntry(
        key="RosetteLimits", title="可行域：偶数 n 会到顶",
        blurb="cal_kernels 每次只构造到请求的阶，某阶不可实现时（旋转后的核线段与 x 轴平行）"
              "抛 ValueError 并给出最大可用阶，不会产出 inf/nan 坐标。这一格把真实边界与"
              "真实报错原文摆出来：n=10 时 PA/CA 到 5 阶、PR/CR 到 6 阶、PO 到 8 阶。",
        tags=("诚实边界", "ValueError", "偶数 n"),
    )),
)
