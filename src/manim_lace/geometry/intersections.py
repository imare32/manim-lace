"""Polyline intersection detection with event-aware deduplication.

Candidate generation (``grid`` or ``brute_force``) is separated from the exact
segment test, so the acceleration structure only prunes work and can never change
the reported events. Deduplication compares path identity, arc positions, local
neighbourhood and type, not plain point distance.

Events whose two paths expose an evaluable source curve are additionally refined
on that curve (SPEC FR-036, ``geometry/refine.py``); refinement is fail-open, so a
path without a probe keeps the sampled-polyline estimate unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CrossingEvent, CrossingStats, EventPolicy, PolylinePath
from .index import SegmentCandidateIndex, all_pairs, neighbourhood_clusters
from .refine import refine_crossing

CandidateStrategy = Literal["grid", "brute_force"]
CandidateTracer = Callable[[int, int, str, dict[str, Any]], None]

__all__ = [
    "CandidateStrategy",
    "CrossingDetectionResult",
    "CrossingStats",
    "detect_crossings",
]


@dataclass(slots=True)
class CrossingDetectionResult:
    crossings: list[CrossingEvent]
    diagnostics: list[Diagnostic]
    stats: CrossingStats | None = None


@dataclass(frozen=True, slots=True)
class _RawHit:
    path_i: int
    path_j: int
    segment_i: int
    segment_j: int
    u: float
    v: float
    point: tuple[float, float]
    sin_angle: float
    kind: str
    s_i: float
    s_j: float


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _segment_hit(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
    *,
    position_tol: float,
    angle_tol: float,
) -> tuple[float, float, np.ndarray, float, str] | None:
    """Return (u, v, point, abs(sin(angle)), kind), if segments intersect."""
    r, s = b - a, d - c
    len_r, len_s = float(np.linalg.norm(r)), float(np.linalg.norm(s))
    if len_r <= position_tol or len_s <= position_tol:
        return None
    denom = _cross2(r, s)
    sin_angle = abs(denom) / (len_r * len_s)
    qmp = c - a
    if sin_angle < angle_tol:
        # Exact parallel/coincident segments have no unique line intersection.
        # A very shallow but non-parallel crossing must still be considered:
        # angle_tol classifies it as delicate, it must not silently erase it.
        distance = abs(_cross2(qmp, r)) / len_r
        if distance <= position_tol:
            rr = float(r @ r)
            t0, t1 = float((c - a) @ r) / rr, float((d - a) @ r) / rr
            overlap = min(max(t0, t1), 1.0) - max(min(t0, t1), 0.0)
            if overlap * len_r > position_tol:
                return (float("nan"), float("nan"), np.array([np.nan, np.nan]), sin_angle, "overlap")
        if denom == 0.0:
            return None
    u = _cross2(qmp, s) / denom
    v = _cross2(qmp, r) / denom
    tol_u = position_tol / max(len_r, position_tol)
    tol_v = position_tol / max(len_s, position_tol)
    if not (-tol_u <= u <= 1 + tol_u and -tol_v <= v <= 1 + tol_v):
        return None
    u, v = float(np.clip(u, 0, 1)), float(np.clip(v, 0, 1))
    p = a + u * r
    endpoint = (u <= tol_u or u >= 1 - tol_u or v <= tol_v or v >= 1 - tol_v)
    if endpoint:
        kind = "endpoint_touch"
    elif sin_angle <= angle_tol * 10:
        kind = "near_tangent"
    else:
        kind = "transverse"
    return u, v, p, sin_angle, kind


def _adjacent_segments(path: PolylinePath, i: int, j: int) -> bool:
    if i == j or abs(i - j) == 1:
        return True
    if path.closed and {i, j} == {0, path.segment_count - 1}:
        return True
    return False


def _arc_distance(a: float, b: float, length: float, closed: bool) -> float:
    delta = abs(a - b)
    return min(delta, max(0.0, length - delta)) if closed and length > 0 else delta



def _branch_ray(
    points: np.ndarray,
    index: int,
    direction: int,
    origin: np.ndarray,
    *,
    closed: bool,
    tol: float,
) -> np.ndarray | None:
    """First point along the walk from ``index`` (inclusive) that differs from ``origin``.

    Coincident repeated vertices are skipped. Without this, a duplicated sample
    collapses one local branch, which silently demotes a genuine vertex crossing
    to ``endpoint_touch`` and removes it from strict alternation.
    """
    count = len(points) - 1 if closed else len(points)
    if count <= 0:
        return None
    cursor = index % count if closed else index
    for _ in range(count):
        if not closed and (cursor < 0 or cursor >= count):
            return None
        delta = points[cursor] - origin
        if float(np.linalg.norm(delta)) > tol:
            return delta
        cursor = (cursor + direction) % count if closed else cursor + direction
    return None


def _local_rays(path: PolylinePath, arc: float, point: np.ndarray, tol: float) -> list[np.ndarray]:
    """Return the one or two local branches leaving a curve position."""
    points = path.points
    closed = path.closed and path.length > 0
    if closed:
        arc = arc % path.length
    cumulative = path.cumulative_lengths
    idx = int(np.argmin(np.abs(cumulative - arc)))
    if abs(float(cumulative[idx]) - arc) <= tol:
        if closed and idx == len(points) - 1:
            idx = 0
        back_index, forward_index = idx - 1, idx + 1
    else:
        seg = int(np.clip(np.searchsorted(cumulative, arc, side="right") - 1, 0, len(points) - 2))
        back_index, forward_index = seg, seg + 1
    rays: list[np.ndarray] = []
    for index, direction in ((back_index, -1), (forward_index, 1)):
        delta = _branch_ray(points, index, direction, point, closed=closed, tol=tol)
        if delta is not None:
            rays.append(delta / float(np.linalg.norm(delta)))
    return rays


def _classify_vertex_intersection(
    path_a: PolylinePath, path_b: PolylinePath, s_a: float, s_b: float,
    point: tuple[float, float], sin_angle: float, initial_kind: str,
    angle_threshold: float, tol: float,
) -> str:
    """Resolve the event kind from the local branch structure and the angle.

    ``sin_angle`` is the chord angle, or the refined tangent angle when the
    crossing could be solved on the source curves. Only the angle test reacts to
    refinement; the branch alternation stays a property of the sampled geometry.
    """
    if initial_kind != "endpoint_touch":
        # Not a segment-endpoint hit: no branch terminates here, so the verdict is
        # the crossing angle itself.
        return "near_tangent" if sin_angle <= angle_threshold else "transverse"
    external_a = (not path_a.closed) and min(abs(s_a), abs(path_a.length - s_a)) <= tol
    external_b = (not path_b.closed) and min(abs(s_b), abs(path_b.length - s_b)) <= tol
    if external_a or external_b:
        return "endpoint_touch"
    p = np.asarray(point, dtype=float)
    rays_a = _local_rays(path_a, s_a, p, tol)
    rays_b = _local_rays(path_b, s_b, p, tol)
    if len(rays_a) != 2 or len(rays_b) != 2:
        return "endpoint_touch"
    rays = [(float(np.arctan2(ray[1], ray[0])) % (2 * np.pi), side)
            for side, group in ((0, rays_a), (1, rays_b)) for ray in group]
    labels = [side for _, side in sorted(rays)]
    alternates = all(labels[i] != labels[(i + 1) % len(labels)] for i in range(len(labels)))
    if alternates:
        return "near_tangent" if sin_angle <= angle_threshold else "transverse"
    return "near_tangent"

def _flatten_segments(
    paths: list[PolylinePath], position_tol: float
) -> tuple[list[int], list[int], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Collect every usable segment once, in path/segment order.

    Returns ``(path_indices, segment_indices, starts, ends, arc_starts, lengths)``
    for the segments longer than ``position_tol``.
    """
    path_indices: list[int] = []
    segment_indices: list[int] = []
    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []
    arc_starts: list[float] = []
    lengths: list[float] = []
    for path_index, path in enumerate(paths):
        if path.length <= position_tol:
            continue
        segment_lengths = path.segment_lengths
        cumulative = path.cumulative_lengths
        for segment in range(path.segment_count):
            if segment_lengths[segment] <= position_tol:
                continue
            path_indices.append(path_index)
            segment_indices.append(segment)
            starts.append(path.points[segment])
            ends.append(path.points[segment + 1])
            arc_starts.append(float(cumulative[segment]))
            lengths.append(float(segment_lengths[segment]))
    return (
        path_indices,
        segment_indices,
        np.asarray(starts, dtype=float).reshape(-1, 2),
        np.asarray(ends, dtype=float).reshape(-1, 2),
        np.asarray(arc_starts, dtype=float),
        np.asarray(lengths, dtype=float),
    )


def detect_crossings(
    paths: list[PolylinePath],
    *,
    position_tol: float = 1e-7,
    angle_tol: float = 1e-8,
    candidate_strategy: CandidateStrategy = "grid",
    refine: bool = True,
    policy: EventPolicy | None = None,
    candidate_tracer: CandidateTracer | None = None,
) -> CrossingDetectionResult:
    """Find path/path and non-adjacent self-intersections.

    Only ``transverse`` events should normally enter the automatic over/under
    solver. Endpoint contacts, shallow-angle events and overlaps remain in the
    output for diagnosis.

    ``candidate_strategy`` selects how candidate segment pairs are enumerated:
    ``grid`` prunes with a deterministic uniform grid, ``brute_force`` checks
    every pair. Both must produce identical events; the grid exists only to
    reduce the number of exact tests (SPEC FR-035).

    ``refine`` locally re-solves each hit on the source curves when both paths
    expose one (SPEC FR-036). Paths built from plain coordinates have no probe, so
    their events stay exactly as the sampled polyline reported them.

    ``policy`` decides what happens to candidates that are not plain transverse
    crossings: keep them as diagnosed facts (the default), promote point-like
    contacts into the weave, or drop the warning. It never removes geometry from the
    result, and it never turns an overlap or a multiway node into a binary crossing.
    """
    if position_tol <= 0 or not np.isfinite(position_tol):
        raise ValueError("position_tol must be positive and finite")
    if angle_tol <= 0 or angle_tol >= 1 or not np.isfinite(angle_tol):
        raise ValueError("angle_tol must be finite and within (0, 1)")
    if candidate_strategy not in ("grid", "brute_force"):
        raise ValueError("candidate_strategy must be 'grid' or 'brute_force'")
    if not isinstance(refine, bool):
        raise ValueError("refine must be a bool")
    policy = policy if policy is not None else EventPolicy()
    if not isinstance(policy, EventPolicy):
        raise ValueError("policy must be an EventPolicy or None")
    # Delicate-angle threshold: below it a crossing is reported as near-tangent
    # instead of transversally woven. Shared by the chord and the refined angle.
    angle_threshold = angle_tol * 10
    raw_hits: list[_RawHit] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        if path.length <= position_tol:
            diagnostics.append(Diagnostic(
                code="GEOM-DEGENERATE-PATH",
                severity=Severity.WARNING,
                message=(
                    f"路径 {path.path_id} 的总长度不超过位置容差，不会产生有意义的交叉事件，"
                    "也不会生成描边片段。"
                ),
                path_ids=(path.path_id,),
                hints=("检查采样是否在不同参数处返回了重复坐标；重复顶点无法参与编织。",),
            ))
    (
        path_indices,
        segment_indices,
        starts,
        ends,
        arc_starts,
        segment_lengths,
    ) = _flatten_segments(paths, position_tol)
    segment_count = len(path_indices)
    boxes_min = np.minimum(starts, ends)
    boxes_max = np.maximum(starts, ends)
    if candidate_strategy == "brute_force":
        candidate_pairs = all_pairs(segment_count)
        grid_cells = 0
    else:
        found = SegmentCandidateIndex.build(
            boxes_min, boxes_max, expansion=position_tol
        ).candidates()
        candidate_pairs = found.pairs
        grid_cells = found.grid_cells
    # Scalar lists keep the per-pair bounding-box rejection out of NumPy; it runs
    # once per candidate pair and is the dominant cost on crossing-dense inputs.
    box_low = boxes_min.tolist()
    box_high = boxes_max.tolist()

    pair_checks = 0
    for first, second in candidate_pairs:
        path_first = path_indices[first]
        path_second = path_indices[second]
        if path_first == path_second and _adjacent_segments(
            paths[path_first], segment_indices[first], segment_indices[second]
        ):
            continue
        first_low, first_high = box_low[first], box_high[first]
        second_low, second_high = box_low[second], box_high[second]
        if (
            second_high[0] < first_low[0] - position_tol
            or second_high[1] < first_low[1] - position_tol
            or second_low[0] > first_high[0] + position_tol
            or second_low[1] > first_high[1] + position_tol
        ):
            continue
        pair_checks += 1
        hit = _segment_hit(
            starts[first], ends[first], starts[second], ends[second],
            position_tol=position_tol,
            angle_tol=angle_tol,
        )
        if hit is None:
            if candidate_tracer is not None:
                candidate_tracer(first, second, "no_hit", {
                    "path_i": path_first, "path_j": path_second,
                    "segment_i": segment_indices[first], "segment_j": segment_indices[second],
                })
            continue
        if candidate_tracer is not None:
            candidate_tracer(first, second, "hit", {
                "path_i": path_first, "path_j": path_second,
                "segment_i": segment_indices[first], "segment_j": segment_indices[second],
                "kind": hit[4],
                "point": (float(hit[2][0]), float(hit[2][1])),
            })
        u, v, point, sin_angle, kind = hit
        seg_i, seg_j = segment_indices[first], segment_indices[second]
        if kind == "overlap":
            if policy.collinear_overlap == "diagnose":
                diagnostics.append(Diagnostic(
                    code="GEOM-COLLINEAR-OVERLAP",
                    severity=Severity.WARNING,
                    message="发现共线重叠线段；该重叠不会作为普通横穿交叉处理。",
                    path_ids=(paths[path_first].path_id, paths[path_second].path_id),
                    details={"segment_a": seg_i, "segment_b": seg_j},
                ))
            continue
        s_i = float(arc_starts[first] + u * segment_lengths[first])
        s_j = float(arc_starts[second] + v * segment_lengths[second])
        if path_first == path_second and s_i > s_j:
            s_i, s_j = s_j, s_i
            seg_i, seg_j = seg_j, seg_i
            u, v = v, u
        raw_hits.append(_RawHit(
            path_i=path_first,
            path_j=path_second,
            segment_i=seg_i,
            segment_j=seg_j,
            u=float(u),
            v=float(v),
            point=(float(point[0]), float(point[1])),
            sin_angle=float(sin_angle),
            kind=kind,
            s_i=s_i,
            s_j=s_j,
        ))

    # Merge duplicate reports generated where a crossing lies at polyline vertices.
    raw_hits.sort(key=lambda h: (h.path_i, h.path_j, h.s_i, h.s_j, h.kind))
    unique: list[_RawHit] = []
    for hit in raw_hits:
        duplicate = False
        for prior in reversed(unique):
            if (prior.path_i, prior.path_j) != (hit.path_i, hit.path_j):
                if (prior.path_i, prior.path_j) < (hit.path_i, hit.path_j):
                    break
                continue
            if np.linalg.norm(np.asarray(prior.point) - np.asarray(hit.point)) > position_tol * 4:
                continue
            path_i, path_j = paths[hit.path_i], paths[hit.path_j]
            if _arc_distance(prior.s_i, hit.s_i, path_i.length, path_i.closed) <= position_tol * 8 and \
               _arc_distance(prior.s_j, hit.s_j, path_j.length, path_j.closed) <= position_tol * 8:
                duplicate = True
                break
        if not duplicate:
            unique.append(hit)

    crossings: list[CrossingEvent] = []
    refined_events = 0
    for index, hit in enumerate(unique):
        p_a, p_b = paths[hit.path_i], paths[hit.path_j]
        point, sin_angle = hit.point, hit.sin_angle
        s_i, s_j = hit.s_i, hit.s_j
        segment_i, segment_j = hit.segment_i, hit.segment_j
        u_a, u_b = hit.u, hit.v
        parameter_a: float | None = None
        parameter_b: float | None = None
        refined = None
        if refine:
            refined = refine_crossing(
                p_a, p_b,
                segment_a=hit.segment_i, u_a=hit.u,
                segment_b=hit.segment_j, u_b=hit.v,
                point=hit.point, position_tol=position_tol,
            )
        if refined is not None and hit.path_i == hit.path_j and refined.s_a > refined.s_b:
            # Both sides live on one path: the two passes must stay ordered by arc
            # length even after the refinement moved them.
            refined = refined.swapped()
        if refined is not None:
            point, sin_angle = refined.point, refined.sin_angle
            s_i, s_j = refined.s_a, refined.s_b
            segment_i, segment_j = refined.segment_a, refined.segment_b
            u_a, u_b = refined.u_a, refined.u_b
            parameter_a, parameter_b = refined.parameter_a, refined.parameter_b
            refined_events += 1
        kind = _classify_vertex_intersection(
            p_a, p_b, s_i, s_j, point, sin_angle, hit.kind,
            angle_threshold, max(position_tol * 8, 1e-8),
        )
        event = CrossingEvent(
            crossing_id=f"X{index:04d}",
            kind=kind,  # type: ignore[arg-type]
            point=point,
            path_a=p_a.path_id,
            path_b=p_b.path_id,
            path_index_a=hit.path_i,
            path_index_b=hit.path_j,
            s_a=s_i,
            s_b=s_j,
            segment_a=segment_i,
            segment_b=segment_j,
            u_a=u_a,
            u_b=u_b,
            sin_angle=sin_angle,
            refined=refined is not None,
            parameter_a=parameter_a,
            parameter_b=parameter_b,
        )
        if kind in ("endpoint_touch", "near_tangent"):
            decision = getattr(policy, kind)
            if decision == "weave":
                # Head-on request: the contact becomes an ordinary crossing so it
                # enters the over/under solver. The original classification stays
                # visible in the diagnostic and in the trace.
                diagnostics.append(Diagnostic(
                    code="GEOM-CONTACT-WOVEN",
                    severity=Severity.INFO,
                    message=(
                        f"按事件策略把 {kind} 事件 {event.crossing_id} 提升为普通横穿，"
                        "参与过／欠求解。"
                    ),
                    path_ids=(event.path_a, event.path_b),
                    crossing_id=event.crossing_id,
                    point=event.point,
                    details={"classified_as": kind},
                ))
                event = replace(event, kind="transverse")
            elif decision == "diagnose":
                diagnostics.append(Diagnostic(
                    code=f"GEOM-{kind.upper()}",
                    severity=Severity.WARNING,
                    message=f"交叉候选被分类为 {kind}，默认不参与严格自动交替求解。",
                    path_ids=(event.path_a, event.path_b),
                    crossing_id=event.crossing_id,
                    point=event.point,
                ))
        crossings.append(event)

    # Cluster crossings that coincide geometrically. Pairwise crossings at a
    # genuine multiway node are not independent binary over/under events. The
    # clusters are bounded around one representative point, not transitive
    # connected components: a chain of merely-nearby crossings must not be
    # collapsed into a false multiway node (SPEC FR-034).
    merge_radius = position_tol * 8
    crossing_points = np.asarray(
        [crossing.point for crossing in crossings], dtype=float
    ).reshape(-1, 2)
    multiway_indices: set[int] = set()
    for cluster in neighbourhood_clusters(crossing_points, merge_radius):
        involved = {
            path_id for idx in cluster for path_id in (crossings[idx].path_a, crossings[idx].path_b)
        }
        if len(involved) >= 3:
            multiway_indices.update(cluster)
            if policy.multiway != "diagnose":
                continue
            diagnostics.append(Diagnostic(
                code="GEOM-MULTIWAY-CROSSING",
                severity=Severity.WARNING,
                message="多个路径在同一点附近相交；这些事件不会进入默认的二元过／欠求解。",
                path_ids=tuple(sorted(involved)),
                point=crossings[cluster[0]].point,
                details={"crossing_ids": [crossings[idx].crossing_id for idx in cluster]},
                hints=("通过移动几何避免多线共点，或未来为该节点定义显式的局部穿插规则。",),
            ))
    if multiway_indices:
        crossings = [replace(crossing, kind="multiway") if idx in multiway_indices else crossing
                     for idx, crossing in enumerate(crossings)]
    return CrossingDetectionResult(
        crossings=crossings,
        diagnostics=diagnostics,
        stats=CrossingStats(
            strategy=candidate_strategy,
            segment_count=segment_count,
            candidate_pairs=len(candidate_pairs),
            pair_checks=pair_checks,
            grid_cells=grid_cells,
            refined_events=refined_events,
        ),
    )
