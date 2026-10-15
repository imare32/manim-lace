"""Polyline intersection detection with event-aware deduplication.

This starter implementation prioritizes clear semantics and deterministic
behavior over asymptotic speed. An R-tree/BVH candidate index can be introduced
without changing the event model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CrossingEvent, PolylinePath


@dataclass(slots=True)
class CrossingDetectionResult:
    crossings: list[CrossingEvent]
    diagnostics: list[Diagnostic]


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



def _local_rays(path: PolylinePath, arc: float, point: np.ndarray, tol: float) -> list[np.ndarray]:
    """Return the one or two local branches leaving a curve position."""
    cumulative = path.cumulative_lengths
    length = float(cumulative[-1])
    if path.closed and length > 0:
        arc = arc % length
    idx = int(np.argmin(np.abs(cumulative - arc)))
    if abs(float(cumulative[idx]) - arc) <= tol:
        if path.closed and idx == len(path.points) - 1:
            idx = 0
        if idx == 0:
            if path.closed:
                rays = [path.points[-2] - point, path.points[1] - point]
            else:
                rays = [path.points[1] - point]
        elif idx == len(path.points) - 1:
            rays = [path.points[-2] - point]
        else:
            rays = [path.points[idx - 1] - point, path.points[idx + 1] - point]
    else:
        seg = int(np.clip(np.searchsorted(cumulative, arc, side="right") - 1, 0, len(path.points) - 2))
        rays = [path.points[seg] - point, path.points[seg + 1] - point]
    return [ray / np.linalg.norm(ray) for ray in rays if np.linalg.norm(ray) > tol]


def _classify_vertex_intersection(
    path_a: PolylinePath, path_b: PolylinePath, s_a: float, s_b: float,
    point: tuple[float, float], sin_angle: float, initial_kind: str, tol: float,
) -> str:
    if initial_kind != "endpoint_touch":
        return initial_kind
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
        return "near_tangent" if sin_angle <= 1e-7 else "transverse"
    return "near_tangent"

def detect_crossings(
    paths: list[PolylinePath],
    *,
    position_tol: float = 1e-7,
    angle_tol: float = 1e-8,
) -> CrossingDetectionResult:
    """Find path/path and non-adjacent self-intersections.

    Only ``transverse`` events should normally enter the automatic over/under
    solver. Endpoint contacts, shallow-angle events and overlaps remain in the
    output for diagnosis.
    """
    if position_tol <= 0 or not np.isfinite(position_tol):
        raise ValueError("position_tol must be positive and finite")
    if angle_tol <= 0 or angle_tol >= 1 or not np.isfinite(angle_tol):
        raise ValueError("angle_tol must be finite and within (0, 1)")
    raw_hits: list[_RawHit] = []
    diagnostics: list[Diagnostic] = []
    for i, path_i in enumerate(paths):
        starts_i, ends_i = path_i.points[:-1], path_i.points[1:]
        lens_i = path_i.segment_lengths
        cum_i = path_i.cumulative_lengths
        for j in range(i, len(paths)):
            path_j = paths[j]
            starts_j, ends_j = path_j.points[:-1], path_j.points[1:]
            lens_j = path_j.segment_lengths
            cum_j = path_j.cumulative_lengths
            for seg_i, (a, b) in enumerate(zip(starts_i, ends_i)):
                if lens_i[seg_i] <= position_tol:
                    continue
                box_i_min, box_i_max = np.minimum(a, b), np.maximum(a, b)
                for seg_j, (c, d) in enumerate(zip(starts_j, ends_j)):
                    if i == j and _adjacent_segments(path_i, seg_i, seg_j):
                        continue
                    if lens_j[seg_j] <= position_tol:
                        continue
                    if (np.maximum(c, d) < box_i_min - position_tol).any() or (
                        np.minimum(c, d) > box_i_max + position_tol
                    ).any():
                        continue
                    hit = _segment_hit(
                        a, b, c, d,
                        position_tol=position_tol,
                        angle_tol=angle_tol,
                    )
                    if hit is None:
                        continue
                    u, v, point, sin_angle, kind = hit
                    if kind == "overlap":
                        diagnostics.append(Diagnostic(
                            code="GEOM-COLLINEAR-OVERLAP",
                            severity=Severity.WARNING,
                            message="发现共线重叠线段；该重叠不会作为普通横穿交叉处理。",
                            path_ids=(path_i.path_id, path_j.path_id),
                            details={"segment_a": seg_i, "segment_b": seg_j},
                        ))
                        continue
                    s_i = float(cum_i[seg_i] + u * lens_i[seg_i])
                    s_j = float(cum_j[seg_j] + v * lens_j[seg_j])
                    if i == j and s_i > s_j:
                        s_i, s_j = s_j, s_i
                        seg_i_out, seg_j_out = seg_j, seg_i
                        u_out, v_out = v, u
                    else:
                        seg_i_out, seg_j_out = seg_i, seg_j
                        u_out, v_out = u, v
                    raw_hits.append(_RawHit(
                        path_i=i,
                        path_j=j,
                        segment_i=seg_i_out,
                        segment_j=seg_j_out,
                        u=float(u_out),
                        v=float(v_out),
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
    for index, hit in enumerate(unique):
        p_a, p_b = paths[hit.path_i], paths[hit.path_j]
        kind = _classify_vertex_intersection(
            p_a, p_b, hit.s_i, hit.s_j, hit.point, hit.sin_angle, hit.kind,
            max(position_tol * 8, 1e-8),
        )
        event = CrossingEvent(
            crossing_id=f"X{index:04d}",
            kind=kind,  # type: ignore[arg-type]
            point=hit.point,
            path_a=p_a.path_id,
            path_b=p_b.path_id,
            path_index_a=hit.path_i,
            path_index_b=hit.path_j,
            s_a=hit.s_i,
            s_b=hit.s_j,
            segment_a=hit.segment_i,
            segment_b=hit.segment_j,
            u_a=hit.u,
            u_b=hit.v,
            sin_angle=hit.sin_angle,
        )
        crossings.append(event)
        if kind != "transverse":
            diagnostics.append(Diagnostic(
                code=f"GEOM-{kind.upper()}",
                severity=Severity.WARNING,
                message=f"交叉候选被分类为 {kind}，默认不参与严格自动交替求解。",
                path_ids=(event.path_a, event.path_b),
                crossing_id=event.crossing_id,
                point=event.point,
            ))

    # Cluster crossings that coincide geometrically. Pairwise crossings at a
    # genuine multiway node are not independent binary over/under events.
    adjacency: dict[int, set[int]] = {i: set() for i in range(len(crossings))}
    for left, right in combinations(range(len(crossings)), 2):
        if np.linalg.norm(np.asarray(crossings[left].point) - np.asarray(crossings[right].point)) <= position_tol * 8:
            adjacency[left].add(right)
            adjacency[right].add(left)
    visited: set[int] = set()
    multiway_indices: set[int] = set()
    merge_radius = position_tol * 8
    for root in range(len(crossings)):
        if root in visited:
            continue
        # Use a bounded cluster around one representative point, not transitive
        # connected components: a chain of merely-nearby crossings must not be
        # collapsed into a false multiway node.
        cluster = [root]
        root_point = np.asarray(crossings[root].point)
        for candidate in range(root + 1, len(crossings)):
            if candidate not in visited and np.linalg.norm(root_point - np.asarray(crossings[candidate].point)) <= merge_radius:
                cluster.append(candidate)
        visited.update(cluster)
        involved = {path_id for idx in cluster for path_id in (crossings[idx].path_a, crossings[idx].path_b)}
        if len(involved) >= 3:
            multiway_indices.update(cluster)
            diagnostics.append(Diagnostic(
                code="GEOM-MULTIWAY-CROSSING",
                severity=Severity.WARNING,
                message="多个路径在同一点附近相交；这些事件不会进入默认的二元过／欠求解。",
                path_ids=tuple(sorted(involved)),
                point=crossings[root].point,
                details={"crossing_ids": [crossings[idx].crossing_id for idx in cluster]},
                hints=("通过移动几何避免多线共点，或未来为该节点定义显式的局部穿插规则。",),
            ))
    if multiway_indices:
        crossings = [replace(crossing, kind="multiway") if idx in multiway_indices else crossing
                     for idx, crossing in enumerate(crossings)]
    return CrossingDetectionResult(crossings=crossings, diagnostics=diagnostics)
