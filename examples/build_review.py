"""Render the human review page into ``media/review/`` from the case catalog.

Usage:

    python examples/build_review.py                    # render every case, write the page
    python examples/build_review.py --probe            # measure only: no rendering, no page
    python examples/build_review.py -q l               # faster / smaller renders
    python examples/build_review.py --category rosette --category degenerate
    python examples/build_review.py --cases deg-bow,spec-simple
    python examples/build_review.py --no-render        # reuse the media on disk
    python examples/build_review.py --verdicts docs/review-verdicts.json   # bake in past verdicts

Why a second page next to ``media/gallery/index.html``: the status gallery shows the
patterns the project is proud of, in their published styling. This one shows *test and
benchmark geometry*, in one uniform style across the stroke, boolean and arrangement
channels, and it asks a person to sign off on each case.

Every case therefore carries two verdicts:

* **程序判定** — measured facts and invariants (``examples/review_checks.py``): crossing
  counts by kind, self-crossings, alternation defects, over/under sources, region and
  hole accounting, ring validity, the weave defect signatures from
  ``benchmarks/weave_audit.py``, and a solve-twice determinism check. Failing checks are
  expanded; passing ones are collapsible.
* **人眼审核** — 通过 / 存疑 / 有问题, a defect tag vocabulary and a free-text note, saved
  in the browser and exportable as JSON.

Neither replaces the other, which is the point: a check can only catch what it was
written to catch, and the page keeps the failing check, the silently-passing one and the
human note side by side. The toolbar can filter straight to "程序通过但人审有问题", the
list where the checks are *missing* something.

The output lives under ``media/`` (the generated-data directory the repository ignores),
so re-running never leaves untracked files in ``examples/``. To keep a review round in
version control, export the verdicts from the page into a tracked path and pass it back
with ``--verdicts``; the page then opens with that round already loaded.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import html
import json
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

EXAMPLES = Path(__file__).resolve().parent
ROOT = EXAMPLES.parent
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import manim  # noqa: E402
from manim import Dot, Scene, Text, VGroup, config, tempconfig  # noqa: E402
from review_catalog import (  # noqa: E402
    CASES,
    CATEGORIES,
    CATEGORY_BY_KEY,
    Case,
    cases_for,
    catalog_stats,
    source_engine_kwargs,
)
from review_checks import collect_verdict, ensure_audit_probe  # noqa: E402

import manim_lace  # noqa: E402
from manim_lace import Lace  # noqa: E402
from manim_lace.manim_api import _polyline_to_vmobject  # noqa: E402
from manim_lace.render.pixels import px_to_stroke_width  # noqa: E402

MEDIA = ROOT / "media" / "review"
PAGE = MEDIA / "index.html"
SCRATCH = ROOT / "media" / "_review_build"

QUALITY = {"l": "low_quality", "m": "medium_quality", "h": "high_quality", "k": "fourk_quality"}
PIXEL_HEIGHT = {"l": 480, "m": 720, "h": 1080, "k": 2160}

#: One uniform style for every case, so its declared channels are comparable and two cases
#: can be compared without mentally discounting a colour choice. Strands take a palette
#: colour per path because the ribbon channels show their cut *only* as a colour change.
RIBBON_STYLE: dict[str, Any] = {
    "palette": "natsu",
    "fill_opacity": 1.0,
    "hole_color": "#ffffff",
    "draw_holes": True,
    "stroke_color": "#000000",
    "stroke_width_px": 2.0,
}
STROKE_STYLE: dict[str, Any] = {
    "palette": "natsu",
    "stroke_color": "#000000",
    "stroke_width_px": 3.0,
    "stroke_opacity": 1.0,
}

#: Crossing counts above which the annotation layer drops the ID text (dots only) or
#: gives up: labels stop meaning anything long before 70 crossings.
ANNOTATE_LABELS_MAX = 30
ANNOTATE_DOTS_MAX = 200
#: ``z_index`` of the annotation layer. Region fills use their painter order as z_index, so
#: the markers have to sit clearly above every fill and outline to be visible at all.
ANNOTATE_Z = 1000
#: Thickness of the raw-input centerline in output pixels (converted per render, so the
#: panel reads the same at any ``-q``).
RAW_INPUT_PX = 2.4


# ---------------------------------------------------------------------------
# Building one case in one channel
# ---------------------------------------------------------------------------


def channel_plan(case: Case) -> tuple[tuple[str, str], ...]:
    """``(channel, backend)`` pairs to build for a case.

    ``stroke`` has no ribbon backend; ribbon channels name the backend they run
    (``boolean`` / ``arrangement`` / experimental ``hybrid``).
    A case may omit channels it cannot afford (``Case.omitted``), which the page then
    shows explicitly with the measured reason instead of quietly drawing fewer panels.
    """
    if case.kind == "error":
        return ()
    skip = {channel for channel, _reason in case.omitted}
    return tuple(
        (channel, "boolean" if channel == "stroke" else channel)
        for channel in case.channels
        if channel not in skip
    )


def omitted_channels(case: Case) -> tuple[tuple[str, str], ...]:
    """The channels a case declares it does not run, with their reasons."""
    return case.omitted


def build_lace(case: Case, channel: str) -> Lace:
    """Build one case/channel pair with the review page's uniform style."""
    source = case.source()
    offset = case.offset if source.offset is None else float(source.offset)
    weave_mode = case.weave_mode if source.weave_mode is None else str(source.weave_mode)
    render = "stroke" if channel == "stroke" else "ribbon"
    style = STROKE_STYLE if render == "stroke" else RIBBON_STYLE
    kwargs: dict[str, Any] = {
        "offset": offset,
        "render": render,
        "weave_mode": weave_mode,
        "ribbon_backend": "boolean" if channel == "stroke" else channel,
        **case.engine,
        **style,
    }
    if source.sampling_trace:
        # A source that sampled its own curve (the implicit isocontour extractor) hands its
        # summaries to the engine exactly as ``from_implicit`` does, through the catalog's
        # single definition of what a source implies — so this and the tests' solver stay in
        # step. Without it, the sampler's warnings (a missed error target, an ambiguous
        # saddle) would be dropped for every case built from pre-sampled paths.
        kwargs.update(source_engine_kwargs(source))
    if source.paths is not None:
        return Lace.from_paths(source.paths, **kwargs)
    return Lace(source.mobject, **kwargs)


def probe_error(case: Case) -> str | None:
    """The error a case is required to raise, exactly as the caller would see it."""
    try:
        build_lace(case, case.channels[0])
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


@dataclass
class CaseMeasurement:
    """Everything the page knows about one case: per-channel verdicts and expectations."""

    case: Case
    channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None
    expectation: dict[str, Any] = field(default_factory=dict)
    window: tuple[float, float, np.ndarray] | None = None


def _crossing_ids(lace: Lace) -> list[str]:
    return [crossing.crossing_id for crossing in lace.crossings]


def measure_case(case: Case, *, audit: bool = True, determinism: bool = True) -> CaseMeasurement:
    """Solve every channel of a case and collect the programmatic verdicts."""
    measurement = CaseMeasurement(case=case)
    if case.kind == "error":
        measurement.error = probe_error(case)
        measurement.expectation = _expectations(measurement)
        return measurement
    if audit:
        # The weave audit records what ``mark_flush_edges`` was called with at solve time,
        # so its probe has to be installed before the first build, not when the checks run.
        with contextlib.suppress(Exception):  # pragma: no cover - audit is a dev tool
            ensure_audit_probe()
    for index, (channel, backend) in enumerate(channel_plan(case)):
        solve_started = time.perf_counter()
        lace = build_lace(case, channel)
        solve_seconds = time.perf_counter() - solve_started
        if measurement.window is None:
            measurement.window = frame_window(lace.paths, lace.offset, case.focus)
        verdict = collect_verdict(
            lace.result,
            backend=backend,
            # The solve-twice check is a property of the case, not of one backend, and it
            # doubles the cost of the heaviest inputs: run it on the first channel only.
            rebuild=(
                (lambda channel=channel: build_lace(case, channel))
                if determinism and index == 0
                else None
            ),
            audit=audit and channel != "stroke",
            solve_seconds=solve_seconds,
        )
        verdict["channel"] = channel
        verdict["backend"] = backend
        verdict["crossing_ids"] = _crossing_ids(lace)
        verdict["measured_note"] = _measured_note(lace, channel)
        measurement.channels[channel] = verdict
    measurement.expectation = _expectations(measurement)
    return measurement


def _measured_note(lace: Lace, channel: str) -> str:
    """One sentence per channel, read from the object that was just solved."""
    units = "可见片段" if lace.render_mode == "stroke" else "可见区域"
    codes = sorted({diagnostic.code for diagnostic in lace.diagnostics})
    tail = f"；诊断 {'、'.join(codes)}" if codes else "；0 诊断"
    return f"{channel}：{len(lace.crossings)} 交叉 / {len(lace.result.pieces)} 个{units}{tail}"


def _expectations(measurement: CaseMeasurement) -> dict[str, Any]:
    """Compare what the catalog said about the case against what was measured."""
    case = measurement.case
    issues: list[str] = []
    if case.kind == "error":
        if measurement.error is None:
            issues.append("本案例应当报错，但没有抛出任何异常")
        elif case.expect_error and case.expect_error not in measurement.error:
            issues.append(f"错误文本不含 {case.expect_error!r}：{measurement.error}")
        return {"ok": not issues, "issues": issues,
                "measured": {"error": measurement.error}}

    crossings = {channel: data["facts"]["crossings"]
                 for channel, data in measurement.channels.items()}
    self_crossings = {channel: data["facts"]["self_crossings"]
                      for channel, data in measurement.channels.items()}
    codes = {
        channel: {diagnostic["code"] for diagnostic in data["diagnostics"]}
        for channel, data in measurement.channels.items()
    }
    reference = next(iter(crossings.values()), 0)
    if len(set(crossings.values())) > 1:
        issues.append(
            "各通道报告的交叉数不一致：" + "、".join(f"{c}={n}" for c, n in crossings.items())
            + "（FR-040 要求共享同一份拓扑）"
        )
    if case.expect_crossings is not None and reference != case.expect_crossings:
        issues.append(f"预期 {case.expect_crossings} 个交叉，实测 {reference}")
    if case.expect_min_crossings is not None and reference < case.expect_min_crossings:
        issues.append(f"预期至少 {case.expect_min_crossings} 个交叉，实测 {reference}")
    if case.expect_self_crossings is not None:
        measured_self = next(iter(self_crossings.values()), 0)
        if measured_self != case.expect_self_crossings:
            issues.append(f"预期 {case.expect_self_crossings} 处自交，实测 {measured_self}")
    for code in case.expect_diagnostics:
        if not any(code in found for found in codes.values()):
            issues.append(f"预期诊断 {code} 未出现")
    if case.expect_any_diagnostics:
        if not any(
            code in found
            for found in codes.values()
            for code in case.expect_any_diagnostics
        ):
            issues.append(
                "预期至少出现其中之一："
                + "、".join(case.expect_any_diagnostics)
                + f"，实测 {sorted({code for found in codes.values() for code in found})}"
            )
    for code in case.forbid_diagnostics:
        offenders = [channel for channel, found in codes.items() if code in found]
        if offenders:
            issues.append(f"不允许出现 {code}，却出现在 {'、'.join(offenders)}")
    return {
        "ok": not issues,
        "issues": issues,
        "measured": {
            "crossings": crossings,
            "self_crossings": self_crossings,
            "diagnostics": {channel: sorted(found) for channel, found in codes.items()},
        },
    }


def channel_agreement(measurement: CaseMeasurement) -> dict[str, Any]:
    """Whether the channels agree on topology — the one thing they must never differ on."""
    if len(measurement.channels) < 2:
        return {"ok": True, "detail": "只有一个通道，无需比对"}
    facts = {channel: data["facts"] for channel, data in measurement.channels.items()}
    counts = {channel: fact["crossings"] for channel, fact in facts.items()}
    sources = {channel: fact["sources"] for channel, fact in facts.items()}
    kinds = {channel: fact["kinds"] for channel, fact in facts.items()}
    agreed = len({json.dumps(counts, sort_keys=True)}) == 1 \
        and len({json.dumps(sources, sort_keys=True)}) == 1 \
        and len({json.dumps(kinds, sort_keys=True)}) == 1
    return {
        "ok": agreed,
        "detail": (
            "、".join(f"{channel}:{count}" for channel, count in counts.items())
            if agreed else
            "交叉数/事件类型/上下关系来源不一致：" + json.dumps(
                {"crossings": counts, "sources": sources, "kinds": kinds},
                ensure_ascii=False,
            )
        ),
    }


# ---------------------------------------------------------------------------
# Framing (translate to the origin, then set the camera window — never scale)
# ---------------------------------------------------------------------------

#: The render aspect; every case is framed at this ratio so pages of images line up.
ASPECT = 16.0 / 9.0


def frame_window(
    paths: list[Any], offset: float, focus: tuple[float, float, float] | None = None
) -> tuple[float, float, np.ndarray]:
    """The camera window a case needs, plus the shift that brings it to the origin.

    Scaling a mobject would change the geometry but leave stroke widths alone, which is
    why the gallery has a ``StrokePanel.refit`` and why this page does not scale at all:
    the window moves instead. A pure translation leaves every width untouched, so the
    stroke and ribbon panels of one case show the same strand thickness.

    ``focus`` overrides the window with an explicit ``(centre_x, centre_y, span)`` for
    cases whose interesting geometry is tiny compared to their extent.
    """
    if focus is not None:
        centre = np.array([float(focus[0]), float(focus[1])])
        width = float(focus[2]) * ASPECT
        return width, float(focus[2]), centre
    points = np.vstack([np.asarray(path.points, dtype=float)[:, :2] for path in paths])
    low, high = points.min(axis=0), points.max(axis=0)
    centre = 0.5 * (low + high)
    span = (high - low) + 4.0 * offset
    width = float(max(span[0], span[1] * ASPECT)) * 1.12
    return width, width / ASPECT, centre


def annotation_layers(lace: Lace, window: tuple[float, float, np.ndarray]) -> tuple[list[Any], bool]:
    """Crossing markers: dots always, ID labels while there are few enough to read."""
    _width, height, _centre = window
    unit = height / 720.0
    dot_radius = 3.2 * unit
    font_size = float(np.clip(90.0 * unit, 5.0, 34.0))
    dots = VGroup()
    for crossing in lace.crossings:
        dot = Dot(
            point=np.array([crossing.point[0], crossing.point[1], 0.0]),
            radius=dot_radius,
            color="#d02020",
        )
        dots.add(dot)
    if not dots:
        return [], False
    # Region fills carry their own ``z_index`` (the painter order), so a marker at the
    # default 0 is painted over exactly at a crossing — the one place it is needed.
    dots.set_z_index(ANNOTATE_Z)
    layers: list[Any] = [dots]
    with_labels = len(lace.crossings) <= ANNOTATE_LABELS_MAX
    if with_labels:
        labels = VGroup()
        for crossing in lace.crossings:
            labels.add(Text(crossing.crossing_id, font_size=font_size, color="#d02020")
                       .move_to(np.array([crossing.point[0], crossing.point[1], 0.0]))
                       .shift(np.array([0.0, 4.5 * unit + 0.5 * font_size / 90.0, 0.0])))
        labels.set_z_index(ANNOTATE_Z + 1)
        layers.append(labels)
    return layers, with_labels


def _piece_object_id(piece: Any) -> str:
    """The stable ID of a stroke piece or a ribbon region (mirrors the facade's helper)."""
    identifier = getattr(piece, "piece_id", None) or getattr(piece, "region_id", None)
    if identifier is None:
        raise ValueError(f"piece without piece_id/region_id: {type(piece).__name__}")
    return str(identifier)


def source_layer(lace: Lace, window: tuple[float, float, np.ndarray]) -> Any:
    """The raw input: the centerlines the engine was handed, in their strand colours.

    Every other panel shows a *result*; this one shows what went in, so a reviewer can tell
    "the engine saw the wrong geometry" apart from "the engine wove it wrong". The colours
    come from the same style plan the woven panels use — taken per piece and mapped back to
    its path — so a strand keeps one colour across all four panels.

    The line width is a fixed number of output pixels (the repo's own pixel conversion),
    not a world-space width: the raw input has no ribbon width, and a fixed on-screen
    thickness is what makes the panel readable at any zoom.
    """
    plan = lace.style_plan
    colors: dict[str, str] = {}
    if plan is not None:
        for piece in lace.result.pieces:
            if piece.path_id not in colors:
                assignment = plan.assignment_for(_piece_object_id(piece))
                if assignment is not None:
                    colors[piece.path_id] = assignment.color
    _width, height, _centre = window
    stroke = px_to_stroke_width(
        RAW_INPUT_PX, pixel_height=int(config.pixel_height), frame_height=height
    )
    group = VGroup()
    for path in lace.paths:
        line = _polyline_to_vmobject(np.asarray(path.points, dtype=float), closed=path.closed)
        line.set_stroke(color=colors.get(path.path_id, "#4a4a4a"), width=stroke, opacity=1.0)
        group.add(line)
    group.set_z_index(ANNOTATE_Z - 1)
    return group


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _scene_for(
    case: Case,
    channel: str | None,
    window: tuple[float, float, np.ndarray],
) -> type[Scene]:
    """A one-shot scene class for a case, named uniquely so Manim writes distinct files.

    Three kinds of panel come out of here: a weave backend (``stroke``/``boolean``/
    ``arrangement``), the raw input (``channel="input"``: the centerlines the engine was
    handed, with the crossings it found on them) and the annotated view (``channel=None``:
    the same markers over the woven result).
    """
    width, height, centre = window
    shift = -np.array([float(centre[0]), float(centre[1]), 0.0])
    name = f"Review_{case.key.replace('-', '_')}_{channel or 'annotate'}"

    def construct(self: Scene) -> None:
        self.camera.background_color = "#ffffff"
        if channel == "input":
            # The raw input needs a solved case only for its paths, style and crossings; the
            # geometry drawn is the input, not the result.
            lace = build_lace(case, annotate_base(case))
            group = source_layer(lace, window)
            layers, _labelled = annotation_layers(lace, window)
            for layer in layers:
                group.add(layer)
        else:
            lace = build_lace(case, channel or annotate_base(case))
            group = lace.ribbons.copy()
            if lace.render_mode == "ribbon":
                group.add(*lace.outlines)
            if channel is None:
                layers, _labelled = annotation_layers(lace, window)
                for layer in layers:
                    group.add(layer)
        group.shift(shift)
        self.add(group)

    return type(name, (Scene,), {"construct": construct})


def annotate_base(case: Case) -> str:
    """Which channel the annotated view is drawn over.

    A ribbon channel when the case has one that this round actually runs, because the
    crossing markers are there to be read against the cut geometry, and the annotated view
    should not silently be the one channel whose cuts are drawn as strokes. Channels the
    case omits are excluded: asking for ``boolean`` here put the pathological backend back
    into the build on exactly the cases that omit it (measured: the annotate render of
    ``index-random-walks-6`` was the 1.2GB one).
    """
    plan = [channel for channel, _backend in channel_plan(case)]
    ribbon = [channel for channel in plan if channel != "stroke"]
    return ribbon[0] if ribbon else plan[0]


def render_case(
    case: Case,
    channel: str | None,
    window: tuple[float, float, np.ndarray],
    *,
    quality: str,
) -> Path:
    """Render one channel (or the annotated view) and copy it next to the page."""
    width, height, _centre = window
    scene_class = _scene_for(case, channel, window)
    options = {
        "quality": QUALITY[quality],
        "format": "png",
        "save_last_frame": True,
        "media_dir": str(SCRATCH),
        "verbosity": "ERROR",
        "disable_caching": True,
        "progress_bar": "none",
        "frame_width": width,
        "frame_height": height,
    }
    suffix = channel or "annotate"
    with tempconfig(options):
        scene_class().render()
    produced = sorted(SCRATCH.rglob("*.png"), key=lambda path: path.stat().st_mtime)
    if not produced:
        raise RuntimeError(f"rendering {case.key}/{suffix} produced no png under {SCRATCH}")
    MEDIA.mkdir(parents=True, exist_ok=True)
    target = MEDIA / f"{case.key}__{suffix}.png"
    shutil.copyfile(produced[-1], target)
    return target


def channels_to_render(measurement: CaseMeasurement) -> list[str]:
    """Which images a case gets: its channels, plus an annotated view when it helps."""
    if measurement.case.kind == "error" or not measurement.channels:
        return []
    # The raw input comes first: a reviewer reads the row left to right as "what went in →
    # what the declared channels made of it → where the crossings ended up".
    channels = ["input", *[channel for channel, _backend in channel_plan(measurement.case)]]
    crossings = next(
        (data["facts"]["crossings"] for data in measurement.channels.values()), 0
    )
    if measurement.case.annotate and crossings <= ANNOTATE_DOTS_MAX:
        channels.append("annotate")
    return channels


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_CSS = """
:root { --bg:#f6f4f1; --card:#fff; --ink:#191919; --muted:#6d6d6d; --border:#e2ded9;
  --accent:#b85450; --pass:#1f7a4d; --fail:#c02b1f; --info:#5b6b7c; --warn:#a8741a;
  --maybe:#b06f00; }
* { margin:0; padding:0; box-sizing:border-box; }
.hidden { display:none !important; }
body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  background:var(--bg); color:var(--ink); line-height:1.6; }
header { padding:2.2rem 1.5rem 1.6rem; background:var(--card); border-bottom:1px solid var(--border); }
header h1 { font-size:1.7rem; font-weight:700; }
header p { margin-top:.4rem; color:var(--muted); font-size:.9rem; max-width:70rem; }
.meta { margin-top:.9rem; display:flex; gap:.6rem; flex-wrap:wrap; }
.meta span { font-size:.76rem; color:var(--muted); background:var(--bg); padding:.2rem .6rem;
  border-radius:4px; border:1px solid var(--border); }
main { max-width:1500px; margin:0 auto; padding:1.2rem 1.5rem 4rem; }

/* ---- sticky review toolbar ---- */
.toolbar { position:sticky; top:0; z-index:50; background:rgba(255,255,255,.96);
  backdrop-filter:blur(6px); border-bottom:1px solid var(--border); margin:0 -1.5rem 1.2rem;
  padding:.7rem 1.5rem; display:flex; gap:.9rem; align-items:center; flex-wrap:wrap; }
.toolbar label { font-size:.78rem; color:var(--muted); display:flex; gap:.35rem;
  align-items:center; }
.toolbar select, .toolbar input[type=search] { font:inherit; font-size:.8rem; padding:.25rem .5rem;
  border:1px solid var(--border); border-radius:5px; background:var(--card); color:var(--ink); }
.toolbar input[type=search] { width:13rem; }
.btn { font:inherit; font-size:.78rem; padding:.28rem .7rem; border-radius:5px;
  border:1px solid var(--border); background:var(--card); color:var(--ink); cursor:pointer; }
.btn:hover { border-color:var(--accent); color:var(--accent); }
.btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.btn.primary:hover { filter:brightness(1.08); color:#fff; }
.progress { margin-left:auto; display:flex; gap:.6rem; align-items:center; font-size:.78rem;
  color:var(--muted); }
.store { font-size:.74rem; padding:.2rem .55rem; border-radius:4px; border:1px solid var(--border);
  background:var(--bg); color:var(--muted); }
.store.ok { color:var(--pass); border-color:#bfdccb; background:#f1f9f4; }
.store.warn { color:var(--warn); border-color:#e8d9b5; background:#fdf6e6; }
.paste-panel { background:var(--card); border:1px solid var(--border); border-radius:8px;
  padding:.8rem 1rem; margin:0 0 1.2rem; }
.paste-hint { font-size:.78rem; color:var(--muted); margin-bottom:.5rem; }
.paste-panel textarea { font-family:ui-monospace,Consolas,monospace; font-size:.74rem;
  min-height:6rem; }
.paste-actions { display:flex; gap:.5rem; align-items:center; margin-top:.5rem; flex-wrap:wrap; }
.paste-preview { font-size:.74rem; color:var(--muted); }
.paste-preview.ok { color:var(--pass); }
.paste-preview.warn { color:var(--warn); }
.paste-preview.bad { color:var(--fail); }
.btn[disabled] { opacity:.5; cursor:not-allowed; }
.progress b { color:var(--ink); }
.bar { width:9rem; height:.5rem; border-radius:99px; background:var(--border); overflow:hidden;
  display:flex; }
.bar i { display:block; height:100%; }
.bar .p { background:var(--pass); } .bar .m { background:var(--maybe); }
.bar .f { background:var(--fail); }

/* ---- sections and cards ---- */
h2 { font-size:1.25rem; margin:2.6rem 0 .2rem; padding-bottom:.35rem;
  border-bottom:2px solid var(--border); }
h2 span { font-size:.8rem; font-weight:400; color:var(--muted); margin-left:.6rem; }
h2:first-of-type { margin-top:.5rem; }
.cat-what { font-size:.82rem; color:var(--muted); margin:.6rem 0 0; max-width:80rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(560px,1fr)); gap:1.3rem;
  margin-top:1.1rem; }
.card { background:var(--card); border:1px solid var(--border); border-radius:8px;
  overflow:hidden; display:flex; flex-direction:column; }
.card.hidden { display:none; }
.card-head { padding:.85rem 1rem .5rem; display:flex; gap:.6rem; align-items:baseline; }
.card-head h3 { font-size:1rem; font-weight:600; }
.card-head code { font-size:.72rem; color:var(--muted); }
.card-head .focus { margin-left:auto; }
.card p.prose { padding:0 1rem; font-size:.82rem; color:var(--muted); }
.card .look { margin:.5rem 1rem 0; font-size:.8rem; background:#fff8ec; border-left:3px solid
  var(--warn); padding:.35rem .6rem; border-radius:0 4px 4px 0; color:var(--ink); }
.shots { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.4rem;
  padding:.7rem 1rem 0; }
.shot { border:1px solid var(--border); border-radius:6px; overflow:hidden; background:#fff; }
.shot img { display:block; width:100%; cursor:zoom-in; background:#fff; }
.shot figcaption { font-size:.7rem; color:var(--muted); text-align:center; padding:.15rem 0 .25rem;
  border-top:1px solid var(--border); background:var(--bg); }
.shot.missing { display:flex; align-items:center; justify-content:center; min-height:8rem;
  color:var(--muted); font-size:.75rem; }

.panel { padding:.6rem 1rem .3rem; }
.panel h4 { font-size:.74rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:.5rem 0 .3rem; }
.chips { display:flex; gap:.35rem; flex-wrap:wrap; }
.chip { font-size:.72rem; padding:.08rem .45rem; border-radius:3px; background:var(--bg);
  border:1px solid var(--border); color:var(--muted); }
.chip.pass { color:var(--pass); border-color:#bfdccb; background:#f1f9f4; }
.chip.fail { color:#fff; background:var(--fail); border-color:var(--fail); font-weight:600; }
.chip.info { color:var(--info); border-color:#ccd6e0; background:#f3f6f9; }
.chip.warn { color:var(--warn); border-color:#e8d9b5; background:#fdf6e6; }
.chip.error { color:#fff; background:#a02020; border-color:#a02020; }
.checks { font-size:.78rem; }
.checks .row { display:flex; gap:.5rem; padding:.18rem 0; border-bottom:1px dashed var(--border); }
.checks .row:last-child { border-bottom:none; }
.checks .st { flex:0 0 3.1rem; font-size:.68rem; text-align:center; border-radius:3px;
  height:1.05rem; line-height:1.05rem; }
.checks .st.pass { color:var(--pass); background:#f1f9f4; }
.checks .st.fail { color:#fff; background:var(--fail); }
.checks .st.warn { color:#fff; background:var(--warn); }
.checks .st.info { color:var(--info); background:#f3f6f9; }
.checks .st.skip { color:var(--muted); background:var(--bg); }
.checks .k { flex:0 0 15rem; color:var(--ink); }
.checks .d { color:var(--muted); font-family:ui-monospace,Consolas,monospace; font-size:.7rem; }
details summary { cursor:pointer; font-size:.75rem; color:var(--muted); margin-top:.25rem; }
.expect { margin:.5rem 1rem .2rem; font-size:.78rem; border-radius:5px; padding:.4rem .6rem;
  color:var(--ink); }
.expect.ok { background:#f1f9f4; border-left:3px solid var(--pass); }
.expect.bad { background:#fdf1ef; border-left:3px solid var(--fail); }
.expect b { color:var(--ink); }
.review { margin:.6rem 1rem 1rem; border-top:1px solid var(--border); padding-top:.6rem; }
.review .verdicts { display:flex; gap:.4rem; align-items:center; flex-wrap:wrap; }
.vbtn { font:inherit; font-size:.8rem; padding:.3rem .8rem; border-radius:5px; cursor:pointer;
  border:1px solid var(--border); background:var(--card); color:var(--ink); }
.vbtn[data-v=pass][aria-pressed=true] { background:var(--pass); border-color:var(--pass); color:#fff; }
.vbtn[data-v=maybe][aria-pressed=true] { background:var(--maybe); border-color:var(--maybe); color:#fff; }
.vbtn[data-v=bad][aria-pressed=true] { background:var(--fail); border-color:var(--fail); color:#fff; }
.vbtn.clear { color:var(--muted); }
.mine { margin-left:auto; font-size:.72rem; color:var(--muted); }
.tags { display:flex; gap:.3rem; flex-wrap:wrap; margin-top:.45rem; }
.ttag { font:inherit; font-size:.72rem; padding:.1rem .5rem; border-radius:99px; cursor:pointer;
  border:1px solid var(--border); background:var(--bg); color:var(--muted); }
.ttag[aria-pressed=true] { background:#fff1ef; border-color:var(--fail); color:var(--fail); }
textarea { width:100%; margin-top:.5rem; font:inherit; font-size:.8rem; padding:.4rem .55rem;
  border:1px solid var(--border); border-radius:5px; resize:vertical; min-height:2.5rem;
  background:var(--card); color:var(--ink); }
.note-hint { font-size:.7rem; color:var(--muted); margin-top:.2rem; }

/* ---- sweep / disagreement tables ---- */
.sweep { width:100%; border-collapse:collapse; margin-top:1rem; font-size:.8rem;
  background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.sweep th, .sweep td { padding:.35rem .6rem; text-align:left; border-bottom:1px solid var(--border);
  vertical-align:top; }
.sweep th { background:var(--bg); font-weight:600; font-size:.75rem; color:var(--muted); }
.sweep code { font-size:.72rem; }
.sweep tr.mismatch td { background:#fdf1ef; }
footer { text-align:center; padding:1.6rem 1.5rem; color:var(--muted); font-size:.8rem;
  border-top:1px solid var(--border); }
footer code { background:var(--bg); padding:.1rem .35rem; border-radius:3px; }

/* ---- lightbox + focus mode ---- */
.overlay { display:none; position:fixed; inset:0; z-index:1000; background:rgba(18,16,14,.94);
  color:#eee; }
.overlay.open { display:flex; flex-direction:column; }
.ov-head { padding:.7rem 1.2rem; display:flex; gap:.7rem; align-items:center; flex-wrap:wrap;
  border-bottom:1px solid rgba(255,255,255,.15); }
.ov-head h3 { font-size:1rem; }
.ov-head .ov-channel { font-size:.8rem; color:#ffd9a0; background:rgba(255,255,255,.08);
  padding:.12rem .5rem; border-radius:4px; }
/* The way out has to be a button, not just a keyboard hint: the overlay covers the page,
   so without it the only exit is Esc/F, which is not something to rely on. */
.ov-head .btn.exit { margin-left:auto; font-size:.8rem; padding:.3rem .9rem;
  background:#eee; color:#111; border-color:#eee; }
.ov-head .btn.exit:hover { background:#fff; color:#000; border-color:#fff; }
.ov-head .meta2 { font-size:.75rem; color:#bbb; }
.ov-body { flex:1; display:flex; min-height:0; }
.ov-stage { flex:1; display:flex; align-items:center; justify-content:center; padding:1rem;
  min-width:0; }
.ov-stage img { max-width:100%; max-height:100%; object-fit:contain; cursor:zoom-out; }
.ov-side { flex:0 0 26rem; border-left:1px solid rgba(255,255,255,.15); overflow:auto;
  padding:.9rem 1.1rem 2rem; font-size:.8rem; }
.ov-side .checks .k { flex:0 0 9rem; }
.ov-side .checks .row { border-color:rgba(255,255,255,.12); }
.ov-side .checks .d { color:#a9a9a9; }
.ov-side p.prose { color:#c6c6c6; }
.ov-side .card-head code { color:#a9a9a9; }
.ov-side .note-hint { color:#a9a9a9; }
/* The amber/light blocks keep their light backgrounds in the overlay, so their text has to
   stay dark there: inheriting the overlay's #eee made "目录预期与实测一致" unreadable. */
.ov-side .expect, .ov-side .expect b, .ov-side .look, .ov-side .look b { color:var(--ink); }
.ov-side .panel h4 { color:#9c9c9c; }
.ov-side textarea { background:#241f1c; color:#eee; border-color:#3d3733; }
.ov-side .review { border-color:rgba(255,255,255,.15); margin:.6rem 0 0; }
.ov-side .vbtn { background:#2a2521; color:#eee; border-color:#443d38; }
.ov-side .ttag { background:#241f1c; color:#bbb; border-color:#443d38; }
.ov-side .chip { background:#241f1c; border-color:#443d38; color:#bbb; }
.ov-side .card-head h3 { font-size:.95rem; }
.ov-hint { font-size:.72rem; color:#8d8d8d; }
.tabrow { display:flex; gap:.3rem; }
.tab { font:inherit; font-size:.74rem; padding:.15rem .55rem; border-radius:4px; cursor:pointer;
  background:#2a2521; color:#ddd; border:1px solid #443d38; }
.tab[aria-pressed=true] { background:#eee; color:#111; border-color:#eee; }
mark { background:#ffe9a8; }
"""

_SCRIPT = """
(function () {
  var STORE_KEY = 'manim-lace-review-v1';
  var SEED = window.__REVIEW_SEED__ || null;
  var BUILD = window.__REVIEW_BUILD__ || '';
  var QUALITY = window.__REVIEW_QUALITY__ || '';
  var DEFECT_TAGS = window.__REVIEW_TAGS__ || [];
  var state = {};
  var storageOk = true;

  function clone(object) { return JSON.parse(JSON.stringify(object)); }

  function storageWorks() {
    // A private window or a blocked third-party context throws on the very first write;
    // find that out now, because a reviewer who believes their verdicts are saved and
    // finds them gone after a refresh has lost the round.
    try {
      var probe = STORE_KEY + '-probe';
      window.localStorage.setItem(probe, '1');
      window.localStorage.removeItem(probe);
      return true;
    } catch (error) { return false; }
  }

  function setStoreState(kind, text) {
    var badge = document.getElementById('store-state');
    if (!badge) { return; }
    badge.className = 'store ' + kind;
    badge.textContent = text;
  }

  function load() {
    // The baked ledger (``--verdicts``) is the base and this browser's own verdicts sit on
    // top, per case: rebuilding the page with a new round must not hide it behind an older
    // copy in localStorage, and a local note must not be thrown away by a rebuild.
    var base = SEED && SEED.cases ? clone(SEED.cases) : {};
    var stored = {};
    storageOk = storageWorks();
    if (storageOk) {
      try {
        var raw = window.localStorage.getItem(STORE_KEY);
        if (raw) {
          var parsed = JSON.parse(raw);
          if (parsed && parsed.cases) { stored = parsed.cases; }
        }
      } catch (error) { storageOk = false; }
    }
    state = {};
    Object.keys(base).forEach(function (key) { state[key] = base[key]; });
    Object.keys(stored).forEach(function (key) { state[key] = stored[key]; });
    var count = Object.keys(state).length;
    if (storageOk) {
      setStoreState('ok', '本浏览器已自动保存' + (count ? '（' + count + ' 条结论）' : '') +
        '：刷新或重开页面都会保留，不用再导入');
    } else {
      setStoreState('warn', '本浏览器禁用了本地存储：结论只在这个标签页有效，刷新会丢——' +
        '请用「复制结论」留档');
    }
  }

  function save() {
    if (!storageOk) { return; }
    var stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify({
        version: 1, built: BUILD, quality: QUALITY, cases: state
      }));
      var count = Object.keys(state).length;
      setStoreState('ok', '已自动保存 ' + stamp + '（' + count + ' 条结论）' +
        '：刷新或重开页面都会保留，不用再导入');
    } catch (error) {
      storageOk = false;
      setStoreState('warn', '本地存储写入失败：结论只在这个标签页有效，刷新会丢——' +
        '请用「复制结论」留档');
    }
  }

  function entry(key) {
    if (!state[key]) { state[key] = { verdict: '', tags: [], note: '', at: '' }; }
    return state[key];
  }

  function reviewed(key) {
    var item = state[key];
    return !!(item && (item.verdict || (item.tags && item.tags.length) || item.note));
  }

  function cards() { return Array.prototype.slice.call(document.querySelectorAll('.card[data-key]')); }

  function paint(card) {
    var key = card.getAttribute('data-key');
    var item = state[key] || { verdict: '', tags: [], note: '' };
    card.setAttribute('data-verdict', item.verdict || 'none');
    card.querySelectorAll('.vbtn[data-v]').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-v') === item.verdict));
    });
    card.querySelectorAll('.ttag[data-t]').forEach(function (chip) {
      chip.setAttribute('aria-pressed', String((item.tags || []).indexOf(chip.getAttribute('data-t')) >= 0));
    });
    var area = card.querySelector('textarea[data-note]');
    if (area && area.value !== (item.note || '')) { area.value = item.note || ''; }
    var stamp = card.querySelector('.mine');
    if (stamp) { stamp.textContent = reviewed(key) ? ('已审核' + (item.at ? ' ' + item.at : '')) : '未审核'; }
    var flags = [];
    if (card.querySelector('.chip.fail')) { flags.push('checkfail'); }
    if (card.querySelector('.chip.warn')) { flags.push('checkwarn'); }
    if (card.querySelector('.chip.warn, .chip.error')) { flags.push('diagnostic'); }
    if (!reviewed(key)) { flags.push('unreviewed'); }
    card.setAttribute('data-flags', flags.join(' '));
    var sweep = document.querySelector('.sweep tr[data-key="' + key + '"] .v');
    if (sweep) {
      var label = { pass: '通过', maybe: '存疑', bad: '有问题' }[item.verdict];
      sweep.textContent = label || '（未审核）';
      sweep.className = item.verdict ? ('v ' + item.verdict) : 'v';
    }
  }

  function paintAll() {
    cards().forEach(paint);
    document.querySelectorAll('.ov-side').forEach(paint);
    progress(); applyFilters();
  }

  function progress() {
    var all = cards().length, done = 0, counts = { pass: 0, maybe: 0, bad: 0 }, disagree = 0;
    cards().forEach(function (card) {
      var key = card.getAttribute('data-key');
      var item = state[key] || {};
      if (reviewed(key)) { done += 1; }
      if (item.verdict && counts[item.verdict] !== undefined) { counts[item.verdict] += 1; }
      if (item.verdict === 'bad' && card.getAttribute('data-checkfail') === '0' &&
          (card.getAttribute('data-checkwarn') || '0') === '0') { disagree += 1; }
    });
    var percent = all ? Math.round(100 * done / all) : 0;
    var bar = document.querySelector('.bar');
    if (bar) {
      bar.innerHTML = '';
      ['pass', 'maybe', 'bad'].forEach(function (name) {
        if (!counts[name] || !all) { return; }
        var piece = document.createElement('i');
        piece.className = name === 'pass' ? 'p' : (name === 'maybe' ? 'm' : 'f');
        piece.style.width = (100 * counts[name] / all) + '%';
        bar.appendChild(piece);
      });
    }
    var text = document.getElementById('progress-text');
    if (text) {
      text.innerHTML = '已审核 <b>' + done + '</b>/' + all + '（' + percent + '%） · ' +
        '通过 <b>' + counts.pass + '</b> · 存疑 <b>' + counts.maybe + '</b> · ' +
        '有问题 <b>' + counts.bad + '</b> · ' +
        '程序通过但人审有问题 <b>' + disagree + '</b>';
    }
  }

  function applyFilters() {
    var category = (document.getElementById('f-category') || {}).value || '';
    var verdict = (document.getElementById('f-verdict') || {}).value || '';
    var query = ((document.getElementById('f-search') || {}).value || '').trim().toLowerCase();
    var visible = [];
    cards().forEach(function (card) {
      var show = true;
      if (category && card.getAttribute('data-cat') !== category) { show = false; }
      var mine = state[card.getAttribute('data-key')] || {};
      var flags = card.getAttribute('data-flags') || '';
      if (verdict === 'unreviewed' && flags.indexOf('unreviewed') < 0) { show = false; }
      if (verdict === 'checkfail' && flags.indexOf('checkfail') < 0) { show = false; }
      if (verdict === 'checkwarn' && flags.indexOf('checkwarn') < 0) { show = false; }
      if (verdict === 'diagnostic' && flags.indexOf('diagnostic') < 0) { show = false; }
      if (verdict === 'disagree' && (card.getAttribute('data-checkfail') !== '0' ||
          (card.getAttribute('data-checkwarn') || '0') !== '0')) { show = false; }
      if (verdict && ['pass', 'maybe', 'bad'].indexOf(verdict) >= 0 && mine.verdict !== verdict) {
        show = false;
      }
      if (query) {
        var haystack = card.getAttribute('data-search') || '';
        if (haystack.indexOf(query) < 0) { show = false; }
      }
      card.classList.toggle('hidden', !show);
      if (show) { visible.push(card); }
    });
    document.querySelectorAll('section.cat').forEach(function (section) {
      var any = section.querySelectorAll('.card:not(.hidden)').length;
      section.classList.toggle('hidden', any === 0);
      var head = section.querySelector('h2');
      if (head) { head.classList.toggle('hidden', any === 0); }
      var what = section.querySelector('.cat-what');
      if (what) { what.classList.toggle('hidden', any === 0); }
    });
    window.__VISIBLE__ = visible;
  }

  function setVerdict(card, verdict) {
    var item = entry(card.getAttribute('data-key'));
    item.verdict = item.verdict === verdict ? '' : verdict;
    item.at = new Date().toISOString().slice(0, 16).replace('T', ' ');
    save(); paintAll();
  }

  function toggleTag(card, tag) {
    var item = entry(card.getAttribute('data-key'));
    var list = item.tags || (item.tags = []);
    var at = list.indexOf(tag);
    if (at >= 0) { list.splice(at, 1); } else { list.push(tag); }
    item.at = new Date().toISOString().slice(0, 16).replace('T', ' ');
    save(); paintAll();
  }

  // ---- focus mode ----
  var overlay = document.getElementById('focus');
  var current = -1;
  // The channel the reviewer last looked at. Arrow keys keep it: walking a list of cases
  // while being thrown back to the first panel on every step made the comparison useless.
  var currentChannel = null;

  function focusCard(card, channel) {
    if (!card) { return; }
    if (channel) { currentChannel = channel; }
    var visible = window.__VISIBLE__ || cards();
    current = visible.indexOf(card);
    var body = overlay.querySelector('.ov-body');
    body.innerHTML = '';
    var stage = document.createElement('div');
    stage.className = 'ov-stage';
    var side = document.createElement('div');
    side.className = 'ov-side';
    var imported = card.cloneNode(true);
    imported.classList.remove('hidden');
    var shots = imported.querySelector('.shots');
    // Fall back to the first panel when this case has no such channel (an error case has
    // no images at all, and a case may omit a backend).
    var first = shots ? shots.querySelector('img') : null;
    if (currentChannel && shots) {
      first = shots.querySelector('img[data-channel="' + currentChannel + '"]') || first;
    }
    var channelLabel = first
      ? (first.closest('figure').querySelector('figcaption').textContent || '')
      : '';
    var heading = overlay.querySelector('.ov-head .ov-channel');
    if (heading) { heading.textContent = channelLabel; }
    var image = document.createElement('img');
    image.src = first ? first.src : '';
    image.alt = card.getAttribute('data-search') || '';
    stage.appendChild(image);
    var controls = document.createElement('div');
    controls.innerHTML = '<div class="panel"><h4>通道</h4></div>';
    var tabs = document.createElement('div');
    tabs.className = 'tabrow';
    (shots ? shots.querySelectorAll('figure.shot') : []).forEach(function (figure) {
      var img = figure.querySelector('img');
      if (!img) { return; }
      var button = document.createElement('button');
      button.className = 'tab';
      button.textContent = figure.querySelector('figcaption').textContent;
      button.__src = img.src;
      button.__channel = img.getAttribute('data-channel');
      button.setAttribute('aria-pressed', String(img === first));
      button.addEventListener('click', function () {
        image.src = img.src;
        currentChannel = button.__channel;
        var label = overlay.querySelector('.ov-head .ov-channel');
        if (label) { label.textContent = button.textContent; }
        tabs.querySelectorAll('.tab').forEach(function (other) {
          other.setAttribute('aria-pressed', String(other === button));
        });
      });
      tabs.appendChild(button);
    });
    var blink = document.createElement('button');
    blink.className = 'tab';
    blink.textContent = '闪烁对照 A/B';
    blink.addEventListener('click', function () {
      var sources = Array.prototype.slice.call(tabs.querySelectorAll('.tab')).map(function (tab) {
        return tab.__src;
      });
      if (sources.length < 2) { return; }
      if (blink.__timer) {
        window.clearInterval(blink.__timer);
        blink.__timer = null;
        blink.setAttribute('aria-pressed', 'false');
        return;
      }
      blink.setAttribute('aria-pressed', 'true');
      var which = 0;
      blink.__timer = window.setInterval(function () {
        which = 1 - which;
        image.src = sources[which];
      }, 500);
    });
    controls.querySelector('.panel').appendChild(tabs);
    controls.querySelector('.panel').appendChild(blink);
    side.appendChild(controls);

    ['data-key', 'data-cat', 'data-checkfail', 'data-search'].forEach(function (name) {
      side.setAttribute(name, card.getAttribute(name) || '');
    });
    var head = imported.querySelector('.card-head');
    var prose = imported.querySelector('p.prose');
    var look = imported.querySelector('.look');
    var expect = imported.querySelector('.expect');
    var panels = imported.querySelectorAll('.panel');
    var review = imported.querySelector('.review');
    [head, prose, look, expect].forEach(function (node) { if (node) { side.appendChild(node); } });
    panels.forEach(function (panel) { side.appendChild(panel); });
    if (review) { side.appendChild(review); }
    var hint = document.createElement('p');
    hint.className = 'ov-hint';
    hint.textContent = '← → 上一个/下一个 · 1 通过 · 2 存疑 · 3 有问题 · F 关闭 · 点击图放大';
    side.appendChild(hint);
    body.appendChild(stage);
    body.appendChild(side);
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    paint(side);
    image.addEventListener('click', function () { window.open(image.src, '_blank'); });
  }

  function closeFocus() {
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    var body = overlay.querySelector('.ov-body');
    if (body) { body.innerHTML = ''; }
  }

  // ---- event delegation: works for the page and for the cloned focus panel ----
  document.addEventListener('click', function (event) {
    var target = event.target;
    if (target.matches && target.matches('.shot img')) {
      var owner = target.closest('.card');
      if (owner) { focusCard(owner, target.getAttribute('data-channel')); }
      return;
    }
    var button = target.closest && target.closest('[data-act]');
    if (!button) { return; }
    var action = button.getAttribute('data-act');
    var card = button.closest('.card, .ov-side');
    if (action === 'verdict' && card) { setVerdict(card, button.getAttribute('data-v')); return; }
    if (action === 'tag' && card) { toggleTag(card, button.getAttribute('data-t')); return; }
    if (action === 'focus') {
      focusCard(button.closest('.card'));
      return;
    }
  });

  document.addEventListener('input', function (event) {
    var area = event.target;
    if (area.matches && area.matches('textarea[data-note]')) {
      var card = area.closest('.card, .ov-side');
      if (!card) { return; }
      var item = entry(card.getAttribute('data-key'));
      item.note = area.value;
      item.at = new Date().toISOString().slice(0, 16).replace('T', ' ');
      save();
      var stamp = card.querySelector('.mine');
      if (stamp) { stamp.textContent = '已审核 ' + item.at; }
      progress();
    }
    if (event.target.id === 'f-search') { applyFilters(); }
  });

  document.addEventListener('change', function (event) {
    if (event.target.id === 'f-category' || event.target.id === 'f-verdict') { applyFilters(); }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      if (overlay.classList.contains('open')) { closeFocus(); }
      return;
    }
    if (!overlay.classList.contains('open')) {
      return;
    }
    var visible = window.__VISIBLE__ || cards();
    var card = visible[current];
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      var step = event.key === 'ArrowRight' ? 1 : -1;
      var next = (current + step + visible.length) % visible.length;
      focusCard(visible[next]);
      event.preventDefault();
      return;
    }
    if (!card) { return; }
    if (event.key === '1') { setVerdict(card, 'pass'); }
    if (event.key === '2') { setVerdict(card, 'maybe'); }
    if (event.key === '3') { setVerdict(card, 'bad'); }
    if (event.key === 'f' || event.key === 'F') { closeFocus(); }
  });

  // ---- clipboard in / out (no files: the browser already keeps the round) ----
  function payload() {
    return JSON.stringify({ version: 1, built: BUILD, quality: QUALITY, cases: state }, null, 2);
  }

  function flash(button, text, kind) {
    var original = button.getAttribute('data-label') || button.textContent;
    button.setAttribute('data-label', original);
    button.textContent = text;
    button.className = 'btn ' + (kind || '');
    window.setTimeout(function () {
      button.textContent = original;
      button.className = 'btn';
    }, 2600);
  }

  function copyViaTextarea(text) {
    // Fallback for a context where the async Clipboard API is unavailable (some browsers
    // refuse it on file://): a temporary textarea plus the old execCommand path.
    var area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'readonly');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, area.value.length);
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
    document.body.removeChild(area);
    return ok;
  }

  function importSummary(text) {
    try {
      var parsed = JSON.parse(text);
      var incoming = (parsed && parsed.cases) || {};
      var keys = Object.keys(incoming);
      var overwrite = keys.filter(function (key) {
        var mine = state[key];
        return mine && (mine.verdict || (mine.tags && mine.tags.length) || mine.note);
      }).length;
      return { ok: true, cases: incoming, keys: keys, overwrite: overwrite,
               built: parsed && parsed.built ? String(parsed.built) : '' };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }

  function mergeImported(result) {
    result.keys.forEach(function (key) { state[key] = result.cases[key]; });
    save();
    paintAll();
  }

  var copyButton = document.getElementById('do-copy');
  if (copyButton) {
    copyButton.addEventListener('click', function () {
      var text = payload();
      var count = Object.keys(state).length;
      var done = function () {
        flash(copyButton, '已复制 ' + count + ' 条结论（' + text.length + ' 字节）', 'primary');
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {
          if (copyViaTextarea(text)) { done(); }
          else {
            openPaste();
            document.getElementById('import-text').value = text;
            document.getElementById('import-text').select();
            flash(copyButton, '剪贴板不可用：已选中文本，请按 Ctrl+C', '');
          }
        });
      } else if (copyViaTextarea(text)) {
        done();
      } else {
        openPaste();
        document.getElementById('import-text').value = text;
        document.getElementById('import-text').select();
        flash(copyButton, '剪贴板不可用：已选中文本，请按 Ctrl+C', '');
      }
    });
  }

  var pastePanel = document.getElementById('paste-panel');
  var pasteArea = document.getElementById('import-text');
  var pastePreview = document.getElementById('paste-preview');
  var mergeButton = document.getElementById('do-merge');

  function openPaste() {
    pastePanel.classList.remove('hidden');
    pasteArea.focus();
  }

  function updatePreview() {
    var text = (pasteArea.value || '').trim();
    if (!text) {
      pastePreview.textContent = '把「复制结论」得到的 JSON 粘贴到这里（Ctrl+V），或点「读剪贴板」。';
      pastePreview.className = 'paste-preview';
      mergeButton.disabled = true;
      return;
    }
    var result = importSummary(text);
    if (!result.ok) {
      pastePreview.textContent = '不是有效的 JSON：' + result.error;
      pastePreview.className = 'paste-preview bad';
      mergeButton.disabled = true;
      return;
    }
    pastePreview.textContent = '解析到 ' + result.keys.length + ' 条结论'
      + (result.built ? '（导出时间 ' + result.built + '）' : '')
      + '，其中 ' + result.overwrite + ' 条会覆盖本机已有的结论。';
    pastePreview.className = 'paste-preview ' + (result.overwrite ? 'warn' : 'ok');
    mergeButton.disabled = result.keys.length === 0;
  }

  var readButton = document.getElementById('do-read');
  if (readButton) {
    readButton.addEventListener('click', function () {
      openPaste();
      if (!(navigator.clipboard && navigator.clipboard.readText)) {
        flash(readButton, '本浏览器不允许读剪贴板，请手动 Ctrl+V', '');
        return;
      }
      navigator.clipboard.readText().then(function (text) {
        pasteArea.value = text;
        updatePreview();
      }, function () {
        flash(readButton, '读取被拒绝，请手动 Ctrl+V', '');
      });
    });
  }

  var pasteButton = document.getElementById('do-paste');
  if (pasteButton) {
    pasteButton.addEventListener('click', function () {
      if (pastePanel.classList.contains('hidden')) { openPaste(); }
      else { pastePanel.classList.add('hidden'); }
    });
  }

  if (pasteArea) {
    pasteArea.addEventListener('input', updatePreview);
    pasteArea.addEventListener('paste', function () {
      window.setTimeout(updatePreview, 0);
    });
  }

  if (mergeButton) {
    mergeButton.addEventListener('click', function () {
      var result = importSummary((pasteArea.value || '').trim());
      if (!result.ok) { return; }
      mergeImported(result);
      flash(mergeButton, '已合并 ' + result.keys.length + ' 条', 'primary');
      pasteArea.value = '';
      updatePreview();
    });
  }

  var clearButton = document.getElementById('do-clear');
  if (clearButton) {
    clearButton.addEventListener('click', function () {
      if (!window.confirm('清空本机上的全部人审结论？（导出的文本不受影响）')) { return; }
      state = {};
      save(); paintAll();
    });
  }
  var sweepButton = document.getElementById('do-sweep');
  if (sweepButton) {
    sweepButton.addEventListener('click', function () {
      var first = (window.__VISIBLE__ || cards())[0];
      if (first) { focusCard(first); }
    });
  }
  var exitButton = document.getElementById('do-exit-focus');
  if (exitButton) {
    exitButton.addEventListener('click', function () { closeFocus(); });
  }

  load();
  paintAll();
  updatePreview();
  window.__REVIEW__ = { state: state, paintAll: paintAll, focusCard: focusCard };
})();
"""

DEFECT_TAGS: tuple[str, ...] = (
    "缺口", "断头/悬空描边", "画进丝带内部的线", "上下关系反了", "少画了一块",
    "多画了一块", "接缝/端面可见", "角点或曲线畸形", "面积不守恒", "颜色不可辨",
    "与另一通道不一致", "形状本身不对",
)


def _status_label(status: str) -> str:
    return {"pass": "通过", "fail": "失败", "warn": "警告", "info": "读数",
            "skip": "不适用"}.get(status, status)


def _checks_html(verdict: dict[str, Any], *, collapsed: bool = True) -> str:
    checks = verdict.get("checks", [])
    attention = [check for check in checks if check["status"] in ("fail", "warn")]
    other = [check for check in checks if check["status"] not in ("fail", "warn")]

    def row(check: dict[str, Any]) -> str:
        return (
            f'<div class="row"><span class="st {check["status"]}">{_status_label(check["status"])}</span>'
            f'<span class="k">{html.escape(check["key"])}</span>'
            f'<span class="d">{html.escape(check["detail"])}</span></div>'
        )

    block = f'<div class="checks">{"".join(row(check) for check in attention)}</div>'
    if other:
        open_attr = "" if collapsed else " open"
        block += (
            f"<details{open_attr}><summary>其余 {len(other)} 项读数与通过的检查</summary>"
            f'<div class="checks">{"".join(row(check) for check in other)}</div></details>'
        )
    return block


def _channel_facts_html(verdict: dict[str, Any]) -> str:
    facts = verdict["facts"]
    kinds = facts.get("kinds", {})
    kind_text = "、".join(f"{name}×{count}" for name, count in kinds.items())
    angle = facts.get("worst_sin_angle")
    chips = [
        f"交叉 {facts['crossings']}",
        f"自交 {facts['self_crossings']}",
        f"{facts['units']} {facts['pieces']}",
        f"交替缺陷 {facts['alternation_defects']}",
        f"放宽 {facts['relaxed']}",
        f"精化 {facts['refined']}",
        f"路径 {facts['paths']}",
    ]
    if angle is not None:
        chips.append(f"最差 sinθ {angle:.3f}")
    if kind_text:
        chips.append(kind_text)
    return "".join(f'<span class="chip">{html.escape(chip)}</span>' for chip in chips)


def _diagnostics_html(verdict: dict[str, Any]) -> str:
    diagnostics = verdict.get("diagnostics", [])
    if not diagnostics:
        return '<span class="chip pass">0 诊断</span>'
    chips = []
    for diagnostic in diagnostics:
        severity = diagnostic["severity"]
        css = {"warning": "warn", "error": "error", "info": "info"}.get(severity, "info")
        title = f"{diagnostic['message']}"
        if diagnostic.get("hints"):
            title += " · " + " ".join(diagnostic["hints"])
        chips.append(
            f'<span class="chip {css}" title="{html.escape(title)}">'
            f'{html.escape(diagnostic["code"])}×{diagnostic["count"]}·{html.escape(severity)}</span>'
        )
    return "".join(chips)


def _shot_html(case: Case, channel: str, label: str, *, exists: bool) -> str:
    if not exists:
        return f'<figure class="shot missing"><span>无图（{html.escape(label)}）</span></figure>'
    source = f"{case.key}__{channel}.png"
    return (
        f'<figure class="shot"><img src="{source}" data-channel="{channel}" '
        f'alt="{html.escape(case.title)} {html.escape(label)}" loading="lazy">'
        f"<figcaption>{html.escape(label)}</figcaption></figure>"
    )


def _verdict_badge(set_: dict[str, Any]) -> str:
    failed = set_["failed"]
    warned = set_.get("warned", 0)
    badges = []
    if failed:
        badges.append(f'<span class="chip fail">检查失败 {failed}</span>')
    if warned:
        badges.append(f'<span class="chip warn">警告 {warned}</span>')
    if not badges:
        badges.append('<span class="chip pass">检查全通过</span>')
    return "".join(badges)


def _card_html(measurement: CaseMeasurement, rendered: dict[str, bool], focus_hint: str) -> str:
    case = measurement.case
    checkfail = sum(data.get("failed", 0) for data in measurement.channels.values())
    checkwarn = sum(data.get("warned", 0) for data in measurement.channels.values())
    shots: list[str] = []
    for channel in channels_to_render(measurement):
        label = {
            "input": "原始输入（中心线 + 检出交叉）",
            "stroke": "stroke（中心线切口）",
            "boolean": "ribbon · boolean",
            "arrangement": "ribbon · arrangement",
            "hybrid": "ribbon · hybrid（实验）",
            "annotate": "编织结果（交叉编号）",
        }[channel]
        shots.append(_shot_html(case, channel, label,
                               exists=rendered.get(channel, False)))
    if case.kind == "error":
        shown = html.escape(measurement.error or "（未抛错，不符合预期）")
        shots.append(
            f'<figure class="shot missing"><span>必须失败的案例：<code>{shown}</code></span></figure>'
        )

    panels = []
    for channel, data in measurement.channels.items():
        panels.append(
            f'<div class="panel"><h4>{html.escape(channel)} · {_verdict_badge(data)}</h4>'
            f'<div class="chips">{_channel_facts_html(data)}</div>'
            f'<div class="chips" style="margin-top:.3rem">{_diagnostics_html(data)}</div>'
            f'<p class="note-hint">{html.escape(data.get("measured_note", ""))}</p>'
            f'{_checks_html(data)}</div>'
        )
    if not measurement.channels:
        panels.append(
            '<div class="panel"><h4>程序判定</h4><p class="note-hint">'
            '本案例的目标就是抛出错误，没有可求解的几何。</p></div>'
        )
    omitted = omitted_channels(case)
    if omitted:
        items = "".join(
            f'<div class="row"><span class="st warn">未跑</span>'
            f'<span class="k">{html.escape(channel)}</span>'
            f'<span class="d">{html.escape(reason)}</span></div>'
            for channel, reason in omitted
        )
        panels.append(
            f'<div class="panel"><h4>本轮未纳入的通道（引擎侧开销，实测数字已写在原因里）</h4>'
            f'<div class="checks">{items}</div></div>'
        )

    expectation = measurement.expectation
    issues = expectation.get("issues") or []
    if issues:
        expect_html = (
            '<div class="expect bad"><b>目录预期与实测不符</b><ul>'
            + "".join(f"<li>{html.escape(issue)}</li>" for issue in issues)
            + "</ul></div>"
        )
    else:
        expect_html = (
            '<div class="expect ok">目录预期与实测一致'
            + (f"：{html.escape(measurement.error)}" if measurement.error else "")
            + "</div>"
        )

    agreement = channel_agreement(measurement)
    agree_chip = (
        f'<span class="chip {"pass" if agreement["ok"] else "fail"}">通道一致性：'
        f'{html.escape(agreement["detail"])}</span>'
    )

    tags = "".join(
        f'<button class="ttag" data-act="tag" data-t="{html.escape(tag)}" aria-pressed="false">'
        f'{html.escape(tag)}</button>'
        for tag in DEFECT_TAGS
    )
    engine_note = "、".join(f"{key}={value}" for key, value in case.engine.items())
    meta_chips = [
        f"offset {case.offset:g}",
        f"weave {case.weave_mode}",
        f"kind {case.kind}",
        *([engine_note] if engine_note else []),
        *case.tags,
    ]
    search = " ".join(
        [case.key, case.title, case.prose, case.look_for, case.category, *case.tags]
    ).lower()
    return (
        f'<div class="card" data-key="{case.key}" data-cat="{case.category}" '
        f'data-checkfail="{checkfail}" data-checkwarn="{checkwarn}" '
        f'data-search="{html.escape(search)}">'
        f'<div class="card-head"><h3>{html.escape(case.title)}</h3>'
        f'<code>{html.escape(case.key)}</code>'
        f'<button class="btn focus" data-act="focus" title="{html.escape(focus_hint)}">聚焦</button></div>'
        f'<p class="prose">{html.escape(case.prose)}</p>'
        + (f'<div class="look"><b>看什么：</b>{html.escape(case.look_for)}</div>'
           if case.look_for else "")
        + '<div class="chips" style="padding:.5rem 1rem 0">'
        + "".join(f'<span class="chip">{html.escape(chip)}</span>' for chip in meta_chips)
        + "</div>"
        + f'<div class="chips" style="padding:.35rem 1rem 0">{agree_chip}</div>'
        + f'<div class="shots">{"".join(shots)}</div>'
        + "".join(panels)
        + expect_html
        + '<div class="review"><div class="verdicts">'
        + '<button class="vbtn" data-act="verdict" data-v="pass" aria-pressed="false">通过</button>'
        + '<button class="vbtn" data-act="verdict" data-v="maybe" aria-pressed="false">存疑</button>'
        + '<button class="vbtn" data-act="verdict" data-v="bad" aria-pressed="false">有问题</button>'
        + '<button class="vbtn clear" data-act="verdict" data-v="" aria-pressed="false">清除</button>'
        + '<span class="mine">未审核</span></div>'
        + f'<div class="tags">{tags}</div>'
        + '<textarea data-note rows="2" placeholder="人审备注：看到了什么、在哪一处、和你预期差在哪"></textarea>'
        + '</div></div>'
    )


def _section_html(
    category_key: str, measurements: list[CaseMeasurement], rendered: dict[str, dict[str, bool]]
) -> str:
    category = CATEGORY_BY_KEY[category_key]
    cards = "".join(
        _card_html(measurement, rendered.get(measurement.case.key, {}), "放大并逐张审核")
        for measurement in measurements
    )
    return (
        f'<section class="cat" data-cat="{category.key}">'
        f"<h2>{html.escape(category.title)}<span>{html.escape(category.subtitle)}</span></h2>"
        f'<p class="cat-what">{html.escape(category.what)}</p>'
        f'<div class="grid">{cards}</div></section>'
    )


def _sweep_table(measurements: list[CaseMeasurement]) -> str:
    rows = []
    for measurement in measurements:
        case = measurement.case
        checkfail = sum(data.get("failed", 0) for data in measurement.channels.values())
        checkwarn = sum(data.get("warned", 0) for data in measurement.channels.values())
        codes = sorted({
            diagnostic["code"]
            for data in measurement.channels.values()
            for diagnostic in data.get("diagnostics", [])
        })
        issues = measurement.expectation.get("issues") or []
        rows.append(
            f'<tr data-key="{case.key}"><td><code>{html.escape(case.key)}</code></td>'
            f"<td>{html.escape(case.title)}</td>"
            f'<td class="v">（未审核）</td>'
            + (f'<td><span class="chip fail">{checkfail}</span></td>' if checkfail
               else '<td><span class="chip pass">0</span></td>')
            + (f'<td><span class="chip warn">{checkwarn}</span></td>' if checkwarn
               else '<td><span class="chip pass">0</span></td>')
            + (f'<td><span class="chip fail">{len(issues)}</span></td>' if issues
               else '<td><span class="chip pass">0</span></td>')
            + f'<td class="codes">{html.escape("、".join(codes) or "—")}</td></tr>'
        )
    return (
        "<table class='sweep'><tr><th>key</th><th>案例</th><th>人审</th><th>检查失败</th>"
        "<th>警告</th><th>预期不符</th><th>诊断码</th></tr>" + "".join(rows) + "</table>"
    )


def write_page(
    measurements: list[CaseMeasurement],
    *,
    quality: str,
    rendered_now: bool,
    seed: dict[str, Any] | None,
    target: Path | None = None,
) -> Path:
    """Write the review page. ``target`` defaults to ``media/review/index.html``.

    The tests pass their own path: writing the real page from a two-case test run replaced
    the built 53-case page with a 48 KB fragment, which is a side effect no test should have.
    """
    page_path = PAGE if target is None else target
    rendered: dict[str, dict[str, bool]] = {}
    for measurement in measurements:
        rendered[measurement.case.key] = {
            channel: (MEDIA / f"{measurement.case.key}__{channel}.png").exists()
            for channel in channels_to_render(measurement)
        }
    sections: list[str] = []
    for category in CATEGORIES:
        items = [m for m in measurements if m.case.category == category.key]
        if items:
            sections.append(_section_html(category.key, items, rendered))

    stats = catalog_stats()
    total_cases = len(measurements)
    total_channels = sum(len(m.channels) for m in measurements)
    failed_checks = sum(d.get("failed", 0) for m in measurements for d in m.channels.values())
    warned_checks = sum(d.get("warned", 0) for m in measurements for d in m.channels.values())
    mismatched = sum(1 for m in measurements if m.expectation.get("issues"))
    diagnostic_codes = Counter(
        diagnostic["code"]
        for m in measurements for data in m.channels.values()
        for diagnostic in data.get("diagnostics", [])
    )
    category_filter = "".join(
        f'<option value="{category.key}">{html.escape(category.title)}（{stats[category.key]}）</option>'
        for category in CATEGORIES
    )
    meta = [
        f"manim-lace {manim_lace.__version__}",
        f"Manim CE {manim.__version__}",
        f"{total_cases} 个案例 / {total_channels} 次求解",
        "通道 stroke / boolean / arrangement",
        f"渲染质量 {quality.upper()}" if rendered_now else "复用上次媒体，判定已重算",
        f"检查失败 {failed_checks} 项 · 警告 {warned_checks} 项 · 预期不符 {mismatched} 个案例",
        f"触发诊断码 {len(diagnostic_codes)} 种",
    ]
    seed_json = json.dumps(seed or {}, ensure_ascii=False)
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manim-Lace 编织效果人工审查</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Manim-Lace 编织效果人工审查</h1>
  <p>程序判定每一格都给出可证伪的读数与不变量；但这不够——同一格还要人眼看一遍，
     标出程序没写进检查里的东西。两者不一致的地方（尤其是「程序全通过、人眼有问题」）
     才是这张页面真正要找的。</p>
  <div class="meta">{''.join(f'<span>{html.escape(item)}</span>' for item in meta)}</div>
</header>
<main>
  <div class="toolbar">
    <label>分类 <select id="f-category"><option value="">全部</option>{category_filter}</select></label>
    <label>筛选 <select id="f-verdict">
      <option value="">全部</option>
      <option value="unreviewed">只看未审核</option>
      <option value="checkfail">只看程序检查失败</option>
      <option value="checkwarn">只看程序有警告</option>
      <option value="disagree">只看「程序通过但人审有问题」</option>
      <option value="diagnostic">只看有诊断</option>
      <option value="pass">只看人审通过</option>
      <option value="maybe">只看人审存疑</option>
      <option value="bad">只看人审有问题</option>
    </select></label>
    <label>搜索 <input type="search" id="f-search" placeholder="key / 标题 / 诊断码"></label>
    <button class="btn" id="do-sweep">开始逐一审核</button>
    <button class="btn primary" id="do-copy">复制结论（到剪贴板）</button>
    <button class="btn" id="do-paste">粘贴导入</button>
    <button class="btn" id="do-clear">清空</button>
    <span class="store" id="store-state">正在检查本机存储…</span>
    <span class="progress"><span class="bar"></span><span id="progress-text"></span></span>
  </div>
  <div class="paste-panel hidden" id="paste-panel">
    <p class="paste-hint">把别处「复制结论」得到的 JSON 粘进来（Ctrl+V），或点「读剪贴板」。
      这里的结论只存在你自己的浏览器里，不会上传到任何地方；合并会按案例覆盖本机已有的结论。</p>
    <textarea id="import-text" rows="5" spellcheck="false"
      placeholder='{{"version": 1, "cases": {{ ... }}}}'></textarea>
    <div class="paste-actions">
      <button class="btn" id="do-read">读剪贴板</button>
      <button class="btn primary" id="do-merge" disabled>合并到本机结论</button>
      <span class="paste-preview" id="paste-preview"></span>
    </div>
  </div>
  {''.join(sections)}
  <h2>全部案例清单<span>人审结论与程序判定对照，红色行=预期不符</span></h2>
  {_sweep_table(measurements)}
  <h2>触发到的诊断码<span>按案例实测汇总</span></h2>
  <p class="cat-what">{html.escape('、'.join(f'{code}×{count}' for code, count in sorted(diagnostic_codes.items())) or '本次没有触发任何诊断')}</p>
</main>
<footer>
  <p>由 <a href="https://github.com/ManimCommunity/Manim" style="color:#b85450">Manim CE {manim.__version__}</a>
     + <strong>manim-lace</strong> 渲染生成 · 每个数字都读自同一次真实求解</p>
  <p>重新生成：<code>python examples/build_review.py</code> ·
     只重算判定：<code>python examples/build_review.py --probe</code> ·
     只渲染一类：<code>python examples/build_review.py --category rosette</code></p>
  <p>人审结论存在浏览器 localStorage 里，导出 JSON 后可提交到仓库并用
     <code>--verdicts</code> 重新载入：<code>python examples/build_review.py --verdicts docs/review-verdicts.json</code></p>
  <p>本页与所有媒体都是生成物，位于 <code>media/review/</code>（该目录不入库）</p>
</footer>
<div class="overlay" id="focus"><div class="ov-head"><h3>逐张审核</h3>
  <span class="ov-channel"></span>
  <span class="ov-hint">← → 切换（保持当前通道）· 1/2/3 判定 · F 或 Esc 关闭</span>
  <button class="btn exit" id="do-exit-focus">退出逐张审核</button></div>
  <div class="ov-body"></div></div>
<script>
window.__REVIEW_SEED__ = {seed_json};
window.__REVIEW_BUILD__ = {json.dumps(time.strftime('%Y-%m-%d %H:%M'))};
window.__REVIEW_QUALITY__ = {json.dumps(quality)};
window.__REVIEW_TAGS__ = {json.dumps(list(DEFECT_TAGS), ensure_ascii=False)};
</script>
<script>{_SCRIPT}</script>
</body>
</html>
"""
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(page, encoding="utf-8")
    return page_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _select_cases(args: argparse.Namespace) -> list[Case]:
    if args.cases:
        wanted = [key.strip() for key in args.cases.split(",") if key.strip()]
        unknown = [key for key in wanted if key not in {case.key for case in CASES}]
        if unknown:
            raise SystemExit(f"unknown case key(s): {', '.join(unknown)}")
        return [case for case in CASES if case.key in wanted]
    selected: list[Case] = []
    categories = args.category or [category.key for category in CATEGORIES]
    for category in categories:
        if category not in CATEGORY_BY_KEY:
            raise SystemExit(f"unknown category {category!r}")
        selected.extend(cases_for(category))
    if args.limit:
        selected = selected[: args.limit]
    return selected


def _seed_from_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    seed_path = Path(path)
    if not seed_path.is_absolute():
        seed_path = ROOT / seed_path
    if not seed_path.exists():
        raise SystemExit(f"--verdicts file not found: {seed_path}")
    try:
        return json.loads(seed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--verdicts is not valid JSON: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build media/review/index.html from the case catalog")
    parser.add_argument("-q", "--quality", choices=tuple(QUALITY), default="m",
                        help="still quality preset l/m/h/k (default m: 720p)")
    parser.add_argument("--category", action="append", default=None,
                        help="only this category (repeatable)")
    parser.add_argument("--cases", default="", help="comma separated case keys")
    parser.add_argument("--limit", type=int, default=0, help="keep only the first N cases")
    parser.add_argument("--no-render", action="store_true",
                        help="reuse the media on disk, recompute the verdicts and the page")
    parser.add_argument("--probe", action="store_true",
                        help="measure every case and print the table; render nothing")
    parser.add_argument("--no-page", action="store_true",
                        help="render but do not write the page (for trying one case out)")
    parser.add_argument("--no-audit", action="store_true",
                        help="skip the weave_audit defect signatures (faster probe)")
    parser.add_argument("--no-determinism", action="store_true",
                        help="skip the solve-twice check (roughly halves the probe time)")
    parser.add_argument("--verdicts", default=None,
                        help="bake a past review round (exported JSON) into the page")
    args = parser.parse_args(argv)

    selected = _select_cases(args)
    # Building many Manim/Cairo mobjects before running the pure NumPy implicit
    # extractor can leave native state behind that corrupts the later marching-squares
    # frames (observed as a closure ``cell``, or a ``dict_itemiterator``, reaching a
    # float comparison; it kills the run at ``imp-pole`` whenever the implicit cases
    # are measured last).  The page is rebuilt in its declared order below, so only the
    # execution order changes: measure the self-contained implicit cases first, then
    # the rest.  ``--no-render`` needs this too -- it still builds every Manim source.
    processing = list(selected)
    if not args.probe:
        processing.sort(key=lambda case: case.category != "implicit")
    started = time.perf_counter()
    measurements: list[CaseMeasurement] = []
    rendered_now = False
    try:
        for case in processing:
            case_started = time.perf_counter()
            measurement = measure_case(
                case,
                audit=not args.no_audit,
                determinism=not args.no_determinism,
            )
            measurements.append(measurement)
            elapsed = time.perf_counter() - case_started
            if args.probe:
                _print_probe(measurement, elapsed)
                continue
            if not args.no_render:
                window = measurement.window or (8.0, 4.5, np.zeros(2))
                for channel in channels_to_render(measurement):
                    render_case(
                        case,
                        None if channel == "annotate" else channel,
                        window,
                        quality=args.quality,
                    )
                rendered_now = True
            print(f"[review] {case.key:28s} {_summary(measurement)}  {elapsed:.1f}s", flush=True)
            gc.collect()
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)

    if not args.probe:
        by_key = {measurement.case.key: measurement for measurement in measurements}
        measurements = [by_key[case.key] for case in selected]

    if args.probe:
        _print_probe_summary(measurements, time.perf_counter() - started)
        return 0
    if args.no_page:
        print(f"[review] --no-page：渲染了 {len(measurements)} 个案例，未改写页面")
        return 0
    target = write_page(
        measurements,
        quality=args.quality,
        rendered_now=rendered_now,
        seed=_seed_from_file(args.verdicts),
    )
    failed = sum(data.get("failed", 0) for m in measurements for data in m.channels.values())
    mismatched = sum(1 for m in measurements if m.expectation.get("issues"))
    print(
        f"[review] 写入 {target}（{len(measurements)} 个案例，"
        f"检查失败 {failed} 项，目录预期不符 {mismatched} 个）"
        f" 用时 {time.perf_counter() - started:.1f}s"
    )
    return 0


def _summary(measurement: CaseMeasurement) -> str:
    if measurement.case.kind == "error":
        return f"必须失败：{measurement.error or '未抛错（不符预期）'}"
    counts = {channel: data["facts"]["crossings"] for channel, data in measurement.channels.items()}
    failed = sum(data.get("failed", 0) for data in measurement.channels.values())
    warned = sum(data.get("warned", 0) for data in measurement.channels.values())
    issues = len(measurement.expectation.get("issues") or [])
    return (
        "交叉 " + "、".join(f"{channel}={count}" for channel, count in counts.items())
        + f" | 检查失败 {failed} | 警告 {warned} | 预期不符 {issues}"
    )


def _print_probe(measurement: CaseMeasurement, elapsed: float = 0.0) -> None:
    case = measurement.case
    print(f"\n=== {case.key}  [{case.category}]  {case.title}  ({elapsed:.1f}s)", flush=True)
    if case.kind == "error":
        print(f"    必须失败 → {measurement.error or '未抛错（不符预期）'}", flush=True)
        return
    for channel, data in measurement.channels.items():
        facts = data["facts"]
        codes = "、".join(
            f"{diagnostic['code']}(×{diagnostic['count']})"
            for diagnostic in data["diagnostics"]
        ) or "—"
        failing = "、".join(
            f"{check['status']}:{check['key']}：{check['detail']}"
            for check in data["checks"] if check["status"] in ("fail", "warn")
        ) or "—"
        print(
            f"    {channel:12s} 交叉 {facts['crossings']:4d} 自交 {facts['self_crossings']:3d} "
            f"{facts['units']} {facts['pieces']:4d} 交替缺陷 {facts['alternation_defects']:2d} "
            f"放宽 {facts['relaxed']:2d} 类型 {facts['kinds']}",
            flush=True,
        )
        print(f"        诊断 {codes}", flush=True)
        print(f"        失败检查 {failing}", flush=True)
    for issue in measurement.expectation.get("issues") or []:
        print(f"    !! 预期不符：{issue}", flush=True)


def _print_probe_summary(measurements: list[CaseMeasurement], elapsed: float) -> None:
    failed = sum(d.get("failed", 0) for m in measurements for d in m.channels.values())
    warned = sum(d.get("warned", 0) for m in measurements for d in m.channels.values())
    mismatched = [m.case.key for m in measurements if m.expectation.get("issues")]
    kinds = Counter(
        name for m in measurements for data in m.channels.values()
        for name in data["facts"]["kinds"]
    )
    print("\n" + "=" * 78)
    print(f"案例 {len(measurements)} 个，用时 {elapsed:.1f}s")
    print(f"检查失败合计 {failed} 项 · 警告 {warned} 项")
    print(f"目录预期不符 {len(mismatched)} 个：{'、'.join(mismatched) or '无'}")
    print(f"实测到的事件类型：{dict(sorted(kinds.items()))}")


if __name__ == "__main__":
    raise SystemExit(main())
