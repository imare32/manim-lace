"""Render the showcase gallery into ``media/gallery/`` from real data.

Usage:

    python examples/build_gallery.py                  # render everything, then write the page
    python examples/build_gallery.py -q l             # faster / smaller renders
    python examples/build_gallery.py --no-render      # reuse the existing media, refresh the data
    python examples/build_gallery.py --only CircleLineGallery,PaletteGallery
    python examples/build_gallery.py --skip-videos

Everything on the page comes from the current checkout:

* the media is rendered from the scene classes in this directory;
* the numbers are read from the ``Lace`` objects those scenes build (a thin probe
  records them while ``construct`` runs), so crossings, visible regions/pieces,
  area accounting, diagnostics, palette choices, density simplifications and trace
  events are measured, never typed in;
* the palette table is read from ``manim_lace.style.palette``.

Data collection is separated from rendering: ``--no-render`` still re-runs every
scene (with its animations stubbed out) so the page keeps real numbers while the
images stay as they are on disk.

The output lives under ``media/`` (the same generated-data directory Manim uses and
the repository ignores), so re-running this script never leaves untracked files in
``examples/``. Open ``media/gallery/index.html`` to look at the result.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import importlib
import io
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).resolve().parent
ROOT = EXAMPLES.parent
if str(EXAMPLES) not in sys.path:
    # For the example modules themselves (scene_*.py and their support module rosette.py).
    sys.path.insert(0, str(EXAMPLES))

import manim  # noqa: E402
import numpy as np  # noqa: E402
import rosette as rosette_module  # noqa: E402
from manim import tempconfig  # noqa: E402

import manim_lace  # noqa: E402
from manim_lace import Lace  # noqa: E402
from manim_lace.style import palette as palette_module  # noqa: E402

#: Generated output lives next to Manim's own renders, which the repository ignores.
MEDIA = ROOT / "media" / "gallery"
PAGE = MEDIA / "index.html"
SCRATCH = ROOT / "media" / "_gallery_build"

#: Records every ``Lace`` the showcase builds, so the page can describe the real objects.
_CAPTURED: list[Lace] = []
_ORIGINAL_INIT = Lace.__init__


def _capturing_init(self: Lace, *args: Any, **kwargs: Any) -> None:
    _ORIGINAL_INIT(self, *args, **kwargs)
    _CAPTURED.append(self)


Lace.__init__ = _capturing_init  # type: ignore[method-assign]

# ``from_parametric`` / ``from_graph`` build the object through ``__new__``, so the
# class method needs the same probe.
_ORIGINAL_FROM_ENGINE = Lace._from_engine.__func__  # type: ignore[attr-defined]


def _capturing_from_engine(cls: Any, *args: Any, **kwargs: Any) -> Lace:
    obj = _ORIGINAL_FROM_ENGINE(cls, *args, **kwargs)
    _CAPTURED.append(obj)
    return obj


Lace._from_engine = classmethod(_capturing_from_engine)  # type: ignore[method-assign]

#: Records every ``StarRosette`` the showcase builds (``rosette.py`` is an examples-only
#: support module, so it is probed here as well).
_ROSETTES: list[Any] = []
_ORIGINAL_ROSETTE_INIT = rosette_module.StarRosette.__init__


def _capturing_rosette_init(self: Any, *args: Any, **kwargs: Any) -> None:
    _ORIGINAL_ROSETTE_INIT(self, *args, **kwargs)
    _ROSETTES.append(self)


rosette_module.StarRosette.__init__ = _capturing_rosette_init  # type: ignore[method-assign]


@dataclass(frozen=True)
class Card:
    """One showcase tile: which scene draws it, in which module, and how it is described."""

    key: str
    scene: str
    module: str
    title: str
    blurb: str
    tags: tuple[str, ...] = ()
    media: str = "still"  # "still" or "video"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    subtitle: str
    cards: tuple[Card, ...]


@dataclass
class Collected:
    """A card plus what the scene actually built while it constructed."""

    card: Card
    laces: list[Lace] = field(default_factory=list)
    rosettes: list[Any] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    rendered: bool = False


# ---------------------------------------------------------------------------
# The showcase (prose only; every number below comes from the code)
# ---------------------------------------------------------------------------


def _weave_cards() -> tuple[Card, ...]:
    """Weave cards take their prose from the scenes themselves.

    ``scene_gallery.GALLERY`` pairs every showcase pattern with the ``GalleryEntry``
    its scene renders, so one pattern is never described twice in two places and the
    page cannot drift from what the renderer draws.
    """
    from scene_gallery import GALLERY

    return tuple(
        Card(
            scene_name,  # media is named after the scene, so re-rendering one is obvious
            scene_name,
            "scene_gallery",
            entry.title,
            entry.blurb,
            entry.tags,
        )
        for scene_name, entry in GALLERY
    )


def _rosette_cards() -> tuple[Card, ...]:
    """Rosette cards take their prose from ``scene_rosette.GALLERY`` (same idea)."""
    from scene_rosette import GALLERY

    return tuple(
        Card(
            scene_name,
            scene_name,
            "scene_rosette",
            entry.title,
            entry.blurb,
            entry.tags,
        )
        for scene_name, entry in GALLERY
    )


SECTIONS: tuple[Section, ...] = (
    Section("weave", "编织图案", "ribbon 后端，白底黑线", _weave_cards()),
    Section(
        "rosette", "玫瑰线（Star Rosette）",
        "根目录 rosette.py 的星形玫瑰，最后一格交给编织器",
        _rosette_cards(),
    ),
    Section("backend", "绘制通道对照", "同一份交叉与上下关系，三个后端", (
        Card("RibbonGallery", "RibbonGallery", "scene_gallery", "同一输入，三种绘制通道",
             "stroke 按中心线切口；ribbon(boolean) 把重叠区从下股丝带上布尔减掉；"
             "ribbon(arrangement) 求出丝带边界的平面剖分，再按交叉把每个面归给一条股线。",
             ("stroke / boolean / arrangement", "面积核算")),
    )),
    Section("style", "美学策略（M6）", "manim_lace.style：纯装饰层，不动交叉与上下关系", (
        Card("PaletteGallery", "PaletteGallery", "scene_style", "调色板：同一编织，四套和色",
             "色卡取自公开的日本传统色名，分组参考樱井辉子《日本色彩调和辞典》的季节／色调思路"
             "（不复刻原书色卡）。深色在前、纸色收尾，循环取色时先给可见的颜色。",
             ("haru / natsu / aki / fuyu", "纸张层", "边框")),
        Card("BorderGallery", "BorderGallery", "scene_style", "边框设计：同一图案，四种框",
             "边框由可见几何的包围盒生成，支持方形／圆角／切角、多环、内缩与配色索引；"
             "落进图案内部或圆角放不下时会抛错，而不是悄悄近似。",
             ("square / round / bevel", "inset", "双环")),
        Card("CutEndGallery", "CutEndGallery", "scene_style", "切口端处理",
             "cover_allowance 是几何参数：每个断口两侧各缩短 allowance × offset，让下股端头藏进"
             "上股之下；第三格用 stroke_piece_outline 画出片段真实覆盖的多边形，端头形状是可验证的几何。",
             ("butt / round", "覆盖余量", "真实端头轮廓")),
        Card("DensityGallery", "DensityGallery", "scene_style", "密集交叉区的视觉简化",
             "analyze_density 只测量（网格计数／热点／密集簇），simplify_for_density 只隐藏"
             "中点落在密集簇内且短于阈值的可见片段；隐藏清单与阈值写在 RENDER-DENSITY-SIMPLIFIED 里。",
             ("密度簇", "诚实上报")),
    )),
    Section("trace", "算法轨迹（M5）", "动画与细粒度 trace 事件", (
        Card("WeaveDemo", "WeaveDemo", "scene_weave", "算法动画：轨迹驱动的阶段划分",
             "动画计划按真实 TraceEvent 的阶段分组（输入／交叉／拓扑／构造／诊断／完成），"
             "algorithm 与 debug 模式还会叠加细粒度读数。",
             ("manim 动画", "trace 阶段"), media="video"),
        Card("SamplingTraceDemo", "SamplingTraceDemo", "scene_weave", "自适应细分的真实读数",
             "曲线由引擎自己采样，画面上的递归节点数、细分次数与最深层数直接读自 "
             "sampling.subdivision 事件，而不是事后编的数字。",
             ("sampling.subdivision", "有界 trace"), media="video"),
    )),
)

ALL_CARDS: tuple[Card, ...] = tuple(card for section in SECTIONS for card in section.cards)
SECTION_BY_KEY = {section.key: section for section in SECTIONS}


# ---------------------------------------------------------------------------
# Collection: run each scene with its animations stubbed out
# ---------------------------------------------------------------------------


def _module(card: Card) -> Any:
    return importlib.import_module(card.module)


def _collect(card: Card) -> Collected:
    """Run ``construct`` without rendering, so the real objects are available."""
    _CAPTURED.clear()
    _ROSETTES.clear()
    scene = getattr(_module(card), card.scene)()
    scene.play = lambda *args, **kwargs: None  # type: ignore[method-assign]
    scene.wait = lambda *args, **kwargs: None  # type: ignore[method-assign]
    scene.add = lambda *args, **kwargs: None  # type: ignore[method-assign]
    # The scenes print their own diagnostics; keep the build log readable.
    with contextlib.redirect_stdout(io.StringIO()):
        scene.construct()
    collected = Collected(card=card, laces=list(_CAPTURED), rosettes=list(_ROSETTES))
    _CAPTURED.clear()
    _ROSETTES.clear()
    collected.metrics = _measure(collected)
    collected.note = _note(collected)
    return collected


def _event_data(lace: Lace, event_type: str) -> dict[str, Any]:
    """A lace's trace event data — the engine's own numbers, not a re-computation."""
    for event in lace.result.trace:
        if event.event_type == event_type:
            return dict(event.data)
    return {}


def _measure(collected: Collected) -> dict[str, Any]:
    """Measure the objects the scene built: nothing here is inferred or typed in."""
    laces = collected.laces
    codes: Counter[str] = Counter()
    events: Counter[str] = Counter()
    for lace in laces:
        codes.update(diagnostic.code for diagnostic in lace.diagnostics)
        events.update(event.event_type for event in lace.result.trace)
    return {
        "laces": len(laces),
        "paths": sum(len(lace.paths) for lace in laces),
        "crossings": sum(len(lace.crossings) for lace in laces),
        "visible": sum(len(lace.result.pieces) for lace in laces),
        "modes": sorted({lace.render_mode for lace in laces}),
        "backends": sorted({
            lace.engine.ribbon_backend for lace in laces if lace.render_mode == "ribbon"
        }),
        "diagnostics": codes,
        "events": events,
        "palettes": [
            f"{lace.style.palette.label} {lace.style.palette.name}"
            for lace in laces
            if lace.style is not None and getattr(lace.style, "palette", None) is not None
        ],
        "density_dropped": sum(
            lace.density.dropped_count for lace in laces if lace.density is not None
        ),
        "accounting": {
            lace.engine.ribbon_backend: _event_data(lace, "region.accounting")
            for lace in laces
            if lace.render_mode == "ribbon"
        },
        "face_walk": {
            lace.engine.ribbon_backend: _event_data(lace, "region.face_walk")
            for lace in laces
            if lace.render_mode == "ribbon"
        },
        "rosettes": [
            {
                "n": rosette.n,
                "level": rosette.level,
                "star_type": rosette.star_type,
                "points": sum(len(subpath) for subpath in rosette.get_subpaths()),
            }
            for rosette in collected.rosettes
        ],
    }


def _rosette_helpers() -> Any:
    """The rosette example module (imported after the probes are installed)."""
    return importlib.import_module("scene_rosette")


def _note(collected: Collected) -> str:
    """One measured sentence per card, describing what the media really contains."""
    card, laces, metrics = collected.card, collected.laces, collected.metrics
    if card.key == "RosetteLimits":
        # A text-only scene: its numbers come from the probe, not from a drawn object.
        return f"偶数 n 的可行域：n=6 {_max_levels(6)}；n=12 {_max_levels(12)}；越界值原样抛出 ValueError"
    if not laces and not collected.rosettes:
        return ""
    if card.key == "RibbonGallery":
        parts = []
        for lace in laces:
            if lace.render_mode != "ribbon":
                parts.append(f"stroke: {len(lace.result.pieces)} 个可见片段")
                continue
            accounting = _event_data(lace, "region.accounting")
            parts.append(
                f"{lace.engine.ribbon_backend}: 可见面积 {accounting.get('painted_area', 0.0):.4f}"
                f" = 并集 {accounting.get('union_area', 0.0):.4f}，"
                f"隐藏 {accounting.get('removed_area', 0.0):.4f}"
            )
        return "；".join(parts)
    if card.key == "PaletteGallery":
        return f"四个面板各取一套配色：{'、'.join(metrics['palettes'])}"
    if card.key == "BorderGallery":
        return (
            f"{len(laces)} 种边框配置，共 {metrics['crossings']} 个交叉；"
            "框线颜色默认取配色里最深的一色"
        )
    if card.key == "CutEndGallery":
        states = "、".join(
            f"{lace.engine.cap_style} 余量 {lace.engine.cover_allowance:g}" for lace in laces
        )
        return f"三种端头设置：{states}"
    if card.key == "DensityGallery":
        applied = [lace for lace in laces if lace.density is not None and lace.density.applied]
        if not applied:
            return "本次配置没有片段短于阈值，因此一个都没省略"
        lace = applied[0]
        report = lace.density.report
        return (
            f"省略 {lace.density.dropped_count} 个极短片段"
            f"（阈值 {lace.density.threshold:.4f}，簇半径 {lace.density.report.cluster_radius:.4f}，"
            f"{len(report.clusters)} 个密集簇 / {report.crossing_count} 个交叉）"
        )
    if card.key == "RosetteGallery":
        return f"n=10、level=2 的五种花型；各自最大可用阶 {_max_levels(10)}"
    if card.key == "RosetteLevels":
        loops_of = _rosette_helpers().rosette_loops
        steps = "、".join(
            f"L{item['level']} {len(loops_of(item['n'], item['level'], item['star_type']))} 段"
            for item in metrics["rosettes"]
        )
        first = metrics["rosettes"][0]
        return f"该组合（n={first['n']} {first['star_type']}）逐阶：{steps}"
    if card.key == "RosetteConstruction" and metrics["rosettes"]:
        item = metrics["rosettes"][0]
        kernel = rosette_module.cal_kernels(item["n"], item["level"], item["star_type"])[item["level"]]
        loops = _rosette_helpers().rosette_loops(item["n"], item["level"], item["star_type"])
        return (
            f"核 {len(kernel)} 点 → 旋转 {item['n']} 片花瓣 → 按步长 {item['level'] + 1} 重排 → "
            f"合并成 {len(loops)} 段连续折线（{sum(len(loop) for loop in loops)} 点）"
        )
    if card.key == "RosetteWeave":
        loops = _rosette_helpers().rosette_loops(10, 1, "PA") + _rosette_helpers().rosette_loops(
            10, 2, "PA"
        )
        parts = [f"源 {len(loops)} 条闭合自交股线"]
        stroke = next((lace for lace in laces if lace.render_mode == "stroke"), None)
        if stroke is not None:
            parts.append(f"stroke {len(stroke.crossings)} 交叉 / {len(stroke.result.pieces)} 片段")
        for lace in laces:
            if lace.render_mode != "ribbon":
                continue
            codes = sorted({diagnostic.code for diagnostic in lace.diagnostics})
            parts.append(
                f"{lace.engine.ribbon_backend} {len(lace.result.pieces)} 区域"
                + (f"（{'、'.join(codes)}）" if codes else "（0 诊断）")
            )
        return "；".join(parts)
    if card.media == "video":
        total = sum(metrics["events"].values())
        return f"本场景产生 {total} 条 trace 事件，涵盖 {len(metrics['events'])} 种类型"
    codes = metrics["diagnostics"]
    if not codes:
        return f"本次求解 0 条诊断：{metrics['crossings']} 个交叉全部有唯一解"
    detail = "、".join(f"{code}×{count}" for code, count in sorted(codes.items()))
    return f"本次求解 {sum(codes.values())} 条诊断：{detail}"


def _max_levels(n: int) -> str:
    """The largest usable level per star type, probed the same way the scenes do."""
    return "、".join(
        f"{star_type} {_rosette_helpers().max_usable_level(n, star_type)}"
        for star_type in rosette_module.STAR_TYPE_VALUES
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_QUALITY = {"l": "low_quality", "m": "medium_quality", "h": "high_quality", "k": "fourk_quality"}


def _render(card: Card, quality: str) -> None:
    """Render the card's media with the current code and copy it into ``media/gallery``."""
    scene_class = getattr(_module(card), card.scene)
    video = card.media == "video"
    options = {
        "quality": _QUALITY["l"] if video else _QUALITY[quality],
        "format": "mp4" if video else "png",
        "save_last_frame": not video,
        "media_dir": str(SCRATCH),
        "verbosity": "ERROR",
        "disable_caching": True,
        "progress_bar": "none",
    }
    with tempconfig(options):
        scene_class().render()
    suffix = ".mp4" if video else ".png"
    produced = sorted(SCRATCH.rglob(f"*{suffix}"), key=lambda path: path.stat().st_mtime)
    if not produced:
        raise RuntimeError(f"rendering {card.scene} produced no {suffix} under {SCRATCH}")
    MEDIA.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced[-1], MEDIA / f"{card.key}{suffix}")


# ---------------------------------------------------------------------------
# Tables (read from the package and from the collected objects)
# ---------------------------------------------------------------------------


def palette_table() -> str:
    blocks = []
    for name in palette_module.palette_names():
        palette = palette_module.get_palette(name)
        chips = "".join(
            f'<span class="chip" style="background:{swatch.hex}" '
            f'title="{html.escape(swatch.name)} {swatch.reading} {swatch.hex}">'
            f'<b>{html.escape(swatch.name)}</b><i>{swatch.hex}</i></span>'
            for swatch in palette.swatches
        )
        blocks.append(
            f'<div class="palette"><div class="palette-head">'
            f'<strong>{html.escape(palette.label)}</strong> {html.escape(palette.name)}'
            f'<span class="paper" style="background:{palette.background}" '
            f'title="纸 {palette.background}"></span><em>纸 {palette.background}</em></div>'
            f'<div class="chips">{chips}</div>'
            f"<p>{html.escape(palette.description)}</p></div>"
        )
    return "".join(blocks)


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    head = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table class='data'><tr>{head}</tr>{body}</table>"


def _code_cell(codes: list[str]) -> str:
    return f"<span class='codes'>{html.escape('、'.join(codes) or '—')}</span>"


def backend_table(entries: list[tuple[str, Lace]]) -> str:
    """The accounting each backend reported in its own trace events (no re-computation)."""
    rows = []
    for label, lace in entries:
        if lace.render_mode != "ribbon":
            continue
        accounting = _event_data(lace, "region.accounting")
        walk = _event_data(lace, "region.face_walk")
        rows.append((
            html.escape(label),
            f"<code>{lace.engine.ribbon_backend}</code>",
            f"{len(lace.result.pieces)}",
            f"{accounting.get('region_area_sum', 0.0):.6f}",
            f"{accounting.get('painted_area', 0.0):.6f}",
            f"{accounting.get('union_area', 0.0):.6f}",
            f"{accounting.get('removed_area', 0.0):.6f}",
            f"{walk.get('node_count', 0)}",
            f"{walk.get('owner_count', 0)}",
            f"{walk.get('face_count', walk.get('region_polygon_count', 0))}",
            _code_cell(sorted({diagnostic.code for diagnostic in lace.diagnostics})),
        ))
    return _table(
        ("场景", "后端", "可见区域", "区域面积和", "可见面积", "丝带并集", "被隐藏", "遍历节点",
         "归属数", "遍历面数", "诊断"),
        rows,
    )


def trace_table(laces: list[Lace]) -> str:
    counts: Counter[str] = Counter()
    stages: dict[str, str] = {}
    keys: dict[str, list[str]] = {}
    for lace in laces:
        for event in lace.result.trace:
            counts[event.event_type] += 1
            stages[event.event_type] = event.stage
            keys.setdefault(event.event_type, sorted(event.data)[:6])
    rows = [
        (
            f"<code>{html.escape(name)}</code>",
            html.escape(stages[name]),
            str(count),
            _code_cell(keys[name]),
        )
        for name, count in sorted(counts.items(), key=lambda item: (stages[item[0]], item[0]))
    ]
    return _table(("事件类型", "阶段", "条数", "data 字段（前 6）"), rows)


def sampling_table() -> str:
    """A real bounded payload, so the truncation contract is visible instead of described."""
    _CAPTURED.clear()
    lace = Lace.from_parametric(
        lambda t: (float(np.cos(t)), 0.6 * float(np.sin(2.0 * t))),
        (0.0, 2.0 * np.pi),
        offset=0.1,
        max_step=0.4,
        max_error=1e-4,
    )
    _CAPTURED.clear()
    summary = next(
        event.data for event in lace.result.trace if event.event_type == "sampling.subdivision"
    )
    rows = [
        (f"<code>{html.escape(str(key))}</code>", html.escape(str(value)))
        for key, value in summary.items()
        if key != "decisions"
    ]
    first = summary["decisions"][0] if summary["decisions"] else {}
    kept = len(summary["decisions"])
    body = _table(("sampling.subdivision 字段", "值"), rows)
    return (
        f"{body}<p class='hint'>decisions 首条：<code>{html.escape(json.dumps(first, ensure_ascii=False))}</code>"
        f"（共 {summary['decisions_count']} 条，列表保留 {kept} 条，"
        f"截断标记 {summary['decisions_truncated']}，"
        f"计数恒等式 node_count == split + accept + 触顶 + 丢弃 成立）</p>"
    )


def rosette_limits_table() -> str:
    """The real feasibility boundary of ``cal_kernels``, probed per ``(n, star_type)``.

    Odd ``n`` runs past the probe limit, so those cells mean "at least this many".
    """
    helpers = _rosette_helpers()
    rows = [
        (
            f"<code>{n}</code>",
            *[
                str(helpers.max_usable_level(n, star_type))
                for star_type in rosette_module.STAR_TYPE_VALUES
            ],
        )
        for n in (4, 5, 6, 7, 8, 10, 12)
    ]
    table = _table(("n", *rosette_module.STAR_TYPE_VALUES), rows)
    return (
        f"{table}<p class='hint'>单元格 = 该 (n, 花型) 的最大可用阶，由逐阶探测 <code>cal_kernels</code> 得到。"
        f"{helpers.LEVEL_PROBE_LIMIT} 表示顶到本表探测上限（即“至少这么多”）：奇数 n 的 PA/PO/PR 会顶到上限，"
        "CA/CR 仍在有限阶处终止；偶数 n 则全部有限。越界调用抛 <code>ValueError</code>，"
        "并在消息里给出该组合的最大可用阶。</p>"
    )


def diagnostic_table(collected: list[Collected]) -> str:
    seen: dict[str, dict[str, Any]] = {}
    for item in collected:
        for lace in item.laces:
            for diagnostic in lace.diagnostics:
                entry = seen.setdefault(diagnostic.code, {
                    "severity": diagnostic.severity.value,
                    "message": diagnostic.message,
                    "scenes": set(),
                })
                entry["scenes"].add(item.card.title)
    if not seen:
        return "<p>本次渲染的图案没有产生任何诊断。</p>"
    rows = [
        (
            f"<code>{html.escape(code)}</code>",
            html.escape(entry["severity"]),
            html.escape(entry["message"]),
            _code_cell(sorted(entry["scenes"])),
        )
        for code, entry in sorted(seen.items())
    ]
    return _table(("诊断码", "级别", "说明", "出现在"), rows)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_CSS = """
:root { --bg:#faf8f5; --card:#fff; --ink:#1a1a1a; --muted:#6b6b6b; --border:#e0ddd8; --accent:#b85450; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  background:var(--bg); color:var(--ink); line-height:1.6; }
header { text-align:center; padding:3rem 1.5rem 2rem; background:var(--card); border-bottom:1px solid var(--border); }
header h1 { font-size:2rem; font-weight:700; letter-spacing:.02em; }
header p { margin-top:.5rem; color:var(--muted); font-size:.95rem; }
.meta { margin-top:1rem; display:flex; justify-content:center; gap:.8rem; flex-wrap:wrap; }
.meta span { font-size:.8rem; color:var(--muted); background:var(--bg); padding:.25rem .7rem;
  border-radius:4px; border:1px solid var(--border); }
main { max-width:1200px; margin:0 auto; padding:2.5rem 1.5rem; }
h2 { font-size:1.35rem; margin:3rem 0 0; padding-bottom:.4rem; border-bottom:2px solid var(--border); }
h2 span { font-size:.85rem; font-weight:400; color:var(--muted); margin-left:.6rem; }
h2:first-of-type { margin-top:0; }
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:1.5rem; margin-top:1.5rem; }
.card { background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden;
  transition:box-shadow .2s, transform .15s; display:flex; flex-direction:column; }
.card:hover { box-shadow:0 4px 20px rgba(0,0,0,.08); transform:translateY(-2px); }
.card-img { background:#fff; padding:1rem; display:flex; align-items:center; justify-content:center;
  min-height:220px; cursor:zoom-in; }
.card-img img, .card-img video { max-width:100%; max-height:240px; object-fit:contain; }
.card-img img { transition:transform .15s; }
.card-img:hover img { transform:scale(1.03); }
.card-body { padding:1rem 1.2rem 1.2rem; border-top:1px solid var(--border); }
.card-body h3 { font-size:1.05rem; font-weight:600; }
.card-body p { margin-top:.3rem; font-size:.85rem; color:var(--muted); }
.card-body .note { margin-top:.5rem; font-size:.8rem; color:var(--ink); background:var(--bg);
  border-left:3px solid var(--accent); padding:.4rem .6rem; border-radius:0 4px 4px 0; }
.tags { margin-top:.5rem; display:flex; gap:.4rem; flex-wrap:wrap; }
.tag { font-size:.72rem; padding:.1rem .5rem; border-radius:3px; background:var(--bg);
  border:1px solid var(--border); color:var(--muted); }
.tag.warn { color:#8a5a00; border-color:#e8d9b5; background:#fdf6e6; }
table.data { width:100%; border-collapse:collapse; margin-top:1.2rem; font-size:.85rem;
  background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden; }
table.data th, table.data td { padding:.45rem .7rem; text-align:left; border-bottom:1px solid var(--border);
  vertical-align:top; }
table.data th { background:var(--bg); font-weight:600; font-size:.8rem; color:var(--muted); }
table.data tr:last-child td { border-bottom:none; }
.codes, table.data code { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:.78rem; }
.hint { margin-top:.6rem; font-size:.8rem; color:var(--muted); }
.hint code { background:var(--bg); padding:.1rem .35rem; border-radius:3px; }
.palette { background:var(--card); border:1px solid var(--border); border-radius:8px;
  padding:.9rem 1rem; margin-top:1rem; }
.palette-head { font-size:.95rem; display:flex; align-items:center; gap:.5rem; }
.palette-head .paper { width:16px; height:16px; border:1px solid var(--border); border-radius:3px;
  display:inline-block; }
.palette-head em { font-style:normal; font-size:.75rem; color:var(--muted); }
.palette p { margin-top:.45rem; font-size:.8rem; color:var(--muted); }
.chips { display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.6rem; }
.chip { display:flex; flex-direction:column; align-items:center; justify-content:flex-end;
  width:84px; height:58px; border-radius:5px; border:1px solid var(--border); padding-bottom:2px;
  font-size:.62rem; color:#111; text-shadow:0 0 3px rgba(255,255,255,.85); }
.chip b { font-weight:600; }
.chip i { font-style:normal; opacity:.75; font-size:.58rem; }
footer { text-align:center; padding:2rem 1.5rem; color:var(--muted); font-size:.82rem;
  border-top:1px solid var(--border); }
footer a { color:var(--accent); text-decoration:none; }
footer a:hover { text-decoration:underline; }
footer code { background:var(--bg); padding:.1rem .35rem; border-radius:3px; }
.lightbox { display:none; position:fixed; inset:0; z-index:1000; background:rgba(20,18,16,.92);
  justify-content:center; align-items:center; cursor:zoom-out; backdrop-filter:blur(4px); }
.lightbox.open { display:flex; }
.lightbox img { max-width:92vw; max-height:90vh; object-fit:contain; border-radius:4px;
  box-shadow:0 8px 40px rgba(0,0,0,.4); }
.lightbox-caption { position:fixed; bottom:0; left:0; right:0; text-align:center; padding:.8rem 1.5rem;
  color:#ddd; font-size:.9rem; background:rgba(0,0,0,.5); }
.lightbox-hint { position:fixed; top:1rem; right:1.5rem; color:#aaa; font-size:.8rem; }
"""

_SCRIPT = """
(function () {
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lightbox-img');
  var lbCap = document.getElementById('lightbox-caption');
  document.querySelectorAll('.card-img').forEach(function (el) {
    el.addEventListener('click', function () {
      var img = el.querySelector('img');
      if (!img) return;
      lbImg.src = img.src;
      var body = el.parentElement.querySelector('.card-body');
      var h3 = body && body.querySelector('h3');
      var p = body && body.querySelector('p');
      lbCap.textContent = (h3 ? h3.textContent : '') + (p ? ' — ' + p.textContent : '');
      lb.classList.add('open');
    });
  });
  lb.addEventListener('click', function () { lb.classList.remove('open'); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') lb.classList.remove('open'); });
})();
"""


def _card_html(item: Collected) -> str:
    card = item.card
    if card.media == "video":
        media = f'<video src="{card.key}.mp4" controls preload="metadata" muted></video>'
    else:
        media = f'<img src="{card.key}.png" alt="{html.escape(card.title)}">'
    tags = list(card.tags)
    metrics = item.metrics
    if metrics.get("laces"):
        tags.append(f"{metrics['crossings']} 交叉")
        unit = "可见区域" if "ribbon" in metrics["modes"] else "可见片段"
        tags.append(f"{metrics['visible']} 个{unit}")
        tags.extend(f"{backend} 后端" for backend in metrics["backends"])
    badges = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in tags)
    warnings = "".join(
        f'<span class="tag warn">{html.escape(code)}</span>'
        for code in sorted(metrics.get("diagnostics", {}))
    )
    note = f'<div class="note">{html.escape(item.note)}</div>' if item.note else ""
    return (
        f'<div class="card"><div class="card-img">{media}</div>'
        f'<div class="card-body"><h3>{html.escape(card.title)}</h3>'
        f"<p>{html.escape(card.blurb)}</p>{note}"
        f'<div class="tags">{badges}{warnings}</div></div></div>'
    )


def write_page(collected: list[Collected], *, quality: str, rendered_now: bool) -> Path:
    by_key = {item.card.key: item for item in collected}
    blocks: list[str] = []
    for section in SECTIONS:
        items = [by_key[card.key] for card in section.cards if card.key in by_key]
        blocks.append(f"<h2>{html.escape(section.title)}<span>{html.escape(section.subtitle)}</span></h2>")
        if section.key == "backend":
            # One table for the whole section, so the sub-backends can be compared row
            # by row (including the areas each of them hid).
            entries = [
                (item.card.title, lace)
                for item in items
                for lace in item.laces
                if lace.render_mode == "ribbon"
            ]
            if entries:
                blocks.append(backend_table(entries))
        if section.key == "rosette":
            blocks.append(rosette_limits_table())
        if section.key == "style":
            blocks.append(palette_table())
        if section.key == "trace":
            blocks.append(sampling_table())
            # The trace table covers every channel: the animation scenes (stroke) plus the
            # backend comparison (ribbon), so the region events are represented too.
            trace_keys = [
                card.key
                for source in (SECTION_BY_KEY["backend"], section)
                for card in source.cards
            ]
            trace_laces = [
                lace for key in trace_keys if key in by_key for lace in by_key[key].laces
            ]
            if trace_laces:
                blocks.append(trace_table(trace_laces))
        blocks.append(
            '<div class="gallery">' + "".join(_card_html(item) for item in items) + "</div>"
        )
    blocks.append("<h2>诊断与诚实降级<span>本次渲染的图案实际触发的诊断码</span></h2>")
    blocks.append(diagnostic_table(collected))

    meta = [
        f"manim-lace {manim_lace.__version__}",
        f"Manim CE {manim.__version__}",
        f"配色 {len(palette_module.palette_names())} 套 / 色卡 {len(palette_module.SWATCHES)} 色",
        "后端 stroke / ribbon(boolean) / ribbon(arrangement)",
        f"本次渲染质量 {quality.upper()}" if rendered_now else "复用上次媒体，数据已重算",
    ]
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manim-Lace 状态画廊</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Manim-Lace 状态画廊</h1>
  <p>每个图案都由当前代码实机渲染，每个数字都读自同一次求解真实产生的对象</p>
  <div class="meta">{''.join(f'<span>{html.escape(item)}</span>' for item in meta)}</div>
</header>
<main>
{chr(10).join(blocks)}
</main>
<footer>
  <p>由 <a href="https://github.com/ManimCommunity/Manim">Manim CE {manim.__version__}</a> + <strong>manim-lace</strong> 渲染生成</p>
  <p>本页与所有媒体都是生成物，位于 <code>media/gallery/</code>（该目录不入库）</p>
  <p>重新生成：<code>python examples/build_gallery.py</code> ·
     只重算数据：<code>python examples/build_gallery.py --no-render</code> ·
     单图：<code>manim -s -qh examples/scene_gallery.py &lt;ClassName&gt;</code></p>
</footer>
<div class="lightbox" id="lightbox">
  <div class="lightbox-hint">点击任意处关闭 · ESC</div>
  <img id="lightbox-img" src="" alt="">
  <div class="lightbox-caption" id="lightbox-caption"></div>
</div>
<script>{_SCRIPT}</script>
</body>
</html>
"""
    target = PAGE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build media/gallery/index.html from the current code")
    parser.add_argument("-q", "--quality", choices=tuple(_QUALITY), default="h",
                        help="still quality preset l/m/h/k (default h; videos are always low)")
    parser.add_argument("--no-render", action="store_true",
                        help="reuse the media on disk, recompute only the data and the page")
    parser.add_argument("--skip-videos", action="store_true", help="keep existing videos")
    parser.add_argument("--only", default="", help="comma separated scene names to render")
    args = parser.parse_args(argv)
    wanted = {name.strip() for name in args.only.split(",") if name.strip()}

    collected: list[Collected] = []
    try:
        for card in ALL_CARDS:
            item = _collect(card)
            collected.append(item)
            if wanted and card.scene not in wanted:
                continue
            if card.media == "video" and args.skip_videos:
                continue
            if not args.no_render:
                _render(card, args.quality)
                item.rendered = True
            summary = " / ".join(
                part
                for part in (
                    f"{item.metrics['laces']} lace" if item.metrics["laces"] else "",
                    f"{len(item.metrics['rosettes'])} rosette" if item.metrics["rosettes"] else "",
                    f"{item.metrics['crossings']} 交叉" if item.metrics["crossings"] else "",
                    f"{item.metrics['visible']} 可见面" if item.metrics["visible"] else "",
                )
                if part
            )
            print(
                f"[gallery] {card.scene:22s} {'渲染' if item.rendered else '复用'}  "
                f"{summary or '纯文本场景'}"
            )
    finally:
        Lace.__init__ = _ORIGINAL_INIT  # type: ignore[method-assign]
        Lace._from_engine = classmethod(_ORIGINAL_FROM_ENGINE)  # type: ignore[method-assign]
        shutil.rmtree(SCRATCH, ignore_errors=True)
    target = write_page(collected, quality=args.quality, rendered_now=not args.no_render)
    print(f"[gallery] 写入 {target}（{len(collected)} 张卡片）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
