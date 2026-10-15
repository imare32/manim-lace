"""第二条编织通道: **中心线 + ``stroke_width`` + 绘制顺序**(见 `PROGRESS.md` §3 P0-6)。

:class:`~manim_lace.interlacing.Interlacing` 把丝带当作**区域(polygon)**: 区域要被对方切开,
于是需要"一次交叉的四个角点"(偏移线求交 + miter)、配对、挖区间、封口, 还要显式构造孔洞。
本模块换一条路 —— 丝带就是**中心线本身**, 宽度交给渲染器的 ``stroke``:

* **事件** = 中心线交叉的弧长参数(不需要偏移线求交, 也不需要 miter);
* **断口** = 交点两侧 ``offset / |sinθ|``(解析可得; 浅角处把 ``sinθ`` 钳到
  :data:`_SHALLOW_SIN`, 即**故意少切**, 剩下的伸入区靠"压上方后画"盖住);
* **过/欠** = 沿每条路径的通过序列交替赋值(自交交叉的两次通过在通过序列里的位置差恒为奇数
  ⇒ 自洽); 路径之间用 BFS 二着色, 约束成奇环时无解(与 polygon 通道同一限制);
* **孔洞** = 不需要构造: 没被 ``stroke`` 盖住的地方自然是背景;
* **绘制顺序不是必需的**(切口本身就保证可见性); 顺序只在掩盖断口边缘残差时有用。

由此产生的**硬约束**(也见 §3 P0-6): ① 必须**不透明** —— 切口保证的是"谁断开"这个拓扑,
而断口端头是"垂直切断"、真实覆盖边界是斜的, 端头残差靠"不透明 + 顺序"兜住; 半透明下既会露
混色, 也会让整套"覆盖关系"的判定失去意义; ② 浅角交叉残留 ``~offset² · cotθ`` 的三角;
③ 断口不能吃掉本方**作为压上方**的交叉区(:meth:`StrokeWeave._structure_issues` 会检查)。

本模块是**纯几何**(不 import manim), 渲染在 :mod:`manim_lace.lace` 里完成。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from scipy.spatial import cKDTree

from .interlacing import DEFAULT_ATOL, vectorized_intersection

__all__ = [
    "STROKE_UNITS_PER_WIDTH",
    "StrokeWeave",
    "centerline_crossings",
]

#: Manim 的 ``stroke_width`` 与几何宽度的换算: 宽度(单位) ``= stroke_width * 0.01``。
#:
#: 也就是说"半宽 = ``offset``"对应 ``stroke_width = 2 * offset / 0.01``(见 `PROGRESS.md` §3 P0-6)。
STROKE_UNITS_PER_WIDTH = 0.01

#: 浅角保护: ``sinθ`` 的下限。取上限意味着**故意少切**(真实需要 ``offset / sinθ``),
#: 少切出来的伸入区由"压上方后画"覆盖 —— 这条只有在**不透明**下才成立。
_SHALLOW_SIN = 0.2

#: 片段首尾各外延的比例(相对 ``offset``): 让相邻片段重叠, 掩盖抗锯齿接缝。
_OVERSHOOT = 0.03


# --------------------------------------------------------------------------- 求交
def _segment_tables(path: np.ndarray) -> dict:
    """把一条路径整理成"线段表 + 累积弧长", 供求交与按弧长取样共用。"""
    coords = np.asarray(path, dtype=float)
    starts, ends = coords[:-1], coords[1:]
    lengths = np.linalg.norm(ends - starts, axis=1)
    return {
        "coords": coords,
        "starts": starts,
        "ends": ends,
        "lengths": lengths,
        "cumulative": np.concatenate([[0.0], np.cumsum(lengths)]),
        "closed": bool(np.allclose(coords[0], coords[-1])) and len(coords) > 2,
    }


def _pairs_between(first: dict, second: dict, *, same: bool) -> list[tuple[int, int, float, float]]:
    """求两组线段之间的交点, 返回 ``(a 下标, b 下标, ua, ub)``。

    用"按 ``xmin`` 排序 + ``searchsorted`` 筛候选"沿 x 方向剪枝(与
    :meth:`Interlacing._cal_intersections` 同思路), 求交本身复用
    :func:`~manim_lace.interlacing.vectorized_intersection`(尺度无关)。
    ``same`` 为真时只取上三角, 并**排除相邻线段**(它们共享折线角点)。

    求交函数只返回交点坐标, 这里按投影反算参数 —— 参数容差(端点附近)已经在求交函数内部
    用"几何距离 <= ``DEFAULT_ATOL``"处理过, 这里只做投影, 不再引入新的容差。
    """
    starts_a, ends_a = first["starts"], first["ends"]
    starts_b, ends_b = second["starts"], second["ends"]
    if len(starts_a) == 0 or len(starts_b) == 0:
        return []

    xmin_a = np.minimum(starts_a[:, 0], ends_a[:, 0])
    xmax_a = np.maximum(starts_a[:, 0], ends_a[:, 0])
    xmin_b = np.minimum(starts_b[:, 0], ends_b[:, 0])
    xmax_b = np.maximum(starts_b[:, 0], ends_b[:, 0])

    order = np.argsort(xmin_b)
    xmin_b_sorted = xmin_b[order]
    xmax_b_sorted = xmax_b[order]
    sorted_b_start = starts_b[order]
    sorted_b_end = ends_b[order]

    found: list[tuple[int, int, float, float]] = []
    for a in range(len(starts_a)):
        limit = int(np.searchsorted(xmin_b_sorted, xmax_a[a], side="right"))
        if limit <= 0:
            continue
        candidates = np.arange(limit)
        candidates = candidates[xmin_b_sorted[candidates] <= xmax_a[a]]
        candidates = candidates[xmax_b_sorted[candidates] >= xmin_a[a]]
        if same:
            original = order[candidates]
            num = len(starts_a)
            # 相邻线段共享折线角点(闭合路径的首尾段也相邻) —— 它们不是自交
            adjacent = original == a + 1
            if first["closed"]:
                adjacent |= ((a == 0) & (original == num - 1)) | ((original == 0) & (a == num - 1))
            candidates = candidates[(original > a) & ~adjacent]
        if len(candidates) == 0:
            continue
        points, mask = vectorized_intersection(
            starts_a[a],
            ends_a[a],
            sorted_b_start[candidates],
            sorted_b_end[candidates],
        )
        if not mask.any():
            continue
        direction_a = ends_a[a] - starts_a[a]
        norm_a = float(direction_a @ direction_a)
        for slot in np.flatnonzero(mask):
            b_index = int(order[int(candidates[slot])])
            if same and b_index == a:
                continue
            point = points[slot]
            ua = float((point - starts_a[a]) @ direction_a) / norm_a if norm_a > 0 else 0.0
            direction_b = ends_b[b_index] - starts_b[b_index]
            norm_b = float(direction_b @ direction_b)
            ub = float((point - starts_b[b_index]) @ direction_b) / norm_b if norm_b > 0 else 0.0
            found.append((a, b_index, ua, ub))
    return found


def centerline_crossings(paths: Sequence[np.ndarray], *, atol: float = DEFAULT_ATOL) -> list[dict]:
    """求所有**中心线**交叉: 路径之间 + 同一条路径的自交。

    返回:
        字典列表, 每项含 ``i`` / ``j``(``i <= j``, 相等表示自交)、``point``(交点坐标)、
        ``s_i`` / ``s_j``(沿各自路径的弧长参数)。同一位置出现多个交叉(相切接触、三线共点)
        时只保留**一个**: 那种位置上的"谁压谁"没有定义, 交给调用方当作退化跳过。
    """
    tables = [_segment_tables(path) for path in paths]
    crossings: list[dict] = []
    for i, first in enumerate(tables):
        for j in range(i, len(tables)):
            second = tables[j]
            same = i == j
            for a, b, ua, ub in _pairs_between(first, second, same=same):
                arc_a = float(first["cumulative"][a] + ua * first["lengths"][a])
                arc_b = float(second["cumulative"][b] + ub * second["lengths"][b])
                point = first["starts"][a] + ua * (first["ends"][a] - first["starts"][a])
                crossings.append(
                    {"i": i, "j": j, "point": point, "s_i": arc_a, "s_j": arc_b},
                )
    if not crossings:
        return []
    points = np.array([crossing["point"] for crossing in crossings])
    tree = cKDTree(points)
    kept: list[dict] = []
    dropped: set[int] = set()
    for left, right in tree.query_pairs(r=atol):
        dropped.add(max(left, right))
    for index, crossing in enumerate(crossings):
        if index not in dropped:
            kept.append(crossing)
    return kept


# --------------------------------------------------------------------------- 弧长工具
def _arc_point(table: dict, arc: float) -> np.ndarray:
    """折线上给定弧长处的点(闭合路径取模, 开放路径夹到端点)。"""
    cumulative = table["cumulative"]
    length = float(cumulative[-1])
    if length <= 0:
        return table["coords"][0]
    value = arc % length if table["closed"] else float(np.clip(arc, 0.0, length))
    index = int(np.clip(np.searchsorted(cumulative, value, side="right") - 1, 0, len(cumulative) - 2))
    segment = cumulative[index + 1] - cumulative[index]
    ratio = (value - cumulative[index]) / segment if segment > 0 else 0.0
    return table["coords"][index] + ratio * (table["coords"][index + 1] - table["coords"][index])


def _arc_tangent(table: dict, arc: float) -> np.ndarray:
    """折线上给定弧长处的单位切向。"""
    cumulative = table["cumulative"]
    length = float(cumulative[-1])
    value = arc % length if table["closed"] and length > 0 else float(np.clip(arc, 0.0, length))
    index = int(np.clip(np.searchsorted(cumulative, value, side="right") - 1, 0, len(cumulative) - 2))
    direction = table["coords"][index + 1] - table["coords"][index]
    norm = float(np.linalg.norm(direction))
    return direction / norm if norm > 0 else np.array([1.0, 0.0])


def _slice_arc(table: dict, start: float, span: float, step: float) -> np.ndarray:
    """按弧长切出折线的一段(端点插值), 采样步长不超过 ``step``。"""
    count = max(int(np.ceil(span / max(step, 1e-12))) + 1, 2)
    return np.array([_arc_point(table, start + span * index / (count - 1)) for index in range(count)])


# --------------------------------------------------------------------------- 过/欠
def _two_colour(
    path_count: int,
    crossings: Sequence[dict],
    positions: dict[tuple[int, int], int],
) -> tuple[list[int] | None, str]:
    """给每条路径一个起始相位, 使每个交叉的两次通过"一压一被压"。

    ``flags[i] ^ (pos % 2)`` 是路径 ``i`` 第 ``pos`` 次通过时的取值(True = 压上)。
    自交交叉要靠交替自动满足(两次通过的位置差必须为奇数, 实测恒成立); 路径之间构成
    2-着色约束, 出现**奇环**时无解。
    """
    flags: list[int | None] = [None] * path_count
    constraints: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, crossing in enumerate(crossings):
        i, j = crossing["i"], crossing["j"]
        first, second = positions[(index, 0)], positions[(index, 1)]
        if i == j:
            if (first % 2) == (second % 2):
                return None, f"自交交叉 {index} 的两次通过位置差为偶数({first} vs {second}), 交替无解"
            continue
        parity = (first % 2) ^ (second % 2) ^ 1
        constraints[i].append((j, parity))
        constraints[j].append((i, parity))
    for start in range(path_count):
        if flags[start] is not None:
            continue
        flags[start] = 1
        queue = [start]
        while queue:
            node = queue.pop()
            for other, parity in constraints[node]:
                expected = flags[node] ^ parity
                if flags[other] is None:
                    flags[other] = expected
                    queue.append(other)
                elif flags[other] != expected:
                    return None, f"约束冲突(奇环): 路径 {node} 与 {other}"
    return [int(flag) for flag in flags], ""


# --------------------------------------------------------------------------- 主类
class StrokeWeave:
    """把一组中心线折线切成"按交叉身份断开"的片段, 并给出绘制顺序。

    参数:
        paths: 中心线折线(每条 ``(N, 2)``, 闭合路径首尾点相同)。
        offset: 丝带半宽。断口宽度由它与交叉角决定。
        shallow_sin: ``sinθ`` 的下限(见 :data:`_SHALLOW_SIN`)。
        overshoot: 片段首尾外延比例(相对 ``offset``)。
        max_step_factor: 片段采样步长上限(相对 ``offset``)。

    属性:
        crossings: 中心线交叉列表(见 :func:`centerline_crossings`)。
        flags: 每条路径的起始相位; ``None`` 表示交替无解。
        segments: 片段列表, 每项 ``{"path", "start", "span", "points"}``。
        order: 绘制顺序(片段下标)。约束成环时为 ``None``, 此时按原顺序画即可。
        issues: 非致命问题(交替无解、片段顺序成环、断口吃掉上方交叉区等)。
    """

    def __init__(
        self,
        paths: Sequence[np.ndarray],
        offset: float,
        *,
        shallow_sin: float = _SHALLOW_SIN,
        overshoot: float = _OVERSHOOT,
        max_step_factor: float = 0.5,
    ):
        if not np.isfinite(offset) or offset <= 0:
            raise ValueError(f"offset must be a positive finite number, got {offset!r}")
        if not 0.0 < shallow_sin <= 1.0:
            raise ValueError(f"shallow_sin must be within (0, 1], got {shallow_sin!r}")
        if overshoot < 0:
            raise ValueError(f"overshoot must not be negative, got {overshoot!r}")

        self.paths = [np.asarray(path, dtype=float)[:, :2] for path in paths]
        self.offset = float(offset)
        self.shallow_sin = float(shallow_sin)
        self.overshoot = float(overshoot)
        self.max_step_factor = float(max_step_factor)
        self.issues: list[str] = []

        self._tables = [_segment_tables(path) for path in self.paths]
        self.crossings = centerline_crossings(self.paths)

        self._passes: dict[int, list[dict]] = {index: [] for index in range(len(self.paths))}
        for index, crossing in enumerate(self.crossings):
            # 自交时 i == j: 同一个交叉在同一条路径上留下两次通过(两个弧长)
            self._passes[crossing["i"]].append({"arc": crossing["s_i"], "crossing": index, "side": 0})
            self._passes[crossing["j"]].append({"arc": crossing["s_j"], "crossing": index, "side": 1})
        for records in self._passes.values():
            records.sort(key=lambda record: record["arc"])
        self._positions = {
            (record["crossing"], record["side"]): pos
            for records in self._passes.values()
            for pos, record in enumerate(records)
        }

        self.flags, message = _two_colour(len(self.paths), self.crossings, self._positions)
        if self.flags is None:
            self.issues.append(message)
        self.cuts = self._cut_intervals() if self.flags is not None else {}
        self.segments = self._build_segments() if self.flags is not None else []
        self._check_structure()
        self.order = self._order_segments() if self.segments else None

    # ---------------------------------------------------------------- 公开接口
    @property
    def num_segments(self) -> int:
        """片段数量。"""
        return len(self.segments)

    def is_upper(self, path_index: int, pos: int) -> bool:
        """路径 ``path_index`` 的第 ``pos`` 次通过是否压在上方。"""
        if self.flags is None:
            raise ValueError("交替无解时没有过/欠可言")
        return bool(self.flags[path_index] ^ (pos % 2))

    def crossing_ends(self, crossing_index: int) -> tuple[tuple[int, float], tuple[int, float]]:
        """交叉 ``crossing_index`` 的两端 ``((路径, 弧长), (路径, 弧长))``(自交时路径相同)。"""
        crossing = self.crossings[crossing_index]
        return ((crossing["i"], crossing["s_i"]), (crossing["j"], crossing["s_j"]))

    def pass_position(self, crossing_index: int, side: int) -> int:
        """交叉 ``crossing_index`` 的 ``side`` 端, 在该路径**通过序列**里的位置(从 0 起)。"""
        return self._positions[(crossing_index, side)]

    def upper_path(self, crossing_index: int) -> tuple[int, int] | None:
        """交叉 ``crossing_index`` 处 ``(压上的路径, 被压的路径)``; 交替无解时返回 ``None``。"""
        if self.flags is None:
            return None
        crossing = self.crossings[crossing_index]
        i, j = crossing["i"], crossing["j"]
        first = self._positions[(crossing_index, 0)]
        return (i, j) if self.is_upper(i, first) else (j, i)

    def covers(self, path_index: int, arc: float) -> bool:
        """弧长 ``arc`` 是否落在 ``path_index`` 的某个片段内(落在断口里则为 ``False``)。"""
        for segment in self.segments:
            if segment["path"] != path_index:
                continue
            start, span = segment["start"], segment["span"]
            if self._tables[path_index]["closed"]:
                length = float(self._tables[path_index]["cumulative"][-1])
                if (arc - start) % length <= span:
                    return True
            elif start <= arc <= start + span:
                return True
        return False

    # ---------------------------------------------------------------- 内部
    def _cut_intervals(self) -> dict[int, list[tuple[float, float]]]:
        """被压方在交叉处要断开的弧长区间(两侧各 ``offset / |sinθ|``)。"""
        cuts: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for index, crossing in enumerate(self.crossings):
            i, j = crossing["i"], crossing["j"]
            first = self._positions[(index, 0)]
            second = self._positions[(index, 1)]
            tangent_i = _arc_tangent(self._tables[i], crossing["s_i"])
            tangent_j = _arc_tangent(self._tables[j], crossing["s_j"])
            sin_theta = abs(float(tangent_i[0] * tangent_j[1] - tangent_i[1] * tangent_j[0]))
            half = self.offset / max(sin_theta, self.shallow_sin, 1e-9)
            if not self.is_upper(i, first):
                cuts[i].append((crossing["s_i"] - half, crossing["s_i"] + half))
            if not self.is_upper(j, second):
                cuts[j].append((crossing["s_j"] - half, crossing["s_j"] + half))
        return dict(cuts)

    def _merge(self, path_index: int, intervals: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        table = self._tables[path_index]
        length = float(table["cumulative"][-1])
        pieces: list[tuple[float, float]] = []
        for start, end in intervals:
            if table["closed"]:
                start, end = start % length, end % length
                if start <= end:
                    pieces.append((start, end))
                else:
                    pieces.append((start, length))
                    pieces.append((0.0, end))
            else:
                pieces.append((max(start, 0.0), min(end, length)))
        pieces.sort()
        merged: list[tuple[float, float]] = []
        for start, end in pieces:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def _gaps(self, path_index: int, merged: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        """断口区间的补集, 返回 ``(起点弧长, 跨度)``。"""
        table = self._tables[path_index]
        length = float(table["cumulative"][-1])
        gaps: list[tuple[float, float]] = []
        if table["closed"]:
            if not merged:
                return [(0.0, length)]
            for index in range(len(merged)):
                end = merged[index][1]
                start = merged[(index + 1) % len(merged)][0]
                span = (start - end) % length
                if span > length * 1e-12:
                    gaps.append((end % length, span))
        else:
            cursor = 0.0
            for start, end in merged:
                if start - cursor > length * 1e-12:
                    gaps.append((cursor, start - cursor))
                cursor = end
            if length - cursor > length * 1e-12:
                gaps.append((cursor, length - cursor))
        return gaps

    def _build_segments(self) -> list[dict]:
        margin = self.overshoot * self.offset
        segments: list[dict] = []
        for index, table in enumerate(self._tables):
            length = float(table["cumulative"][-1])
            if length <= 0:
                continue
            merged = self._merge(index, self.cuts.get(index, []))
            for start, span in self._gaps(index, merged):
                if table["closed"]:
                    start = (start - margin) % length
                    span = min(span + 2.0 * margin, length)
                else:
                    start = max(start - margin, 0.0)
                    span = min(span + 2.0 * margin, length - start)
                if span <= 0:
                    continue
                step = max(self.max_step_factor * self.offset, span / 400.0)
                segments.append(
                    {
                        "path": index,
                        "start": start,
                        "span": span,
                        "points": _slice_arc(table, start, span, step),
                    },
                )
        return segments

    def _locate(self, path_index: int, arc: float) -> int | None:
        table = self._tables[path_index]
        length = float(table["cumulative"][-1])
        for index, segment in enumerate(self.segments):
            if segment["path"] != path_index:
                continue
            start, span = segment["start"], segment["span"]
            if table["closed"]:
                if (arc - start) % length <= span:
                    return index
            elif start <= arc <= start + span:
                return index
        return None

    def _check_structure(self) -> None:
        """结构护栏: 断口不能吃掉本方作为压上方的那次通过。"""
        if self.flags is None:
            return
        for index, crossing in enumerate(self.crossings):
            i, j = crossing["i"], crossing["j"]
            for path_index, arc, pos in (
                (i, crossing["s_i"], self._positions[(index, 0)]),
                (j, crossing["s_j"], self._positions[(index, 1)]),
            ):
                if not self.is_upper(path_index, pos):
                    continue
                if self._locate(path_index, arc) is None:
                    self.issues.append(
                        f"交叉 {index}: 路径 {path_index} 在此处应压上, 但它的这一弧长落在断口里"
                        "(相邻交叉的断口互相吃掉)",
                    )

    def _order_segments(self) -> list[int] | None:
        """拓扑排序: 交叉处"压上方"的片段排在被压方相邻片段之后(只用来看假接缝)。"""
        later_than: dict[int, set[int]] = defaultdict(set)
        for index, crossing in enumerate(self.crossings):
            upper_lower = self.upper_path(index)
            if upper_lower is None:
                return None
            upper_path, lower_path = upper_lower
            upper_arc = crossing["s_i"] if upper_path == crossing["i"] else crossing["s_j"]
            lower_arc = crossing["s_j"] if upper_path == crossing["i"] else crossing["s_i"]
            tangent_upper = _arc_tangent(self._tables[upper_path], upper_arc)
            tangent_lower = _arc_tangent(self._tables[lower_path], lower_arc)
            sin_theta = abs(float(tangent_upper[0] * tangent_lower[1] - tangent_upper[1] * tangent_lower[0]))
            half = self.offset / max(sin_theta, self.shallow_sin, 1e-9)
            upper_segment = self._locate(upper_path, upper_arc)
            if upper_segment is None:
                continue
            for sign in (-1.0, 1.0):
                lower_segment = self._locate(lower_path, lower_arc + sign * (half * 1.05))
                if lower_segment is not None and lower_segment != upper_segment:
                    later_than[upper_segment].add(lower_segment)
        indegree = {index: len(later_than.get(index, ())) for index in range(len(self.segments))}
        order: list[int] = []
        available = [index for index in range(len(self.segments)) if indegree[index] == 0]
        while available:
            index = available.pop(0)
            order.append(index)
            for other, dependencies in later_than.items():
                if index in dependencies and indegree[other] > 0:
                    indegree[other] -= 1
                    if indegree[other] == 0:
                        available.append(other)
        if len(order) != len(self.segments):
            self.issues.append("绘制顺序的约束有环(不可满足), 按片段原顺序绘制")
            return None
        return order
