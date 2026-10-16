"""The review catalog, its programmatic verdicts, and the page contract.

Two layers are tested separately:

* the **pure-geometry** cases (SPEC benchmark set, index scenarios, degenerate shapes)
  are solved through ``LaceEngine`` directly — no Manim — so the expectations the review
  page declares ("this shape must report ``GEOM-COLLINEAR-OVERLAP``", "this one must have
  five self-crossings") are asserted in the default test run;
* the **Manim-facing** cases (adapter, gallery, rosette) go through the real
  ``Lace`` facade and are guarded by ``importorskip("manim")``, like the rest of the
  optional integration tests.

The invariant assertions deliberately list the checks that must hold for every case. The
page is allowed to *show* a failing check for a human to judge; this test is the smaller,
harder promise: geometry never contradicts itself silently, rings are valid, areas
conserve, and the channels agree on the topology.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import review_catalog  # noqa: E402
from review_catalog import (  # noqa: E402
    CASES,
    CATEGORIES,
    CATEGORY_BY_KEY,
    MANIM_CATEGORIES,
    cases_for,
    catalog_stats,
)
from review_checks import collect_verdict  # noqa: E402

from manim_lace import LaceEngine  # noqa: E402
from manim_lace.benchmarks import event_digest, piece_digest  # noqa: E402

#: Engine options a case is allowed to override from the catalog.
ALLOWED_ENGINE_KEYS = {
    "join", "miter_limit", "min_sin", "overshoot", "min_piece_length", "cap_style",
    "cover_allowance", "conflict_strategy", "event_policy", "candidate_strategy", "refine",
}

#: Insist-on invariants: a case that breaks one of these is a defect, not a review topic.
#: ``region.area_conserved`` is deliberately absent: it degrades to a warning exactly when
#: the engine reports ``REGION-AREA-MISMATCH`` itself (see ``review_checks``), and the
#: cases where that happens are documented degradations.
HARD_CHECKS = (
    "geom.finite",
    "geom.closed_ring",
    "stroke.arc_disjoint",
    "stroke.arc_bounded",
    "region.rings_closed",
    "region.ring_area_matches",
    "region.ring_orientation",
    "region.painted_le_sum",
    "region.rings_area",
    "audit.defect_edges",
    "audit.notch_gaps",
    "audit.dangling_ends",
)

#: Pure-geometry cases: solvable through ``LaceEngine`` with no Manim in the loop.
PURE_CASES = tuple(case for case in CASES if case.category not in MANIM_CATEGORIES)

#: ``PURE_PAIRS`` runs every declared channel, including ones a case omits from the page
#: build: the catalog's ``omitted`` is a statement about how expensive a channel is to
#: *render and audit on the page*, not a claim that the case has no such channel.
PURE_PAIRS = tuple(
    (case, channel) for case in PURE_CASES if case.kind != "error" for channel in case.channels
    if channel not in {name for name, _reason in case.omitted}
)
MANIM_CASES = tuple(case for case in CASES if case.category in MANIM_CATEGORIES)


#: Solved results, keyed by case and channel: the expectations, the invariants and the
#: determinism test all look at the same solve, and the heaviest benchmark inputs take
#: seconds each (the 1501-point self-intersecting curve costs ~17s in the Boolean
#: backend), so re-solving per test would dominate the suite.
_SOLVED: dict[tuple[str, str], object] = {}


def _engine(case, channel: str) -> LaceEngine:
    """The engine for one pure-geometry case and channel, the way the page builds it.

    ``source_engine_kwargs`` is the catalog's single definition of what a source implies, so
    this solver and the page's renderer cannot drift into reviewing different pipelines.
    """
    source = case.source()
    offset = case.offset if source.offset is None else float(source.offset)
    mode = case.weave_mode if source.weave_mode is None else str(source.weave_mode)
    render = "stroke" if channel == "stroke" else "ribbon"
    return LaceEngine(
        source.paths,
        offset=offset,
        render_mode=render,
        weave_mode=mode,
        ribbon_backend="boolean" if channel == "stroke" else channel,
        **case.engine,
        **review_catalog.source_engine_kwargs(source),
    )


def _solve_paths(case, channel: str):
    """A case/channel result, solved at most once per session (see ``_SOLVED``)."""
    key = (case.key, channel)
    if key not in _SOLVED:
        _SOLVED[key] = _engine(case, channel).solve()
    return _SOLVED[key]


def _solve_fresh(case, channel: str):
    """A fresh solve, for the determinism test that must not read the cache."""
    return _engine(case, channel).solve()


# ---------------------------------------------------------------------------
# Catalog structure
# ---------------------------------------------------------------------------


def test_catalog_is_structurally_sound() -> None:
    keys = [case.key for case in CASES]
    assert len(keys) == len(set(keys)), "case keys must be unique"
    assert set(catalog_stats()) == {category.key for category in CATEGORIES}
    assert set(catalog_stats().values()) and all(
        count > 0 for count in catalog_stats().values()
    ), "every category must hold at least one case"
    for case in CASES:
        assert case.category in CATEGORY_BY_KEY, case.key
        assert case.kind in {"paths", "manim", "error"}, case.key
        assert case.title and case.prose, case.key
        assert case.offset > 0, case.key
        assert case.weave_mode in {"alternating", "free", "manual"}, case.key
        assert set(case.channels) <= {"stroke", "boolean", "arrangement"}, case.key
        assert set(case.engine) <= ALLOWED_ENGINE_KEYS, (case.key, set(case.engine))
        if case.kind == "error":
            assert case.expect_error, f"{case.key} must name the error it expects"
        else:
            assert case.channels, case.key
        assert case.expect_crossings is None or case.expect_crossings >= 0, case.key
        assert case.expect_min_crossings is None or case.expect_min_crossings >= 0, case.key
        omitted = dict(case.omitted)
        assert set(omitted) <= set(case.channels), (case.key, sorted(omitted))
        for channel, reason in case.omitted:
            assert reason.strip(), f"{case.key}/{channel} must say why it is omitted"
            assert any(char.isdigit() for char in reason), (
                f"{case.key}/{channel} must quote a measured number in its reason"
            )
        assert len(case.channels) > len(omitted), f"{case.key} would have no channel left"
        if case.focus is not None:
            assert case.focus[2] > 0, f"{case.key} focus span must be positive"


def test_every_category_is_described() -> None:
    for category in CATEGORIES:
        assert category.title and category.subtitle and category.what, category.key
        assert cases_for(category.key), category.key


def test_headline_cases_exist() -> None:
    """The categories the page advertises really carry the cases they claim."""
    assert len(cases_for("spec")) == 4, "SPEC §10.2 asks for exactly four input classes"
    assert len(cases_for("index")) == 9, "tests/test_index.py defines nine scenarios"
    keys = {case.key for case in CASES}
    for key in ("deg-collinear-overlap", "deg-t-junction", "deg-pentagram",
                "adp-nonplanar", "ros-n10-pa-l12-o08"):
        assert key in keys


# ---------------------------------------------------------------------------
# Pure-geometry expectations and invariants
# ---------------------------------------------------------------------------


#: Cases whose expectations can be asserted without Manim, each with the channels the page
#: would actually run for it (an omitted channel is too expensive to include).
PURE_CASES_WITH_CHANNELS = tuple(
    (case, tuple(channel for channel in case.channels
                 if channel not in {name for name, _reason in case.omitted}))
    for case in PURE_CASES if case.kind != "error"
)
PURE_CASE_PARAMS = tuple((case, channels) for case, channels in PURE_CASES_WITH_CHANNELS)
PURE_CASE_IDS = [case.key for case, _channels in PURE_CASES_WITH_CHANNELS]


@pytest.mark.parametrize(("case", "channels"), PURE_CASE_PARAMS, ids=PURE_CASE_IDS)
def test_pure_case_meets_its_declared_expectations(case, channels) -> None:
    """Assert the catalog's expectations the way the page does: across the case's channels.

    A diagnostic belongs to a *backend*: ``RENDER-PATH-FULLY-CUT`` only exists in the stroke
    channel and ``REGION-*`` only in the ribbon ones, so asserting per channel would fail
    every case that names a code its other channel reports. What the catalog promises is
    about the case, and the page shows one expectation verdict per case — the same here.
    """
    codes: set[str] = set()
    crossings: set[int] = set()
    self_crossings: set[int] = set()
    for channel in channels:
        result = _solve_paths(case, channel)
        codes |= {diagnostic.code for diagnostic in result.diagnostics}
        crossings.add(len(result.crossings))
        self_crossings.add(sum(1 for c in result.crossings if c.path_a == c.path_b))
    assert len(crossings) == 1, (case.key, crossings)
    assert len(self_crossings) == 1, (case.key, self_crossings)
    measured = crossings.pop()
    measured_self = self_crossings.pop()
    if case.expect_crossings is not None:
        assert measured == case.expect_crossings, (case.key, measured)
    if case.expect_min_crossings is not None:
        assert measured >= case.expect_min_crossings, (case.key, measured)
    if case.expect_self_crossings is not None:
        assert measured_self == case.expect_self_crossings, (case.key, measured_self)
    for code in case.expect_diagnostics:
        assert code in codes, (case.key, sorted(codes))
    if case.expect_any_diagnostics:
        assert any(code in codes for code in case.expect_any_diagnostics), (
            case.key, sorted(codes),
        )
    for code in case.forbid_diagnostics:
        assert code not in codes, (case.key, code)


@pytest.mark.parametrize(("case", "channel"), PURE_PAIRS, ids=lambda item: getattr(item, "key", item))
def test_pure_case_invariants_hold(case, channel) -> None:
    result = _solve_paths(case, channel)
    backend = "boolean" if channel == "stroke" else channel
    verdict = collect_verdict(result, backend=backend, audit=False)
    failed = {
        check["key"] for check in verdict["checks"]
        if check["status"] == "fail" and check["key"] in HARD_CHECKS
    }
    assert not failed, (case.key, channel, failed)


@pytest.mark.parametrize("case", PURE_CASES, ids=lambda case: case.key)
def test_pure_case_solves_deterministically(case) -> None:
    if case.kind == "error":
        pytest.skip("error cases have no geometry to solve twice")
    channel = case.channels[0]
    first = _solve_fresh(case, channel)
    second = _solve_fresh(case, channel)
    assert event_digest(first.crossings) == event_digest(second.crossings)
    if first.render_mode == "stroke":
        assert piece_digest(first.pieces) == piece_digest(second.pieces)


# ---------------------------------------------------------------------------
# Manim-facing cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", MANIM_CASES, ids=lambda case: case.key)
def test_manim_case_is_consistent(case) -> None:
    """One measurement per case: the declared expectations and the channel agreement.

    The audit signatures and the solve-twice check are left to the page (and to the
    pure-geometry tests, which cover the same engine on the same backends): they are the
    two expensive families, and running both here would multiply the suite's runtime
    without asserting anything the page does not already assert per case.
    """
    pytest.importorskip("manim")
    import build_review

    measurement = build_review.measure_case(case, audit=False, determinism=False)
    assert not measurement.expectation["issues"], measurement.expectation["issues"]
    if case.kind != "error":
        agreement = build_review.channel_agreement(measurement)
        assert agreement["ok"], agreement["detail"]


def test_the_adapter_refuses_input_it_cannot_represent() -> None:
    """The two ``必须失败`` cases must really raise, with the text the catalog promises."""
    pytest.importorskip("manim")
    import build_review

    errors = 0
    for case in cases_for("adapter"):
        if case.kind != "error":
            continue
        message = build_review.probe_error(case)
        assert message is not None, f"{case.key} did not raise"
        assert case.expect_error in message, (case.key, message)
        errors += 1
    assert errors == 2


# ---------------------------------------------------------------------------
# Page contract
# ---------------------------------------------------------------------------


def _scratch_page() -> Path:
    """A page path under the git-ignored ``media/`` tree.

    The page tests must not write ``media/review/index.html``: doing so replaced the built
    53-case page with a two-case fragment, which is a side effect a test has no business
    having. The directory is the same scratch tree the builder itself uses.
    """
    scratch = ROOT / "media" / "_review_build"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch / "test_index.html"


def test_page_script_is_valid_javascript() -> None:
    """Lint the page's own script with node, when node is available.

    A review page whose buttons silently do nothing is worse than no page, and a typo in
    a few hundred lines of JavaScript is not something Python tests can see.

    The script is written into the git-ignored ``media/`` tree rather than pytest's
    ``tmp_path``: on this machine the session temp root resolves inside the repository,
    which left an untracked ``pytest-of-<user>/`` directory behind.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    pytest.importorskip("manim")
    import build_review

    scratch = ROOT / "media" / "_review_build"
    scratch.mkdir(parents=True, exist_ok=True)
    script = scratch / "review_page.js"
    script.write_text(build_review._SCRIPT, encoding="utf-8")
    try:
        completed = subprocess.run(
            [node, "--check", str(script)], capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
    finally:
        script.unlink(missing_ok=True)


def test_page_is_written_with_the_review_hooks() -> None:
    """Write the real page for a couple of cases and check the human-review contract."""
    pytest.importorskip("manim")
    import build_review

    selected = [case for case in CASES if case.key in {"deg-pentagram", "deg-t-junction"}]
    measurements = [build_review.measure_case(case, audit=False) for case in selected]
    target = build_review.write_page(
        measurements, quality="l", rendered_now=False, seed=None, target=_scratch_page()
    )
    page = target.read_text(encoding="utf-8")
    for marker in (
        'data-key="deg-pentagram"',
        'data-act="verdict" data-v="pass"',
        'data-act="verdict" data-v="maybe"',
        'data-act="verdict" data-v="bad"',
        'data-act="tag"',
        'data-note',
        'data-act="focus"',
        'id="f-category"',
        'id="f-verdict"',
        'id="f-search"',
        'id="do-copy"',
        'id="do-paste"',
        'id="do-read"',
        'id="do-merge"',
        'id="import-text"',
        'id="paste-panel"',
        'id="store-state"',
        'id="do-exit-focus"',
        "退出逐张审核",
        "程序通过但人审有问题",
        "__REVIEW_SEED__",
    ):
        assert marker in page, marker
    # The page must not claim a verdict the human has not given.
    assert "通过</button>" in page


def test_the_round_travels_through_the_clipboard_not_files() -> None:
    """Import/export is clipboard-based; the browser itself is the storage.

    A reviewer should never have to download a file and hand it back: every verdict is
    written to ``localStorage`` as it is made, and moving a round between machines is a
    copy and a paste. So the page must carry no file input and no download link, must say
    out loud whether the browser is really persisting, and must fall back loudly rather
    than silently when a clipboard API is unavailable.
    """
    pytest.importorskip("manim")
    import build_review

    page = build_review.write_page(
        [build_review.measure_case(case, audit=False, determinism=False)
         for case in CASES if case.key == "deg-pentagram"],
        quality="l", rendered_now=False, seed=None, target=_scratch_page(),
    ).read_text(encoding="utf-8")
    script = build_review._SCRIPT

    assert 'type="file"' not in page, "the file picker is gone"
    assert "link.download" not in script and "URL.createObjectURL" not in script, (
        "no download path"
    )
    assert "navigator.clipboard.writeText" in script, "copy goes to the clipboard"
    assert "navigator.clipboard.readText" in script, "paste can read the clipboard"
    assert "document.execCommand('copy')" in script, "there is a fallback for locked-down contexts"
    assert "window.localStorage.setItem" in script and "window.localStorage.getItem" in script
    assert "storageWorks" in script and "本浏览器禁用了本地存储" in script, (
        "the page has to admit when it cannot persist"
    )
    # The baked ledger is the base and this browser's verdicts sit on top of it.
    assert "Object.keys(base).forEach" in script and "Object.keys(stored).forEach" in script


def test_the_focus_view_has_a_visible_way_out() -> None:
    """Esc/F is not a way out a reviewer can be expected to know: there is a button."""
    pytest.importorskip("manim")
    import build_review

    page = build_review.write_page(
        [build_review.measure_case(case, audit=False, determinism=False)
         for case in CASES if case.key == "deg-pentagram"],
        quality="l", rendered_now=False, seed=None, target=_scratch_page(),
    ).read_text(encoding="utf-8")
    assert '<button class="btn exit" id="do-exit-focus">退出逐张审核</button>' in page
    assert "getElementById('do-exit-focus')" in build_review._SCRIPT
    assert "closeFocus()" in build_review._SCRIPT
    # The button lives in the overlay header, so it is only visible while reviewing.
    assert ".ov-head .btn.exit" in build_review._CSS


def test_page_bakes_a_past_round_into_the_seed() -> None:
    pytest.importorskip("manim")
    import build_review

    seed = {"version": 1, "cases": {"deg-pentagram": {"verdict": "bad", "tags": ["缺口"],
                                                     "note": "尖端有一处缺口"}}}
    measurements = [build_review.measure_case(build_review.CASES[0])]
    target = build_review.write_page(
        measurements, quality="l", rendered_now=False, seed=seed, target=_scratch_page()
    )
    page = target.read_text(encoding="utf-8")
    assert "尖端有一处缺口" in page
    assert '"verdict": "bad"' in page


# ---------------------------------------------------------------------------
# The checks themselves
# ---------------------------------------------------------------------------


def _fake_region(region_id: str, width: float, height: float, x: float, y: float):
    """One rectangular ribbon region with counter-clockwise rings, no holes."""
    points = np.array([
        [x, y], [x + width, y], [x + width, y + height], [x, y + height], [x, y],
    ])
    from manim_lace.render.regions import RegionRing, RibbonRegion

    ring = RegionRing(points=points, role="exterior")
    return RibbonRegion(region_id=region_id, path_id="P0000", exterior=ring,
                        holes=[], area=float(width * height), draw_index=0)


class _FakeResult:
    """A ribbon result carrying only what ``region_invariants`` reads."""

    def __init__(self, regions, accounting, diagnostics=()):
        from manim_lace.model import TraceEvent

        self.render_mode = "ribbon"
        self.pieces = list(regions)
        self.diagnostics = list(diagnostics)
        self.crossings = []
        self.paths = []
        self.trace = [TraceEvent(sequence=0, stage="construction",
                                 event_type="region.accounting", message="", data=dict(accounting))]


def test_the_area_check_catches_an_inflated_painted_area() -> None:
    """The check that found the thin-ribbon boolean bug, pinned without the engine.

    ``painted_area`` larger than the area its own regions add up to is impossible for a
    union, and the engine's own guard only looks for ``painted < reference`` — so this is
    exactly the case a silent accounting error takes, and exactly what the check has to
    report as a failure rather than a reading.
    """
    pytest.importorskip("shapely")
    import review_checks

    regions = [
        _fake_region("A", 1.0, 1.0, 0.0, 0.0),
        _fake_region("B", 1.0, 1.0, 1.0, 0.0),
    ]
    honest = {"painted_area": 2.0, "union_area": 2.0, "band_area": 2.0,
              "region_area_sum": 2.0, "removed_area": 0.0}
    checks = {check.key: check for check in review_checks.region_invariants(
        _FakeResult(regions, honest), backend="boolean"
    )}
    assert checks["region.area_conserved"].status == review_checks.PASS
    assert checks["region.rings_area"].status == review_checks.PASS

    inflated = dict(honest, painted_area=7.4)
    checks = {check.key: check for check in review_checks.region_invariants(
        _FakeResult(regions, inflated), backend="boolean"
    )}
    assert checks["region.area_conserved"].status == review_checks.FAIL
    assert "静默不一致" in checks["region.area_conserved"].detail
    assert checks["region.rings_area"].status == review_checks.FAIL


def test_the_area_check_uses_the_section_seam_reference() -> None:
    """When the engine reports a section seam it says the section union is not the ribbon.

    ``render/regions.py`` switches its reference to the ribbon band union there, and the
    check has to switch with it: on the thin rosette the two references differ by 27 world
    units, which is the difference between a failure and the engine's declared behaviour.
    """
    pytest.importorskip("shapely")
    import review_checks

    from manim_lace.diagnostics import Diagnostic, Severity

    regions = [_fake_region("A", 2.0, 2.0, 0.0, 0.0)]
    accounting = {"painted_area": 4.0, "union_area": 2.0, "band_area": 4.0,
                  "region_area_sum": 4.0, "removed_area": 0.0}
    seam = Diagnostic(
        code="REGION-SECTION-SEAM", severity=Severity.INFO, message="",
        details={"section_area": 2.0, "band_area": 4.0},
    )
    checks = {check.key: check for check in review_checks.region_invariants(
        _FakeResult(regions, accounting, diagnostics=[seam]), backend="boolean"
    )}
    assert checks["region.area_conserved"].status == review_checks.PASS
    assert "整条丝带并集" in checks["region.area_conserved"].detail

    without_seam = {check.key: check for check in review_checks.region_invariants(
        _FakeResult(regions, accounting), backend="boolean"
    )}
    assert without_seam["region.area_conserved"].status == review_checks.FAIL


def test_page_script_only_references_markup_the_page_has() -> None:
    """Every id and attribute the review script wires up must exist in the page.

    `node --check` proves the script parses; it cannot prove that ``getElementById`` finds
    anything. A typo there leaves the page looking right and doing nothing, which is the
    one failure a review UI must not have.
    """
    import re

    pytest.importorskip("manim")
    import build_review

    measurements = [build_review.measure_case(case, audit=False, determinism=False)
                    for case in CASES if case.key in {"deg-pentagram", "adp-nonplanar"}]
    page = build_review.write_page(
        measurements, quality="l", rendered_now=False, seed=None, target=_scratch_page()
    ).read_text(encoding="utf-8")

    for name in set(re.findall(r"getElementById\('([^']+)'\)", build_review._SCRIPT)):
        assert f'id="{name}"' in page, f"script looks up #{name}, page has no such id"
    for selector, marker in (
        (".card[data-key]", 'class="card"'),
        (".vbtn[data-v]", 'class="vbtn"'),
        (".ttag[data-t]", 'class="ttag"'),
        ("textarea[data-note]", "data-note"),
        ("[data-act]", "data-act="),
        (".bar", 'class="bar"'),
        (".sweep tr[data-key]", "class='sweep'"),
        (".ov-side", 'class="ov-body"'),
        (".shot img", "<figure class=\"shot\""),
    ):
        assert selector  # documented pairing: selector -> the markup it needs
        assert marker in page, f"script uses {selector}, page has no {marker}"


def test_the_raw_input_channel_is_rendered_first() -> None:
    """Every renderable case gets an ``input`` panel, ahead of the weave backends.

    The row is meant to read "what went in → what each backend made of it": without the
    raw input a reviewer cannot tell "the engine saw the wrong geometry" from "the engine
    wove it wrong". Error cases get no panel at all — there is no geometry to draw.
    """
    pytest.importorskip("manim")
    import build_review

    for case in CASES:
        if case.kind == "error":
            measurement = build_review.measure_case(case, audit=False, determinism=False)
            assert build_review.channels_to_render(measurement) == []
            continue
        if not build_review.channel_plan(case):
            continue
        measurement = build_review.measure_case(case, audit=False, determinism=False)
        channels = build_review.channels_to_render(measurement)
        assert channels[0] == "input", (case.key, channels)
        assert channels.count("input") == 1, (case.key, channels)
        for channel, _backend in build_review.channel_plan(case):
            assert channel in channels, (case.key, channel, channels)


def test_the_page_explains_every_channel_and_stays_readable() -> None:
    """Labels for all five panels, and the contrast fix for the light blocks.

    "目录预期与实测一致" was unreadable in the focus overlay: the block keeps its light
    background there, but inherited the overlay's near-white text. The rule that fixed it
    has to stay, so it is pinned here next to the label set.
    """
    pytest.importorskip("manim")
    import build_review

    measurements = [build_review.measure_case(case, audit=False, determinism=False)
                    for case in CASES if case.key in {"deg-pentagram", "deg-t-junction"}]
    page = build_review.write_page(
        measurements, quality="l", rendered_now=False, seed=None, target=_scratch_page()
    ).read_text(encoding="utf-8")

    for label in ("原始输入", "stroke（中心线切口）", "ribbon · boolean",
                  "ribbon · arrangement", "编织结果（交叉编号）"):
        assert label in page, label
    # The input panel is either rendered (an img carrying its channel) or explicitly
    # reported as missing: the page never drops a panel silently.
    assert ('data-channel="input"' in page
            or '无图（原始输入（中心线 + 检出交叉））' in page), "no input panel at all"

    css = build_review._CSS
    assert ".expect {" in css and "color:var(--ink)" in css.split(".expect {")[1].split("}")[0]
    assert ".ov-side .expect, .ov-side .expect b, .ov-side .look, .ov-side .look b" in css
    assert ".ov-head .ov-channel" in css


def test_the_focus_view_remembers_the_selected_channel() -> None:
    """Arrow keys must keep the panel the reviewer chose instead of snapping back.

    Pinned as a source check because there is no browser in the test run: what has to hold
    is that the chosen channel is stored and that the fall-back reads that stored value.
    """
    pytest.importorskip("manim")
    import build_review

    script = build_review._SCRIPT
    assert "var currentChannel = null;" in script
    assert "if (channel) { currentChannel = channel; }" in script
    assert "if (currentChannel && shots)" in script
    assert "currentChannel = button.__channel;" in script
    """The annotated view must not re-run a channel the case declares it cannot afford.

    It did: ``annotate_base`` read ``case.channels``, so on the two random-walk cases the
    annotated render quietly went back to the Boolean backend the case omits — the same
    >5 minute / 1.7GB one, this time inside the renderer.
    """
    pytest.importorskip("manim")
    import build_review

    for case in CASES:
        if case.kind == "error" or not build_review.channel_plan(case):
            continue
        base = build_review.annotate_base(case)
        assert base in {channel for channel, _backend in build_review.channel_plan(case)}, (
            case.key, base, case.omitted,
        )
        assert base not in {name for name, _reason in case.omitted}, (case.key, base)


def test_the_annotated_view_never_picks_an_omitted_channel() -> None:
    """The annotated view must not re-run a channel the case declares it cannot afford.

    It did: ``annotate_base`` read ``case.channels``, so on the two random-walk cases the
    annotated render quietly went back to the Boolean backend the case omits — the same
    >5 minute / 1.7GB one, this time inside the renderer.
    """
    pytest.importorskip("manim")
    import build_review

    for case in CASES:
        if case.kind == "error" or not build_review.channel_plan(case):
            continue
        base = build_review.annotate_base(case)
        assert base in {channel for channel, _backend in build_review.channel_plan(case)}, (
            case.key, base, case.omitted,
        )
        assert base not in {name for name, _reason in case.omitted}, (case.key, base)


def test_frame_window_never_scales_the_geometry() -> None:
    """Framing is a camera window plus a translation, so widths survive it."""
    pytest.importorskip("manim")
    import build_review

    paths = LaceEngine(
        [np.array([[-2.0, 0.0], [2.0, 0.0]])], offset=0.1
    ).paths
    width, height, centre = build_review.frame_window(paths, 0.1)
    assert width / height == pytest.approx(build_review.ASPECT)
    assert np.allclose(centre, [0.0, 0.0])
    assert width >= 4.0 + 3.9 * 0.1, "the window must leave room for the ribbon width"