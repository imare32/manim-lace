"""Programmatic verdicts behind the human review page.

The review page shows every case twice over: once as a render a person looks at, and
once as a set of measured facts and invariant checks. This module is the second half —
it reads a solved :class:`~manim_lace.model.LaceResult` (never the picture) and turns it
into

* **facts** — crossing counts by kind, self-crossings, refinement, over/under sources,
  the worst crossing angle, region/hole/area accounting, diagnostics;
* **checks** — invariants that either hold or do not, each with the number that decided
  it, so "程序判定" is falsifiable instead of a green tick;

The point of pairing it with a person is that a check can only catch what it was written
to catch. The review page therefore keeps the check that *fails*, the check that
*silently passes while the picture is wrong*, and the human note next to each other.

Checks are named after what they measure, and every one reports the measured value in
``detail`` so a disagreement between the page and the eye can be argued about with
numbers.

Nothing here imports Manim at module level: the pure-geometry checks run in the test
suite without it, and the two heavier families (region validity, the weave audit) import
Shapely and the audit script lazily.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from manim_lace.benchmarks import event_digest, piece_digest

#: Check status.
#:
#: ``fail`` is an invariant that did not hold *and* that the engine did not declare —
#: a silent contradiction. ``warn`` is a measurement outside the ideal where the engine
#: already reported the same thing as a diagnostic: a documented degradation a person
#: should look at, not a new defect. ``info`` is a reading, ``skip`` a check that does not
#: apply to this case.
PASS = "pass"
FAIL = "fail"
WARN = "warn"
INFO = "info"
SKIP = "skip"

#: Above this many regions the independent ring-union recomputation is skipped: the
#: verified union is O(n²), and ``region.painted_le_sum`` covers the same class of error.
RING_UNION_MAX_REGIONS = 64


@dataclass(frozen=True, slots=True)
class Check:
    """One invariant, with the measurement that decided it."""

    key: str
    label: str
    status: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    @property
    def warned(self) -> bool:
        return self.status == WARN

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "status": self.status,
                "detail": self.detail}


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def trace_data(result: Any, event_type: str) -> dict[str, Any]:
    """The ``data`` of one trace event type, as the engine emitted it."""
    for event in result.trace:
        if event.event_type == event_type:
            return dict(event.data)
    return {}


def _crossing_kinds(result: Any) -> Counter[str]:
    return Counter(crossing.kind for crossing in result.crossings)


def _assignment_sources(result: Any) -> Counter[str]:
    return Counter(
        assignment.source for assignment in result.topology.assignments.values()
    )


def worst_sin_angle(result: Any) -> float | None:
    """The shallowest crossing on the page — the one a person should look at first."""
    angles = [float(crossing.sin_angle) for crossing in result.crossings]
    return min(angles) if angles else None


# ---------------------------------------------------------------------------
# Facts (the numbers the page prints)
# ---------------------------------------------------------------------------


def alternation_defects(result: Any) -> tuple[int, list[str]]:
    """Visits where a strand lands on the same side twice in a row.

    This is the weave-quality number the eye is asked to confirm: a strict alternation
    solution has zero of them, and a relaxed one has exactly as many as the crossings it
    had to give up. A self-crossing is visited twice by the same path, so both passes are
    counted separately — that is where a "a single path cannot alternate with itself"
    claim would show up if it were true.
    """
    assignments = result.topology.assignments
    defects = 0
    offenders: list[str] = []
    for path in result.paths:
        visits: list[tuple[float, bool, str]] = []
        for crossing in result.crossings:
            record = assignments.get(crossing.crossing_id)
            if record is None:
                continue
            over_is_a = record.over_side == "a"
            if crossing.path_a == path.path_id:
                visits.append((float(crossing.s_a), over_is_a, crossing.crossing_id))
                if crossing.path_b == path.path_id:
                    visits.append((float(crossing.s_b), not over_is_a, crossing.crossing_id))
            elif crossing.path_b == path.path_id:
                visits.append((float(crossing.s_b), not over_is_a, crossing.crossing_id))
        visits.sort()
        for index in range(1, len(visits)):
            if visits[index][1] == visits[index - 1][1]:
                defects += 1
                offenders.append(f"{visits[index][2]}@{path.path_id}")
    return defects, offenders


def crossing_facts(result: Any) -> dict[str, Any]:
    """Everything about the topology stage that a reviewer may want to check by eye."""
    kinds = _crossing_kinds(result)
    sources = _assignment_sources(result)
    cross = result.crossings
    self_crossings = [c.crossing_id for c in cross if c.path_a == c.path_b]
    unassigned = [
        c.crossing_id for c in cross
        if c.kind == "transverse" and c.crossing_id not in result.topology.assignments
    ]
    defects, defect_ids = alternation_defects(result)
    angle = worst_sin_angle(result)
    return {
        "paths": len(result.paths),
        "closed_paths": sum(1 for path in result.paths if path.closed),
        "segments": sum(path.segment_count for path in result.paths),
        "crossings": len(cross),
        "kinds": dict(sorted(kinds.items())),
        "self_crossings": len(self_crossings),
        "self_crossing_ids": self_crossings,
        "refined": sum(1 for c in cross if c.refined),
        "sources": dict(sorted(sources.items())),
        "relaxed": int(sources.get("relaxed", 0)),
        "relaxed_ids": sorted(
            cid for cid, a in result.topology.assignments.items() if a.source == "relaxed"
        ),
        "unassigned": unassigned,
        "mode": result.topology.mode,
        "alternation_defects": defects,
        "defect_ids": defect_ids,
        "worst_sin_angle": angle,
        "crossing_ids": [c.crossing_id for c in cross],
        "crossing_points": [[float(c.point[0]), float(c.point[1])] for c in cross],
    }


def diagnostics_facts(result: Any) -> list[dict[str, Any]]:
    """Diagnostics with their severity, count and machine-readable details."""
    grouped: dict[str, dict[str, Any]] = {}
    for diagnostic in result.diagnostics:
        entry = grouped.setdefault(diagnostic.code, {
            "code": diagnostic.code,
            "severity": diagnostic.severity.value,
            "message": diagnostic.message,
            "count": 0,
            "hints": list(diagnostic.hints),
            "details": {},
        })
        entry["count"] += 1
        if diagnostic.details and not entry["details"]:
            entry["details"] = {
                key: (value if isinstance(value, (int, float, str, bool, list)) else str(value))
                for key, value in diagnostic.details.items()
            }
    return [grouped[code] for code in sorted(grouped)]


def geometry_facts(result: Any) -> dict[str, Any]:
    """Path-level numbers: degenerate paths, closed flags, sampling errors."""
    degenerate: list[str] = []
    curved = 0
    for path in result.paths:
        if path.length <= 1e-12:
            degenerate.append(path.path_id)
        if path.curve is not None:
            curved += 1
    return {
        "degenerate_paths": degenerate,
        "curved_paths": curved,
        "total_length": float(sum(path.length for path in result.paths)),
    }


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def geometry_invariants(result: Any) -> list[Check]:
    """Path-level invariants that hold for any accepted input."""
    checks: list[Check] = []
    bad: list[str] = []
    closed_mismatch: list[str] = []
    for path in result.paths:
        points = np.asarray(path.points, dtype=float)
        if not np.isfinite(points).all():
            bad.append(f"{path.path_id}:非有限坐标")
            continue
        if path.closed and len(points) > 2 and not np.allclose(points[0], points[-1], atol=1e-6):
            closed_mismatch.append(path.path_id)
    checks.append(Check(
        "geom.finite", "坐标有限",
        FAIL if bad else PASS,
        "、".join(bad) if bad else f"{len(result.paths)} 条路径全部有限",
    ))
    checks.append(Check(
        "geom.closed_ring", "闭合路径首尾重合",
        FAIL if closed_mismatch else PASS,
        "、".join(closed_mismatch) if closed_mismatch
        else f"{sum(1 for p in result.paths if p.closed)} 条闭合路径首尾逐位重合",
    ))
    degenerate = [p.path_id for p in result.paths if p.length <= 1e-12]
    checks.append(Check(
        "geom.no_degenerate", "无零长路径",
        INFO if degenerate else PASS,
        f"零长路径 {len(degenerate)} 条（{'、'.join(degenerate)}）"
        if degenerate else "没有零长路径",
    ))
    return checks


def stroke_invariants(result: Any) -> list[Check]:
    """The documented stroke contract: pieces of one path never overlap in arc space."""
    pieces = [piece for piece in result.pieces if hasattr(piece, "arc_start")]
    if not pieces:
        return [Check("stroke.applicable", "stroke 片段不变量", SKIP, "本次不是 stroke 后端")]
    checks: list[Check] = []
    by_path: dict[str, list[Any]] = {}
    for piece in pieces:
        by_path.setdefault(piece.path_id, []).append(piece)
    overlaps: list[str] = []
    out_of_range: list[str] = []
    lengths = {path.path_id: path.length for path in result.paths}
    wrapped: list[str] = []
    for path_id, group in by_path.items():
        spans = sorted((float(p.arc_start), float(p.arc_end)) for p in group)
        length = lengths.get(path_id)
        for start, end in spans:
            if start < -1e-9:
                out_of_range.append(f"{path_id}[{start:.4f},{end:.4f}] 起点为负")
            if length is not None and end - start > length + 1e-9:
                out_of_range.append(
                    f"{path_id}[{start:.4f},{end:.4f}] 长度 {end - start:.4f} 超过路径长 {length:.4f}"
                )
            if length is not None and end > length + 1e-9:
                # Not a violation: a closed path's visible arc that contains the seam is
                # emitted as one wrapping piece (``test_stroke.py`` pins ``arc_end >
                # length``), so the check bounds the *span*, not the end point.
                wrapped.append(f"{path_id}[{start:.4f},{end:.4f}]")
        for (start_a, end_a), (start_b, _) in zip(spans, spans[1:]):
            if end_a > start_b + 1e-9:
                overlaps.append(f"{path_id}:{end_a:.4f}>{start_b:.4f}")
    checks.append(Check(
        "stroke.arc_disjoint", "同路径片段弧长互不重叠",
        FAIL if overlaps else PASS,
        "、".join(overlaps) if overlaps else f"{len(pieces)} 个片段按路径分组互不重叠",
    ))
    checks.append(Check(
        "stroke.arc_bounded", "片段起止与长度合法",
        FAIL if out_of_range else PASS,
        "、".join(out_of_range) if out_of_range
        else (
            "所有片段都满足 起点≥0 且 长度≤路径总长"
            + ("；跨接缝的换行片段：" + "、".join(wrapped[:3]) if wrapped else "")
        ),
    ))
    visible = sum(float(p.arc_end) - float(p.arc_start) for p in pieces)
    total = float(sum(lengths.values()))
    checks.append(Check(
        "stroke.coverage", "可见弧长占比",
        INFO,
        f"可见弧长 {visible:.4f} / 中心线总长 {total:.4f}"
        f"（{100.0 * visible / total:.1f}%，其余是交叉切口）" if total > 0 else "无长度",
    ))
    return checks


def region_invariants(result: Any, *, backend: str = "boolean") -> list[Check]:
    """Ring validity, orientation and area conservation for the area-based backends.

    Four decisions here were made from measurements, not from the docstrings (the probe
    mode is what surfaced them):

    * **The area contract is ``painted_area == union_area``** (the ribbon the engine
      actually built). ``band_area`` is deliberately *not* the reference: it is the
      **sum** of the individual band areas, so it exceeds the visible area by every hidden
      crossing overlap, and comparing against it fails on an ordinary crossing.
    * **A difference is a ``warn``, not a ``fail``, when the engine already reported
      ``REGION-AREA-MISMATCH``.** What this check is for is the *silent* contradiction.
    * **Orientation is only meaningful for rings with area.** The emitted slivers can
      carry a signed area of ~1e-20 whose sign is numerical noise; the engine's own
      ``RegionRing.counter_clockwise`` (``shoelace > 0``) has the same property, so
      degenerate rings are skipped and counted instead of being reported as violations.
    * **Duplicate vertices are a separate, informational finding.** Polygon booleans
      leave consecutive duplicate points (zero-length edges) behind; Shapely then calls
      the polygon invalid, but the measured area is unaffected, so it is reported as a
      reading rather than a failure. It is still worth showing: this repository's history
      is a list of artifacts that came out of exactly such outline noise.

    Needs Shapely (the ``geometry`` extra); the check is reported as ``skip`` when the
    import is unavailable rather than silently passing.
    """
    regions = [piece for piece in result.pieces if hasattr(piece, "exterior")]
    if not regions:
        return [Check("region.applicable", "区域不变量", SKIP, "本次不是 ribbon 后端")]
    try:
        from shapely.geometry import Polygon

        # The engine's verified union, reused rather than re-implemented: it exists
        # precisely because a one-shot union over many parts is unreliable, and an
        # independent recomputation would inherit that unreliability (see ``_covered_area``).
        from manim_lace.render.regions import _covered_area
    except ImportError:  # pragma: no cover - the extra is installed in dev/CI
        return [Check("region.applicable", "区域不变量", SKIP, "缺少 shapely（geometry extra）")]

    def shoelace(points: np.ndarray) -> float:
        return 0.5 * float(np.sum(
            points[:-1, 0] * points[1:, 1] - points[1:, 0] * points[:-1, 1]
        ))

    checks: list[Check] = []
    unclosed: list[str] = []
    orientation: list[str] = []
    area_mismatch: list[str] = []
    noisy: list[str] = []
    degenerate_rings = 0
    hole_roles: Counter[str] = Counter()
    polygons: list[Any] = []
    for region in regions:
        rings = [("exterior", region.exterior), *(
            (hole.role, hole) for hole in region.holes
        )]
        hole_roles.update(hole.role for hole in region.holes)
        shell_area: float | None = None
        hole_area = 0.0
        shell_points: np.ndarray | None = None
        hole_points: list[np.ndarray] = []
        for role, ring in rings:
            points = np.asarray(ring.points, dtype=float)
            if len(points) < 4 or not np.allclose(points[0], points[-1]):
                unclosed.append(f"{region.region_id}.{role}")
                continue
            steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
            repeated = len(points) - len({(round(float(x), 12), round(float(y), 12))
                                          for x, y in points})
            if int((steps <= 1e-12).sum()) or repeated > 1:
                noisy.append(
                    f"{region.region_id}.{role}(零长边 {int((steps <= 1e-12).sum())})"
                )
            area = abs(shoelace(points))
            if area <= 1e-12:
                degenerate_rings += 1
                if role == "exterior":
                    shell_points = points
                continue
            if role == "exterior":
                if shoelace(points) < 0:
                    orientation.append(f"{region.region_id}:外环顺时针（面积 {area:.3g}）")
                shell_area = area
                shell_points = points
            else:
                if shoelace(points) > 0:
                    orientation.append(
                        f"{region.region_id}:{role} 孔洞逆时针（面积 {area:.3g}）"
                    )
                hole_area += area
                hole_points.append(points)
        if shell_area is not None:
            # Recomputed from the rings alone: the piece the renderer fills is the shell
            # minus its holes, and that has to reproduce the area the engine reports.
            expected = abs(shell_area - hole_area)
            if abs(expected - float(region.area)) > max(1e-6 * max(expected, 1.0), 1e-12):
                area_mismatch.append(
                    f"{region.region_id}:环重算 {expected:.6f} vs 引擎 {region.area:.6f}"
                )
            if shell_points is not None:
                # ``buffer(0)`` only cleans duplicate vertices / collinear noise here; the
                # area of a valid ring is preserved, which the check above just proved.
                polygons.append(Polygon(shell_points, hole_points or None).buffer(0))

    checks.append(Check(
        "region.rings_closed", "环闭合且点数够",
        FAIL if unclosed else PASS,
        "、".join(unclosed[:6]) if unclosed
        else f"{len(regions)} 个区域的全部环都首尾重合且至少 4 点",
    ))
    checks.append(Check(
        "region.ring_area_matches", "环的面积与引擎报告一致",
        FAIL if area_mismatch else PASS,
        "、".join(area_mismatch[:6]) if area_mismatch
        else f"{len(regions)} 个区域：外环面积减孔洞面积都等于 region.area",
    ))
    checks.append(Check(
        "region.ring_orientation", "外环逆时针、孔洞顺时针（跳过退化碎片）",
        FAIL if orientation else PASS,
        "、".join(orientation[:6]) if orientation
        else f"全部有面积的环朝向正确（跳过 {degenerate_rings} 个面积≤1e-12 的退化碎片）",
    ))
    checks.append(Check(
        "region.rings_clean", "环上没有零长边或重复顶点",
        INFO if noisy else PASS,
        f"{len(noisy)} 个环带零长边/重复顶点（shapely 会判其无效，但实测面积不受影响）："
        + "、".join(noisy[:5])
        if noisy else "全部环没有重复顶点",
    ))

    accounting = trace_data(result, "region.accounting")
    painted = float(accounting.get("painted_area", 0.0))
    union = float(accounting.get("union_area", 0.0))
    band_sum = float(accounting.get("band_area", 0.0))
    region_sum = float(accounting.get("region_area_sum", 0.0))
    removed = float(accounting.get("removed_area", 0.0))
    # The engine's own contract: both region backends compare areas with a relative
    # ``area_tolerance`` of 1e-6 (``render/regions.py``, ``render/arrangement.py``), so a
    # difference inside it is not a silent inconsistency — checking at 1e-9 here reported
    # failures a thousand times stricter than the code promises.
    tolerance = max(1e-6 * max(union, painted, 1.0), 1e-12)
    # Which reference the engine itself uses is not always ``union_area``: when a split
    # point lands on a vertex it reports ``REGION-SECTION-SEAM`` and says the union of the
    # *sections* is smaller than the ribbon, so the ribbon band union is the honest
    # yardstick (``render/regions.py`` line "reference_area = whole_union if section_seam").
    # On a thin rosette ribbon that difference is 27 world units, so comparing against the
    # wrong one reported a silent inconsistency that the code explicitly accounts for.
    seam = next(
        (diagnostic for diagnostic in result.diagnostics
         if diagnostic.code == "REGION-SECTION-SEAM"),
        None,
    )
    if seam is not None:
        reference = float(seam.details.get("band_area", union))
        reference_note = (
            f"引擎报告 REGION-SECTION-SEAM，故参考面积取整条丝带并集 {reference:.6f}"
            f"（分段并集只有 {union:.6f}）"
        )
    else:
        reference = union
        reference_note = f"参考面积取分段并集 union_area {union:.6f}"
    difference = painted - reference
    declared = {diagnostic.code for diagnostic in result.diagnostics}
    if abs(difference) <= tolerance:
        status, tail = PASS, ""
    elif "REGION-AREA-MISMATCH" in declared:
        status, tail = WARN, "；引擎已自报 REGION-AREA-MISMATCH（文档声明的降级）"
    else:
        status, tail = FAIL, "；引擎没有自报，属于静默不一致"
    checks.append(Check(
        "region.area_conserved", "可见面积 = 构建出的丝带并集",
        status,
        f"可见 painted_area {painted:.6f} vs {reference_note}"
        f"（差 {difference:+.2e}，容差 {tolerance:.1e}）" + tail,
    ))
    # A union can never be larger than the sum of its parts, and this needs no geometry at
    # all: it is arithmetic on two numbers the engine already computed. That is what makes
    # it the right check for a *silent* accounting error. It is the check that found one: on
    # the thin-ribbon rosette the Boolean backend reported ``painted_area`` 37.702956 while
    # its own 161 regions added up to 10.183419, and the engine's guard at the time only
    # looked for ``painted < reference``, so it never noticed. The engine now holds the same
    # bound itself (``render_region_geometry``) and corrects the number when it is violated;
    # this check stays because a second, independent reading of the same invariant is the
    # whole point of auditing. A recomputed union would find the same thing but is O(n²)
    # with the engine's verified-union routine, which is why it is kept for small inputs
    # only.
    inflated = painted - region_sum
    checks.append(Check(
        "region.painted_le_sum", "可见面积不超过区域面积之和",
        FAIL if inflated > tolerance else PASS,
        f"可见 {painted:.6f} vs 各区域面积和 {region_sum:.6f}（超出 {inflated:+.2e}）"
        + ("；并集不可能大于各部件之和" if inflated > tolerance else ""),
    ))
    # Independently rebuild the union from the emitted rings. Gated on the region count:
    # the engine's own ``_covered_area`` (reused here, because a one-shot ``unary_union``
    # can drop a part that only touches its neighbours along an edge) unions one part at a
    # time and tries up to three orders, which is far too slow on a 292-region render.
    if len(regions) > RING_UNION_MAX_REGIONS:
        checks.append(Check(
            "region.rings_area", "区域环的并集面积 = 报告的可见面积",
            SKIP,
            f"{len(regions)} 个区域超过 {RING_UNION_MAX_REGIONS} 的上限，"
            f"独立重算并集过慢，本轮跳过（用 region.painted_le_sum 兜底）",
        ))
    else:
        recomputed = _covered_area(polygons) if polygons else 0.0
        checks.append(Check(
            "region.rings_area", "区域环的并集面积 = 报告的可见面积",
            FAIL if abs(recomputed - painted) > tolerance else PASS,
            f"用 shapely 从环重算 {recomputed:.6f} vs 引擎报告 {painted:.6f}"
            f"（差 {recomputed - painted:+.2e}）",
        ))
    overlap = region_sum - painted
    checks.append(Check(
        "region.no_overlap", "区域之间不重叠",
        (FAIL if overlap > tolerance else PASS) if backend == "arrangement" else INFO,
        f"区域面积和 {region_sum:.6f} vs 可见面积 {painted:.6f}（重叠 {overlap:+.2e}）"
        + ("" if backend == "arrangement" else "：boolean 后端按分段输出，允许重叠并会自报")
    ))
    checks.append(Check(
        "region.area_budget", "丝带面积预算（各丝带之和 → 并集 → 可见）",
        INFO,
        f"各丝带面积之和 {band_sum:.6f} → 并集 {union:.6f}（被交叉隐藏 {removed:.6f}）"
        f" → 可见 {painted:.6f}"
        + (f"，重合 {overlap:.6f}" if abs(overlap) > tolerance else ""),
    ))
    checks.append(Check(
        "region.holes", "孔洞分类",
        INFO,
        (
            "、".join(f"{role}×{count}" for role, count in sorted(hole_roles.items()))
            if hole_roles else "没有孔洞"
        ),
    ))
    return checks


def ensure_audit_probe() -> Any:
    """Import ``weave_audit``, which installs the spy its signatures depend on.

    ``weave_audit`` records what ``mark_flush_edges`` was called with *during a solve*, so
    importing it after the geometry exists leaves the recorder empty and every self-crossing
    edge then looks like a defect that is on no lens boundary. Callers must therefore
    prepare the probe **before** building, which :func:`examples.build_review.measure_case`
    does; :func:`audit_signatures` additionally checks that the recorded regions are the
    ones it is judging and reports ``skip`` instead of inventing failures when they are not.
    """
    ROOT = Path(__file__).resolve().parents[1]
    bench = str(ROOT / "benchmarks")
    if bench not in sys.path:
        sys.path.insert(0, bench)
    import weave_audit  # noqa: PLC0415

    return weave_audit


def audit_signatures(result: Any) -> list[Check]:
    """The defect signatures ``benchmarks/weave_audit.py`` hunts for.

    Reused rather than re-implemented: a stroked edge inside the painted ribbon that is
    on no lens boundary, a lens boundary piece no stroke covers, and a stroke end that
    dangles inside the ribbon. These are the failures a person notices by eye and a
    plain geometry check misses.
    """
    try:
        weave_audit = ensure_audit_probe()
    except Exception as exc:  # pragma: no cover - audit is a dev tool
        return [Check("audit.applicable", "编织缺陷签名", SKIP, f"审计脚本不可用：{exc}")]

    regions = [piece for piece in result.pieces if hasattr(piece, "exterior")]
    if not regions:
        return [Check("audit.applicable", "编织缺陷签名", SKIP, "本次不是 ribbon 后端")]
    recorded = list(weave_audit.CAPTURED.get("regions") or ())
    if [id(region) for region in recorded] != [id(region) for region in regions]:
        return [Check(
            "audit.applicable", "编织缺陷签名",
            SKIP,
            "审计探针记录的区域不是本次求解的对象（探针安装晚于求解，或数据已过期）："
            "跳过缺陷签名而不是误报",
        )]
    overlay_edges = getattr(result, "outline_edges", ())
    violations, over_marked = weave_audit.audit(regions)
    gaps, gap_length = weave_audit.notch_gaps(regions, overlay_edges)
    dangling = weave_audit.dangling_ends(regions, overlay_edges)
    return [
        Check(
            "audit.defect_edges", "没有画进丝带内部的描边",
            FAIL if violations else PASS,
            f"{len(violations)} 条描边两侧都被覆盖、且不在任何透镜边界上（多画的线）"
            if violations else f"{len(regions)} 个区域的全部描边都在真实边界上",
        ),
        Check(
            "audit.notch_gaps", "编织缺口整段都有描边",
            FAIL if gaps else PASS,
            f"{gaps} 段缺口未描边，合计长度 {gap_length:.4f}（少画的线，断在丝带中间）"
            if gaps else "每条记录的缺口边都被完整描出",
        ),
        Check(
            "audit.dangling_ends", "没有悬在丝带内部的描边端头",
            FAIL if dangling else PASS,
            f"{len(dangling)} 处可见的描边端头断在丝带内部：既不是另一条描边的延续、"
            "拐角或 T 形接合，也没被后画的填充盖住（同一条边被两个区域各描一遍只算一处）"
            if dangling else "所有描边端头都接在别的描边上或落在丝带边界",
        ),
        Check(
            "audit.hidden_but_stroked", "该隐藏的接缝没有被描边",
            INFO,
            f"{len(over_marked)} 条接缝被标记为隐藏",
        ),
    ]


def determinism_check(build: Callable[[], Any]) -> Check:
    """Solve the same case twice; the reported geometry must be byte-identical."""
    first = build()
    second = build()
    crossing_a = event_digest(first.result.crossings)
    crossing_b = event_digest(second.result.crossings)
    piece_a = piece_digest(first.result.pieces) if _digestable(first.result.pieces) else ""
    piece_b = piece_digest(second.result.pieces) if _digestable(second.result.pieces) else ""
    same = crossing_a == crossing_b and piece_a == piece_b
    return Check(
        "determinism.twice", "两次求解结果一致",
        PASS if same else FAIL,
        f"交叉指纹 {crossing_a[:12]} / {crossing_b[:12]}，"
        f"几何指纹 {piece_a[:12] or '—'} / {piece_b[:12] or '—'}",
    )


def _digestable(pieces: list[Any]) -> bool:
    """``piece_digest`` is the stroke contract; region objects carry no arc intervals."""
    return bool(pieces) and all(hasattr(piece, "arc_start") for piece in pieces)


# ---------------------------------------------------------------------------
# The assembled verdict
# ---------------------------------------------------------------------------


def collect_verdict(
    result: Any,
    *,
    backend: str = "boolean",
    rebuild: Callable[[], Any] | None = None,
    audit: bool = True,
    regions: bool = True,
    solve_seconds: float | None = None,
) -> dict[str, Any]:
    """Facts + checks for one solved case, in the shape the review page consumes."""
    checks: list[Check] = []
    checks.extend(geometry_invariants(result))
    if result.render_mode == "stroke":
        checks.extend(stroke_invariants(result))
    else:
        if regions:
            checks.extend(region_invariants(result, backend=backend))
        if audit:
            checks.extend(audit_signatures(result))
    if rebuild is not None:
        checks.append(determinism_check(rebuild))
    if solve_seconds is not None:
        # A reading, not an invariant: the review page is also where an unexpectedly
        # expensive backend should become visible instead of staying in a benchmark log.
        checks.append(Check(
            "performance.solve", "本次求解耗时",
            INFO,
            f"{solve_seconds:.2f}s（{result.render_mode} / {backend}，"
            f"{len(result.crossings)} 交叉 / {len(result.pieces)} 个片段或区域）",
        ))

    facts = crossing_facts(result)
    facts["geometry"] = geometry_facts(result)
    facts["accounting"] = trace_data(result, "region.accounting")
    facts["face_walk"] = trace_data(result, "region.face_walk")
    facts["units"] = "可见片段" if result.render_mode == "stroke" else "可见区域"
    facts["pieces"] = len(result.pieces)
    return {
        "render_mode": result.render_mode,
        "facts": facts,
        "diagnostics": diagnostics_facts(result),
        "checks": [check.as_dict() for check in checks],
        "failed": sum(1 for check in checks if check.failed),
        "warned": sum(1 for check in checks if check.warned),
        "measured": {check.key: check.status for check in checks},
    }
