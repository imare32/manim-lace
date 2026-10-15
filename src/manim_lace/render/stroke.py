"""Geometry-only stroke renderer: cut centerlines around underpasses.

This module does not import Manim. It creates ordered polyline pieces that a
Manim adapter can turn into VMobjects. End caps and shallow-angle masking are a
visual approximation, not exact polygon clipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CrossingEvent, PolylinePath, WeaveTopology


@dataclass(slots=True)
class StrokePiece:
    piece_id: str
    path_id: str
    points: np.ndarray
    arc_start: float
    arc_end: float
    closed: bool = False


@dataclass(slots=True)
class StrokeRenderResult:
    pieces: list[StrokePiece]
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _point_at(path: PolylinePath, arc: float) -> np.ndarray:
    cumulative = path.cumulative_lengths
    length = float(cumulative[-1])
    if length <= 0:
        return path.points[0].copy()
    if path.closed:
        arc = arc % length
    else:
        arc = float(np.clip(arc, 0.0, length))
    idx = int(np.clip(np.searchsorted(cumulative, arc, side="right") - 1, 0, len(cumulative) - 2))
    seg_len = cumulative[idx + 1] - cumulative[idx]
    ratio = (arc - cumulative[idx]) / seg_len if seg_len > 0 else 0.0
    return path.points[idx] + ratio * (path.points[idx + 1] - path.points[idx])


def _slice_arc(path: PolylinePath, start: float, end: float) -> np.ndarray:
    """Slice an arc-length interval; closed paths may use end > total length."""
    if end <= start:
        return np.vstack((_point_at(path, start), _point_at(path, end)))
    length = path.length
    cumulative = path.cumulative_lengths
    vertices: list[float] = []
    if path.closed:
        base = cumulative[:-1]
        low_k = int(np.floor(start / max(length, 1e-30))) - 1
        high_k = int(np.ceil(end / max(length, 1e-30))) + 1
        for k in range(low_k, high_k + 1):
            vertices.extend((base + k * length).tolist())
    else:
        vertices = cumulative.tolist()
    arcs = [start] + [v for v in vertices if start + 1e-10 < v < end - 1e-10] + [end]
    points = np.array([_point_at(path, arc) for arc in arcs])
    compact = [points[0]]
    for point in points[1:]:
        if np.linalg.norm(point - compact[-1]) > 1e-10:
            compact.append(point)
    if len(compact) == 1:
        compact.append(compact[0].copy())
    return np.asarray(compact)


def _merge_intervals(intervals: list[tuple[float, float]], tol: float = 1e-10) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_intervals = sorted((a, b) for a, b in intervals if b > a)
    out = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        prev_start, prev_end = out[-1]
        if start <= prev_end + tol:
            out[-1] = (prev_start, max(prev_end, end))
        else:
            out.append((start, end))
    return out


def render_stroke_geometry(
    paths: list[PolylinePath],
    crossings: list[CrossingEvent],
    topology: WeaveTopology,
    *,
    offset: float,
    min_sin: float = 0.2,
    overshoot: float = 0.03,
    min_piece_length: float = 1e-7,
) -> StrokeRenderResult:
    """Build visible centerline pieces from crossing events and assignments.

    ``offset`` is the ribbon half-width. The initial half-cut estimate is
    ``offset / max(abs(sin(theta)), min_sin)`` and is intentionally bounded at
    shallow angles. This first implementation is suitable for opaque stroke
    rendering; transparent strokes and exact area clipping are out of scope.
    """
    if offset <= 0 or not np.isfinite(offset):
        raise ValueError("offset must be positive and finite")
    if not 0 < min_sin <= 1:
        raise ValueError("min_sin must be within (0, 1]")
    path_index_by_id = {p.path_id: i for i, p in enumerate(paths)}
    cuts: dict[str, list[tuple[float, float]]] = {p.path_id: [] for p in paths}
    diagnostics: list[Diagnostic] = []
    for crossing in crossings:
        if crossing.kind != "transverse":
            continue
        assignment = topology.assignment_for(crossing.crossing_id)
        if assignment is None:
            diagnostics.append(Diagnostic(
                code="RENDER-MISSING-ASSIGNMENT",
                severity=Severity.WARNING,
                message="交叉缺少上下关系，因此未在该位置切开中心线。",
                path_ids=(crossing.path_a, crossing.path_b),
                crossing_id=crossing.crossing_id,
                point=crossing.point,
            ))
            continue
        under_side = assignment.under_side
        path_id = crossing.path_a if under_side == "a" else crossing.path_b
        arc = crossing.s_a if under_side == "a" else crossing.s_b
        path = paths[path_index_by_id[path_id]]
        radius = offset / max(abs(crossing.sin_angle), min_sin)
        radius += overshoot * offset
        start, end = arc - radius, arc + radius
        if path.closed and path.length > 0:
            if 2 * radius >= path.length:
                cuts[path_id].append((0.0, path.length))
                continue
            start %= path.length
            end %= path.length
            if start <= end and (arc - radius >= 0 and arc + radius <= path.length):
                cuts[path_id].append((start, end))
            elif (arc - radius) < 0:
                cuts[path_id].extend([(0.0, end), (path.length + arc - radius, path.length)])
            elif (arc + radius) > path.length:
                cuts[path_id].extend([(start, path.length), (0.0, arc + radius - path.length)])
            else:
                # Wrapped interval, e.g. arc itself was represented near the seam.
                cuts[path_id].extend([(start, path.length), (0.0, end)])
        else:
            start = max(0.0, start)
            end = min(path.length, end)
            if end > start:
                cuts[path_id].append((start, end))

    pieces: list[StrokePiece] = []
    for path in paths:
        length = path.length
        intervals = _merge_intervals(cuts[path.path_id])
        if not intervals:
            pieces.append(StrokePiece(
                piece_id=f"{path.path_id}.piece0", path_id=path.path_id,
                points=path.points.copy(), arc_start=0.0, arc_end=length, closed=path.closed,
            ))
            continue
        if path.closed and len(intervals) == 1 and intervals[0][0] <= 1e-10 and intervals[0][1] >= length - 1e-10:
            diagnostics.append(Diagnostic(
                code="RENDER-PATH-FULLY-CUT",
                severity=Severity.WARNING,
                message="交叉切口覆盖了整条闭合路径，因此没有可见中心线片段。",
                path_ids=(path.path_id,),
                hints=("减小 offset，或为密集／小环路实现独立的局部区域几何策略。",),
            ))
            continue
        if intervals[0][0] <= 1e-10 and intervals[-1][1] >= length - 1e-10:
            # A cut wraps over the path seam. The seam is not a true endpoint, so
            # merge the first and last kept intervals into one cyclic piece.
            first_end = intervals[0][1]
            last_start = intervals[-1][0]
            intervals = intervals[1:-1]
            if length - last_start + first_end > min_piece_length:
                pts = _slice_arc(path, last_start, length + first_end)
                pieces.append(StrokePiece(
                    piece_id=f"{path.path_id}.piece-seam", path_id=path.path_id,
                    points=pts, arc_start=last_start, arc_end=length + first_end,
                ))
        keep: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in intervals:
            if start - cursor > min_piece_length:
                keep.append((cursor, start))
            cursor = max(cursor, end)
        if length - cursor > min_piece_length:
            keep.append((cursor, length))
        for idx, (start, end) in enumerate(keep):
            points = _slice_arc(path, start, end)
            pieces.append(StrokePiece(
                piece_id=f"{path.path_id}.piece{idx}", path_id=path.path_id,
                points=points, arc_start=start, arc_end=end, closed=False,
            ))
    if any(abs(c.sin_angle) < min_sin for c in crossings if c.kind == "transverse"):
        diagnostics.append(Diagnostic(
            code="RENDER-SHALLOW-ANGLE-APPROXIMATION",
            severity=Severity.INFO,
            message="至少一个浅角交叉的断口使用了受限近似；这不是精确的区域裁剪。",
            hints=("可调整 min_sin；如需严格轮廓请开发实体 Ribbon 后端。",),
        ))
    return StrokeRenderResult(pieces=pieces, diagnostics=diagnostics)
