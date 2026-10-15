"""Geometry-only stroke renderer: cut centerlines around underpasses.

This module does not import Manim. It creates ordered polyline pieces that a
Manim adapter can turn into VMobjects. End caps and shallow-angle masking are a
visual approximation, not exact polygon clipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..diagnostics import Diagnostic, Severity
from ..model import CapStyle, CrossingEvent, PolylinePath, WeaveTopology
from ..style.caps import trim_cut_half_length, validate_cover_allowance
from .order import paint_order


@dataclass(slots=True)
class StrokePiece:
    """One visible centerline piece.

    ``draw_index`` is the position in the deterministic painter order computed from
    the over/under assignments: a piece of an under path always comes before the
    pieces of the paths that are over it. Opaque rendering does not depend on it, but
    it keeps imperfect cut ends covered (SPEC FR-046 determinism).
    """

    piece_id: str
    path_id: str
    points: np.ndarray
    arc_start: float
    arc_end: float
    closed: bool = False
    draw_index: int = 0


@dataclass(slots=True)
class StrokeRenderResult:
    pieces: list[StrokePiece]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def ordered_pieces(self) -> list[StrokePiece]:
        """Pieces in the deterministic draw order (see ``StrokePiece.draw_index``)."""
        return sorted(self.pieces, key=lambda piece: (piece.draw_index, piece.piece_id))

    @property
    def draw_order(self) -> list[str]:
        """Piece IDs in draw order, for inspection, animation and tests."""
        return [piece.piece_id for piece in self.ordered_pieces()]


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


def _fully_cut_diagnostic(path: PolylinePath, *, closed_seam: bool) -> Diagnostic:
    message = (
        "交叉切口覆盖了整条闭合路径，因此没有可见中心线片段。"
        if closed_seam
        else "交叉切口覆盖了整条开放中心线，因此没有可见片段。"
    )
    return Diagnostic(
        code="RENDER-PATH-FULLY-CUT",
        severity=Severity.WARNING,
        message=message,
        path_ids=(path.path_id,),
        hints=("减小 offset，或为密集／小环路实现独立的局部区域几何策略。",),
    )


def render_stroke_geometry(
    paths: list[PolylinePath],
    crossings: list[CrossingEvent],
    topology: WeaveTopology,
    *,
    offset: float,
    min_sin: float = 0.2,
    overshoot: float = 0.03,
    min_piece_length: float = 1e-7,
    cap_style: CapStyle = "butt",
    cover_allowance: float = 0.0,
) -> StrokeRenderResult:
    """Build visible centerline pieces from crossing events and assignments.

    ``offset`` is the ribbon half-width. The initial half-cut estimate is
    ``offset / max(abs(sin(theta)), min_sin)`` and is intentionally bounded at
    shallow angles. This first implementation is suitable for opaque stroke
    rendering; transparent strokes and exact area clipping are out of scope.

    ``cap_style`` describes how the visible ends of a cut piece are painted. With
    ``round`` or ``square`` caps the paint protrudes half the ribbon width beyond the
    centerline endpoint, so the gap is widened by ``offset`` to keep the over path
    visible. That keeps the piece geometry honest about what the renderer will draw;
    for the exact cap outline use ``style.caps.stroke_piece_outline``.

    ``cover_allowance`` is the cut-end "cover allowance": each cut is shortened by
    ``cover_allowance * offset`` on both sides so the end of the lower strand tucks
    further under the strand on top of it. It may only eat the slack the cut
    already has (``overshoot``), so the visible end never reaches past the true
    crossing; the trimming happens before the cut is clamped and wrapped.

    Guarantees for the emitted pieces of one path: their arc intervals never
    overlap, never cross the removed cut intervals, and a piece is never longer
    than the path itself. ``draw_index`` orders all pieces so that an under path is
    painted before the paths that are over it.
    """
    if offset <= 0 or not np.isfinite(offset):
        raise ValueError("offset must be positive and finite")
    if not 0 < min_sin <= 1:
        raise ValueError("min_sin must be within (0, 1]")
    if not np.isfinite(overshoot) or overshoot < 0:
        raise ValueError("overshoot must be finite and non-negative")
    if not np.isfinite(min_piece_length) or min_piece_length < 0:
        raise ValueError("min_piece_length must be finite and non-negative")
    if cap_style not in ("butt", "round", "square"):
        raise ValueError("cap_style must be 'butt', 'round' or 'square'")
    cover_allowance = validate_cover_allowance(cover_allowance, overshoot)
    path_index_by_id = {p.path_id: i for i, p in enumerate(paths)}
    cuts: dict[str, list[tuple[float, float]]] = {p.path_id: [] for p in paths}
    over_edges: list[tuple[str, str]] = []
    approximate_edges: set[tuple[str, str]] = set()
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
        over_id = crossing.path_b if under_side == "a" else crossing.path_a
        over_edges.append((path_id, over_id))
        if abs(crossing.sin_angle) < min_sin:
            approximate_edges.add((path_id, over_id))
        arc = crossing.s_a if under_side == "a" else crossing.s_b
        path = paths[path_index_by_id[path_id]]
        radius = offset / max(abs(crossing.sin_angle), min_sin)
        radius += overshoot * offset
        if cap_style != "butt":
            # A round or square cap paints half the width past the endpoint.
            radius += offset
        # Trimmed before the cut is clamped to the path ends and wrapped at the seam,
        # because the clamp depends on the untrimmed value.
        radius = trim_cut_half_length(radius, allowance=cover_allowance, offset=offset)
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
        if length <= 0:
            # A zero-length path carries no centerline to draw; the geometry layer
            # already reported GEOM-DEGENERATE-PATH for it.
            continue
        intervals = _merge_intervals(cuts[path.path_id])
        if not intervals:
            pieces.append(StrokePiece(
                piece_id=f"{path.path_id}.piece0", path_id=path.path_id,
                points=path.points.copy(), arc_start=0.0, arc_end=length, closed=path.closed,
            ))
            continue
        seam_tol = 1e-10
        covers_seam = intervals[0][0] <= seam_tol and intervals[-1][1] >= length - seam_tol
        seam_piece: StrokePiece | None = None
        cursor, limit = 0.0, length
        if covers_seam:
            if not path.closed:
                # An open path has no seam to weave around: a cut that reaches both
                # ends removes the whole centerline instead of wrapping around.
                diagnostics.append(_fully_cut_diagnostic(path, closed_seam=False))
                continue
            if len(intervals) == 1:
                diagnostics.append(_fully_cut_diagnostic(path, closed_seam=True))
                continue
            first_end = intervals[0][1]
            last_start = intervals[-1][0]
            intervals = intervals[1:-1]
            # The seam piece spans [last_start, length] U [0, first_end] as one
            # cyclic piece. The remaining visible arc starts at first_end and ends
            # at last_start; using 0/length here would duplicate the seam geometry.
            cursor, limit = first_end, last_start
            if length - last_start + first_end > min_piece_length:
                seam_piece = StrokePiece(
                    piece_id=f"{path.path_id}.piece-seam", path_id=path.path_id,
                    points=_slice_arc(path, last_start, length + first_end),
                    arc_start=last_start, arc_end=length + first_end,
                )
        if seam_piece is not None:
            pieces.append(seam_piece)
        keep: list[tuple[float, float]] = []
        dropped: list[tuple[float, float]] = []
        for start, end in intervals:
            if start - cursor > min_piece_length:
                keep.append((cursor, start))
            elif start > cursor:
                dropped.append((cursor, start))
            cursor = max(cursor, end)
        if limit - cursor > min_piece_length:
            keep.append((cursor, limit))
        elif limit > cursor:
            dropped.append((cursor, limit))
        if dropped:
            diagnostics.append(Diagnostic(
                code="RENDER-PIECE-DROPPED",
                severity=Severity.INFO,
                message=(
                    f"路径 {path.path_id} 上有 {len(dropped)} 段可见中心线短于 min_piece_length，"
                    "未输出为片段。"
                ),
                path_ids=(path.path_id,),
                details={
                    "dropped_count": len(dropped),
                    "longest_dropped": max(end - start for start, end in dropped),
                },
                hints=("减小 min_piece_length 可保留这些极短片段。",),
            ))
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
    if cap_style != "butt":
        diagnostics.append(Diagnostic(
            code="RENDER-CAP-EXTENSION",
            severity=Severity.INFO,
            message=(
                f"cap_style='{cap_style}' 会让可见端头沿切向多出半个线宽，"
                f"断口已额外加宽 {offset:g}；端头轮廓可由 style.caps.stroke_piece_outline 得到。"
            ),
            hints=("改用 cap_style='butt' 可让断口严格停在切口位置。",),
        ))
    if cover_allowance > 0:
        diagnostics.append(Diagnostic(
            code="RENDER-COVER-ALLOWANCE",
            severity=Severity.INFO,
            message=(
                f"端头覆盖余量 cover_allowance={cover_allowance:g}：每个断口两侧各缩短 "
                f"{cover_allowance * offset:g}（= {cover_allowance:g} × offset），"
                f"可见端头退到上方丝带之下（上限 overshoot={overshoot:g}）。"
            ),
            details={
                "cover_allowance": cover_allowance,
                "overshoot": overshoot,
                "trim_per_side": cover_allowance * offset,
            },
            hints=(
                "允许值不超过 overshoot，保证端头不会越过真实交叉点。",
                "这属于几何风格参数：它改变切口，但不改变交叉与上下关系。",
            ),
        ))
    layers, congested = paint_order([path.path_id for path in paths], over_edges)
    exact_edges = [edge for edge in congested if edge not in approximate_edges]
    if congested and len(exact_edges) != len(congested):
        # A cyclic over/under relation is the normal case for two strands that cross an
        # even number of times: the cuts decide visibility, not the paint order. It is
        # only worth reporting where a cut is merely approximate, because there the
        # paint order is what keeps the over path visible.
        diagnostics.append(Diagnostic(
            code="RENDER-DRAW-ORDER-CYCLE",
            severity=Severity.INFO,
            message=(
                "过／欠关系存在环，且环上至少一个断口是浅角近似；"
                "绘制顺序按路径顺序确定性打破，端头形变可能露出近似误差。"
            ),
            path_ids=tuple(sorted({path_id for edge in congested for path_id in edge})),
            details={
                "constraints": [[under, over] for under, over in congested],
                "approximate_constraints": [
                    [under, over] for under, over in congested
                    if (under, over) in approximate_edges
                ],
            },
            hints=("不透明描边只在被钳制的断口处依赖该顺序；增大 min_sin 或减小 offset 可减轻。",),
        ))
    path_position = {path.path_id: index for index, path in enumerate(paths)}
    ordered = sorted(
        pieces,
        key=lambda piece: (
            layers.get(piece.path_id, 0), path_position.get(piece.path_id, 0),
            piece.arc_start, piece.piece_id,
        ),
    )
    for index, piece in enumerate(ordered):
        piece.draw_index = index
    return StrokeRenderResult(pieces=pieces, diagnostics=diagnostics)
