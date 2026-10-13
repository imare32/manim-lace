"""纯几何层: 路径清洗、偏移线生成与编织求解。

本模块与 Manim 渲染层解耦(只依赖 ``numpy`` / ``scipy`` / ``networkx``), 因此可以
脱离渲染环境进行单元测试。整体流程:

1. :func:`clear_paths` 与 :func:`merge_paths` 把任意输入路径清洗、合并为规范的
   开放折线或闭合环;
2. :func:`generate_offset_lines` 使用 Miter Join 为每条路径生成左右两条偏移线,
   即丝带的上下边缘;
3. :class:`Interlacing` 计算偏移线之间的交点, 并由交点拓扑推导出 "孔洞 (holes)"
   与 "丝带片段 (ribbons)"。
"""

from __future__ import annotations

import logging
import warnings
from collections import defaultdict
from collections.abc import Sequence

import networkx
import numpy as np
from scipy.spatial import cKDTree

__all__ = [
    "DEFAULT_ATOL",
    "MAX_CAP_DISTANCE",
    "MITER_LIMIT",
    "VALIDATE_MODES",
    "Interlacing",
    "annulus_polygon",
    "clear_paths",
    "generate_offset_lines",
    "is_cycle",
    "is_open_walk",
    "longest_chain",
    "merge_paths",
    "right_handed",
    "validate_paths",
    "vectorized_intersection",
]

logger = logging.getLogger(__name__)

#: 判定两点重合 / 三点共线 / 向量平行的默认容差。
DEFAULT_ATOL = 1e-6
#: :class:`Interlacing` 的 ``validate`` 参数可选值。
VALIDATE_MODES = ("ignore", "warn", "raise")
#: Miter Join 的最大延伸倍数, 防止锐角处的偏移线无限伸长。
MITER_LIMIT = 5.0
#: 缝合开放路径端点时允许的最大距离。
MAX_CAP_DISTANCE = 10.0

#: 线段标识 ``(路径下标, 类型, 线段下标)``。
#:
#: * 路径下标: 对应 :attr:`Interlacing.paths` 中的位置;
#: * 类型: ``0`` = 中线, ``1`` = 左偏移线, ``2`` = 右偏移线;
#: * 线段下标: 对应路径上相邻两点的序号。
SegmentId = tuple[int, int, int]
#: 拓扑节点标识, 由 ``frozenset`` 包裹的 ``(线段标识, 端点标志)`` 组成。
NodeId = frozenset


def right_handed(coords: np.ndarray) -> bool:
    """判断多边形顶点绕向是否为逆时针(右手定则)。

    使用 Shoelace 公式计算有符号面积, 面积为正表示逆时针。顶点数不足 3 或
    退化多边形一律视为 ``True``, 避免调用方额外判空。

    参数:
        coords: ``(N, 2)`` 或 ``(N, 3)`` 的顶点坐标数组, 允许首尾点重复。

    返回:
        是否为逆时针绕向。
    """
    if len(coords) < 3:
        return True
    if np.allclose(coords[0], coords[-1]):
        coords = coords[:-1]
    if len(coords) < 3:
        return True
    x = coords[:, 0]
    y = coords[:, 1]
    area = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    return bool(area > 0)


def _signed_area(coords: np.ndarray) -> float:
    """Shoelace 有符号面积, 自动忽略重复的闭合点; 顶点不足时返回 0。"""
    pts = coords[:-1] if len(coords) > 1 and np.allclose(coords[0], coords[-1]) else np.asarray(coords, dtype=float)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def annulus_polygon(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """把两条闭合环合成一个"环形"多边形。

    用于无自交点的闭合路径: 其丝带是一条环形带(外环逆时针 + 内环顺时针, 由一条
    狭缝相连), 而不是左右两条偏移线各自构成的实心圆盘。内环反向绕行使填充规则
    (奇偶或非零)都只在环形带上着色, 从而露出中间的孔洞。

    参数:
        first: 其中一条闭合环, ``(N, 2)``。
        second: 另一条闭合环, ``(M, 2)``。内部会按面积自动区分内外。

    返回:
        ``(N + M + 1, 2)`` 的闭合多边形, ``[0]`` 与 ``[-1]`` 相同。
    """
    a = np.asarray(first, dtype=float)[:, :2]
    b = np.asarray(second, dtype=float)[:, :2]
    if len(a) < 2 or len(b) < 2:
        raise ValueError("annulus_polygon requires two closed rings with at least 2 points each")

    outer, inner = (a, b) if abs(_signed_area(a)) >= abs(_signed_area(b)) else (b, a)
    if np.allclose(outer[0], outer[-1]):
        outer = outer[:-1]
    if np.allclose(inner[0], inner[-1]):
        inner = inner[:-1]
    if _signed_area(outer) < 0:
        outer = outer[::-1]
    if _signed_area(inner) < 0:
        inner = inner[::-1]

    # 旋转内环, 让狭缝落在内外环距离最近的一对顶点上
    shift = int(np.argmin(np.linalg.norm(inner - outer[0], axis=1)))
    inner = np.roll(inner, -shift, axis=0)

    return np.vstack([outer, outer[:1], inner[:1], inner[:0:-1], inner[:1], outer[:1]])


def _is_non_collinear(v_in: np.ndarray, v_out: np.ndarray, atol: float) -> np.ndarray:
    """判断相邻两条边向量是否**不共线**(叉积模长不小于容差)。"""
    cross = v_in[:, 0] * v_out[:, 1] - v_in[:, 1] * v_out[:, 0]
    return np.abs(cross) >= atol


def clear_paths(paths: Sequence[np.ndarray], atol: float = DEFAULT_ATOL) -> list[np.ndarray]:
    """清洗路径: 移除重复点与共线点, 丢弃退化路径。

    开放路径按连续三点判断共线; 闭合路径(首尾点重合)额外检查**绕回**处, 即闭合
    点处的 "首尾边 + 首边" 三元组。忽略绕回会在闭合点留下冗余顶点, 使其前后两段
    偏移线共线, 进而在求交时被误判为平行而丢失唯一交点(见 ``Lace(Circle)``)。

    参数:
        paths: 路径序列, 每条路径形如 ``(N, 2)`` 或 ``(N, 3)`` 的数组。
        atol: 判定两点重合 / 三点共线的容差。

    返回:
        清洗后的二维坐标数组列表。长度不足 2 的路径会被丢弃, 因此返回值可能
        比输入短, 甚至为空列表。
    """
    cleared = []
    for path in paths:
        coords = np.asarray(path, dtype=float)[:, :2]
        if len(coords) < 2:
            continue

        dup_mask = np.ones(len(coords), dtype=bool)
        dup_mask[1:] = np.linalg.norm(coords[1:] - coords[:-1], axis=1) > atol
        coords = coords[dup_mask]

        if len(coords) > 2 and np.allclose(coords[0], coords[-1], atol=atol):
            coords = _clear_closed_collinear(coords, atol)
        elif len(coords) > 2:
            colinr_mask = np.ones(len(coords), dtype=bool)
            v1 = coords[1:-1] - coords[:-2]
            v2 = coords[2:] - coords[1:-1]
            colinr_mask[1:-1] = _is_non_collinear(v1, v2, atol)
            coords = coords[colinr_mask]

        if len(coords) > 1:
            cleared.append(coords)
    return cleared


def _clear_closed_collinear(coords: np.ndarray, atol: float) -> np.ndarray:
    """移除闭合路径上的冗余共线顶点(含闭合点处的绕回情形), 并重新闭合。

    参数:
        coords: ``(N, 2)`` 的闭合坐标, ``coords[0] == coords[-1]``。
        atol: 共线判定容差。

    返回:
        重新闭合后的坐标数组; 若剩余顶点不足 3 个(全部共线)则返回空数组。
    """
    body = coords[:-1]
    if len(body) >= 3:
        v_in = body - np.roll(body, 1, axis=0)
        v_out = np.roll(body, -1, axis=0) - body
        body = body[_is_non_collinear(v_in, v_out, atol)]

    if len(body) < 3:
        return np.empty((0, 2), dtype=float)
    return np.vstack([body, body[:1]])


def _point_key(point) -> tuple[float, float]:
    """把坐标四舍五入成可哈希的键(容差 1e-6, 与 :data:`DEFAULT_ATOL` 同量级)。"""
    return (round(float(point[0]), 6), round(float(point[1]), 6))


def _segment_label(segment: tuple) -> str:
    """把 ``(路径下标, 线段下标, 起点, 终点)`` 打印成便于定位的标签。"""
    return f"(路径{segment[0]}, 段{segment[1]})"


def validate_paths(paths: Sequence[np.ndarray], atol: float = DEFAULT_ATOL) -> list[str]:
    """检查输入路径是否落在算法能够处理的"一般位置"上。

    算法的前提是"丝带之间只**横穿**": 一旦输入里出现**沿同一方向共线重叠/重合的
    线段**, 偏移后两条丝带会占据同一块区域, 上下穿插关系无从定义; **三条以上线段
    共点**同理。这类输入会让求解结果错乱(实测可把中心线覆盖检查的失败点从 0 抬到
    20%~75%), 而且在当前实现下是**静默**的。此函数把它们显式查出来, 交给调用方
    决定告警还是报错(:class:`Interlacing` 的 ``validate`` 参数)。

    参数:
        paths: 路径序列, 每条路径形如 ``(N, 2)`` 或 ``(N, 3)`` 的数组。
        atol: 判定重合 / 共线 / 相交的容差。

    返回:
        问题描述列表(每项以稳定的中文前缀开头), 空列表表示通过。检测项:

        * ``"共线重叠: ..."``: 两条线段方向近似平行、共线, 且投影重叠长度超过 ``atol``;
        * ``"多线共点: ..."``: 三条以上线段经过同一点。

    注意: 路径的**自交**(非相邻线段横穿)不算问题 —— 本库的玫瑰线大量存在自交,
    算法能正常处理。
    """
    cleaned = clear_paths(paths, atol)
    segments: list[tuple[int, int, np.ndarray, np.ndarray]] = []
    for path_index, path in enumerate(cleaned):
        for seg_index in range(len(path) - 1):
            segments.append(
                (path_index, seg_index, np.asarray(path[seg_index], float), np.asarray(path[seg_index + 1], float)),
            )
    if len(segments) < 2:
        return []

    starts = np.array([segment[2] for segment in segments])
    ends = np.array([segment[3] for segment in segments])
    directions = ends - starts
    lengths = np.linalg.norm(directions, axis=1)
    bbox_lo = np.minimum(starts, ends)
    bbox_hi = np.maximum(starts, ends)

    # 先把所有线段端点登记到"点 -> 线段集合", 再加上真正的横向交点
    point_segments: dict[tuple[float, float], set[int]] = defaultdict(set)
    for index, (_, _, start, end) in enumerate(segments):
        point_segments[_point_key(start)].add(index)
        point_segments[_point_key(end)].add(index)

    issues: list[str] = []
    eps = 1e-9
    for i in range(len(segments)):
        if lengths[i] < atol:
            continue
        candidates = np.arange(i + 1, len(segments))
        # 包围盒预筛, 避免 O(N²) 的全量精确判定
        mask = (bbox_hi[i] >= bbox_lo[candidates]).all(axis=1) & (bbox_lo[i] <= bbox_hi[candidates]).all(axis=1)
        mask &= lengths[candidates] >= atol
        candidates = candidates[mask]
        if candidates.size == 0:
            continue

        dir_i, len_i, start_i = directions[i], lengths[i], starts[i]
        dirs, lens = directions[candidates], lengths[candidates]
        cross = dir_i[0] * dirs[:, 1] - dir_i[1] * dirs[:, 0]
        parallel = np.abs(cross) / (len_i * lens) < 1e-9

        for j in candidates[parallel]:  # 平行: 判共线重叠
            offset_vec = starts[j] - start_i
            distance = abs(dir_i[0] * offset_vec[1] - dir_i[1] * offset_vec[0]) / len_i
            if distance > atol:
                continue
            t0 = float((starts[j] - start_i) @ dir_i) / (len_i * len_i)
            t1 = float((ends[j] - start_i) @ dir_i) / (len_i * len_i)
            overlap = (min(max(t0, t1), 1.0) - max(min(t0, t1), 0.0)) * len_i
            if overlap <= atol:
                continue
            same_direction = float(dir_i @ directions[j]) > 0.0
            issues.append(
                f"共线重叠: 线段 {_segment_label(segments[i])} 与 {_segment_label(segments[j])} 沿"
                f"{'相同' if same_direction else '相反'}方向重合 {overlap:.4g}(占本段 {overlap / len_i:.0%})",
            )

        others = candidates[~parallel]  # 非平行: 求交并统计共点
        if others.size == 0:
            continue
        denom = cross[~parallel]
        deltas = start_i - starts[others]  # 与 vectorized_intersection 保持一致: d13 = P1 - P3
        ua = (directions[others][:, 0] * deltas[:, 1] - directions[others][:, 1] * deltas[:, 0]) / denom
        ub = (dir_i[0] * deltas[:, 1] - dir_i[1] * deltas[:, 0]) / denom
        hit = (ua >= -eps) & (ua <= 1 + eps) & (ub >= -eps) & (ub <= 1 + eps)
        for u, j in zip(ua[hit], others[hit]):
            key = _point_key(start_i + u * dir_i)
            point_segments[key].add(i)
            point_segments[key].add(j)

    for key, seg_set in sorted(point_segments.items()):
        if len(seg_set) >= 3:
            issues.append(f"多线共点: ({key[0]:.4g}, {key[1]:.4g}) 处有 {len(seg_set)} 条线段相交")
    return issues


def merge_paths(paths: Sequence[np.ndarray], atol: float = DEFAULT_ATOL) -> list[np.ndarray]:
    """把首尾相连的路径合并为更长的开放链或闭合环。

    合并基于 "按容差取整后的坐标等价类" 建图, 因此对浮点误差不敏感。闭合环会被
    统一为逆时针方向, 开放链会被整理为从端点出发的有序点列。

    参数:
        paths: 待合并的路径序列。
        atol: 坐标取整容差, 必须为正数。

    返回:
        合并后的路径列表; 输入为空时返回空列表。
    """
    if not paths:
        return []
    if atol <= 0:
        raise ValueError(f"atol must be positive, got {atol!r}")

    decimals = max(0, int(np.log10(1 / atol)))

    # 收集所有坐标, 建立 "坐标 -> 节点编号" 的映射
    coords_all = np.concatenate(paths, axis=0)
    coords_all = np.around(coords_all, decimals)
    coord_tuples = [tuple(coord) for coord in coords_all]
    d_coord_node = {coord: i for i, coord in enumerate(coord_tuples)}

    # 构建边列表
    edges = []
    for path in paths:
        path_indices = [d_coord_node[tuple(np.around(coord, decimals))] for coord in path]
        edges.extend(zip(path_indices, path_indices[1:]))

    networkx_graph = networkx.Graph()
    networkx_graph.add_edges_from(edges)

    merged: list[np.ndarray] = []

    # 记录每条 path 的起始节点, 用于把环旋转到与原始输入对齐的位置
    path_starts = []
    for path in paths:
        if len(path) > 0:
            start_tuple = tuple(np.around(path[0], decimals))
            if start_tuple in d_coord_node:
                path_starts.append(d_coord_node[start_tuple])

    # 处理闭合环(cycle basis)
    for cycle in networkx.cycle_basis(networkx_graph):
        if len(cycle) < 3:
            continue

        # 尝试将 cycle 旋转到某个 path 的起始点, 保证结果可重现
        target_start = next((ps for ps in path_starts if ps in cycle), None)
        if target_start is not None:
            start_idx = cycle.index(target_start)
            cycle = cycle[start_idx:] + cycle[:start_idx]

        coord_list = [coords_all[idx] for idx in [*cycle, cycle[0]]]
        coords = np.array(coord_list)
        if not right_handed(coords):
            coords = coords[::-1]
        merged.append(coords)

    # 处理开放链
    for island in networkx.connected_components(networkx_graph):
        island_list = list(island)
        if is_cycle(networkx_graph, island_list):
            continue
        if is_open_walk(networkx_graph, island_list):
            edges_island = [(u, v) for u, v in networkx_graph.edges if u in island_list and v in island_list]
            nodes = longest_chain(edges_island)
            if nodes:
                coord_list = [coords_all[idx] for idx in nodes]
                if not right_handed(np.array(coord_list)):
                    coord_list.reverse()
                merged.append(np.array(coord_list))

    return merged


def longest_chain(edges: Sequence[tuple[int, int]]) -> list[int]:
    """在无向图中找出最长的一条简单链。

    参数:
        edges: 无向边列表, 每条边为 ``(u, v)``。

    返回:
        按连接顺序排列的节点列表; 输入为空时返回空列表。若图是闭合环, 会返回
        不含重复起点的节点序列。
    """
    if not edges:
        return []

    # 构建邻接表
    adj: dict[int, list[int]] = {}
    for u, v in edges:
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, []).append(u)

    # 找到两个端点(度为 1 的节点)
    start = None
    end = None
    for node, neighbors in adj.items():
        if len(neighbors) == 1:
            if start is None:
                start = node
            else:
                end = node
                break

    # 没有端点说明是环, 任选一个起点
    if start is None:
        start = edges[0][0]

    chain = [start]
    visited_edges: set[tuple[int, int]] = set()

    current = start
    while True:
        next_node = None
        for n in adj.get(current, []):
            edge = (min(current, n), max(current, n))
            if edge not in visited_edges:
                next_node = n
                visited_edges.add(edge)
                break
        if next_node is None:
            break
        chain.append(next_node)
        current = next_node
        if end is not None and current == end:
            break

    if len(chain) > 1 and chain[0] == chain[-1]:
        chain = chain[:-1]
    return chain


def is_cycle(graph: networkx.Graph, island: Sequence[int]) -> bool:
    """判断某个连通分量是否为一个简单环(所有节点度数均为 2)。"""
    degrees = [graph.degree(node) for node in island]
    return set(degrees) == {2}


def is_open_walk(graph: networkx.Graph, island: Sequence[int]) -> bool:
    """判断某个连通分量是否为一条开放链(恰好两个端点, 其余节点度数为 2)。"""
    if len(island) == 2:
        return True
    degrees = [graph.degree(node) for node in island]
    return set(degrees) == {1, 2} and degrees.count(1) == 2


def generate_offset_lines(coords: np.ndarray, offset: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
    """为路径生成左右两条偏移线(Miter Join)。

    在拐点处取相邻两条线段法向量的角平分线方向, 并按 ``1 / (1 + cosθ)`` 放大,
    使偏移线在内侧/外侧都保持等距。为防止锐角处偏移线过长, 延伸倍数被限制在
    :data:`MITER_LIMIT` 以内。

    参数:
        coords: ``(N, 2)`` 或 ``(N, 3)`` 的路径坐标, 首尾点相同视为闭合路径。
        offset: 偏移距离(丝带半宽)。

    返回:
        ``(path_left, path_right)`` 两条偏移线, 形状与输入一致。
    """
    coords = np.asarray(coords, dtype=float)
    closed = np.allclose(coords[0], coords[-1])
    if closed:
        eff_coords = coords[:-1]
        tangents = np.roll(eff_coords, -1, axis=0) - eff_coords
    else:
        tangents = np.diff(coords, axis=0)

    norms = np.linalg.norm(tangents, axis=1)
    norms[norms < DEFAULT_ATOL] = 1.0
    tangents /= norms[:, None]

    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)

    vn = np.zeros_like(coords)

    if closed:
        n_in = np.roll(normals, 1, axis=0)
        n_out = normals
        denom = 1 + np.sum(n_in * n_out, axis=1)
        denom[denom < DEFAULT_ATOL] = DEFAULT_ATOL
        vn_body = (n_in + n_out) / denom[:, None]
        vn[:-1] = vn_body
        vn[-1] = vn_body[0]
    else:
        n_in = normals[:-1]
        n_out = normals[1:]

        denom = 1 + np.sum(n_in * n_out, axis=1)
        denom[denom < DEFAULT_ATOL] = DEFAULT_ATOL
        vn[1:-1] = (n_in + n_out) / denom[:, None]

        vn[0] = normals[0]
        vn[-1] = normals[-1]

    lens = np.linalg.norm(vn, axis=1)
    mask = lens > MITER_LIMIT
    if np.any(mask):
        vn[mask] *= MITER_LIMIT / lens[mask][:, None]

    return coords + vn * offset, coords - vn * offset


def vectorized_intersection(
    P1: np.ndarray,
    P2: np.ndarray,
    P3: np.ndarray,
    P4: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """向量化计算线段 ``P1P2`` 与一批线段 ``P3P4`` 的交点。

    参数:
        P1, P2: 单条线段的两个端点, 形状为 ``(2,)``。
        P3, P4: ``(N, 2)`` 的候选线段端点数组, 与 ``P1P2`` 逐行配对。

    返回:
        ``(points, mask)``, 其中 ``points`` 为 ``(N, 2)`` 的交点坐标(无效位置为
        外推点, 需用 ``mask`` 过滤), ``mask`` 为 ``(N,)`` 的布尔有效标记。
        平行或不相交的线段其 ``mask`` 为 ``False``。
    """
    d1, d2, d13 = P2 - P1, P4 - P3, P1 - P3
    denom = d1[0] * d2[:, 1] - d1[1] * d2[:, 0]
    is_p = np.abs(denom) < 1e-9
    denom_s = np.where(is_p, 1.0, denom)
    ua = (d2[:, 0] * d13[:, 1] - d2[:, 1] * d13[:, 0]) / denom_s
    ub = (d1[0] * d13[:, 1] - d1[1] * d13[:, 0]) / denom_s
    mask = (~is_p) & (ua >= -1e-9) & (ua <= 1 + 1e-9) & (ub >= -1e-9) & (ub <= 1 + 1e-9)
    return P1 + ua[:, None] * d1, mask


class Interlacing:
    """编织(交错)几何求解器。

    输入一组路径与丝带半宽, 输出"孔洞"与"丝带片段"两类多边形。算法分四步:

    1. 清洗并合并路径(:func:`clear_paths` / :func:`merge_paths`), 统一闭合环绕向;
    2. 为每条路径生成左右偏移线, 并把它们离散为线段;
    3. 用扫描线算法求出所有偏移线之间的交点, 对每条线段上的交点按距离排序;
    4. 以交点为节点、线段为边构建拓扑图, 搜索环以提取孔洞与丝带片段。丝带片段
       通过 :attr:`paths_flag` 交替"绘制 / 跳过", 从而在二维平面上模拟上下穿插。

    属性:
        paths: 清洗合并后的路径列表。
        paths_l / paths_r: 每条路径的左 / 右偏移线。
        paths_closed: 每条路径是否闭合。
        paths_flag: 每条开放路径的初始绘制标志(相邻路径交替)。
        d_segments: ``{线段标识: (起点, 终点)}``。
        d_intersections: ``{交点键: 交点坐标}``。
        d_seg_intersects: ``{线段标识: [相交线段标识...]}``, 按距离起点远近排序。
        holes: 孔洞多边形列表, 每个元素为闭合坐标数组。
        ribbons: 丝带片段多边形列表, 每个元素为闭合坐标数组。
        overlaps: (实验性)交错重叠区域多边形列表, 由 :meth:`_set_overlaps` 填充。
        path_issues: :func:`validate_paths` 检出的退化输入问题列表(见 ``validate`` 参数)。

    空输入(或清洗后为空)是合法的: 此时各集合为空, 实例仍可正常访问属性。

    输入退化: 算法假定丝带之间只**横穿**, 且偏移不会改变相交关系。若输入含**共线
    重叠/重合**的线段或**三线以上共点**, 丝带会占据同一块区域, 上下穿插关系无从
    定义, 结果会错乱(且在此之前是静默的)。这类输入由 ``validate`` 参数统一处理,
    检出结果见 :attr:`path_issues`。
    """

    def __init__(
        self,
        paths: Sequence[np.ndarray],
        offset: float = 0.1,
        compute_overlaps: bool = False,
        validate: str = "warn",
    ):
        """初始化并立即求解。

        参数:
            paths: 路径序列, 每个元素为 ``(N, 2)`` 或 ``(N, 3)`` 的坐标数组。
            offset: 丝带半宽, 必须为正的有限数。
            compute_overlaps: 是否额外计算交错重叠区域(实验性, 见
                :meth:`_set_overlaps`)。默认关闭以避免不必要的开销。
            validate: 对"退化输入"的处理方式(见 :func:`validate_paths`):

                * ``"warn"``(默认): 检出后退化为 ``UserWarning``, 仍继续求解;
                * ``"raise"``: 直接抛 :class:`ValueError`, 不进行求解;
                * ``"ignore"``: 跳过检查(``path_issues`` 保持为空)。

        异常:
            ValueError: ``offset`` 不是正数或不是有限值; ``validate`` 取值未知;
                或 ``validate="raise"`` 且输入含有共线重叠 / 多线共点。

        属性:
            path_issues: :func:`validate_paths` 检出的问题列表(``validate != "ignore"`` 时填充)。
        """
        if validate not in VALIDATE_MODES:
            raise ValueError(f"unknown validate mode {validate!r}, expected one of {VALIDATE_MODES}")
        if not np.isfinite(offset) or offset <= 0:
            raise ValueError(f"offset must be a positive finite number, got {offset!r}")

        self.validate = validate
        self.path_issues: list[str] = [] if validate == "ignore" else validate_paths(paths)
        if self.path_issues:
            detail = f"{self.path_issues[0]}" + (f" 等 {len(self.path_issues)} 处" if len(self.path_issues) > 1 else "")
            message = (
                "输入路径含有共线重叠或多线共点(退化输入): 丝带在这些位置的上下穿插关系没有定义, "
                f"结果可能错乱。{detail}(详见 Interlacing.path_issues)"
            )
            if validate == "raise":
                raise ValueError(message)
            warnings.warn(message, UserWarning, stacklevel=2)

        self.offset = float(offset)
        self.paths: list[np.ndarray] = merge_paths(clear_paths(paths))

        self.paths_closed: list[bool] = []
        self.paths_flag: list[bool] = []
        self.paths_l: list[np.ndarray] = []
        self.paths_r: list[np.ndarray] = []
        self.d_segments: dict[SegmentId, tuple[np.ndarray, np.ndarray]] = {}
        self.d_intersections: dict[frozenset, np.ndarray] = {}
        self.d_seg_intersects: dict[SegmentId, list] = defaultdict(list)
        self.overlaps: list[np.ndarray] = []
        self.holes: list[np.ndarray] = []
        self.ribbons: list[np.ndarray] = []
        self.rail_issues: list[str] = []
        self._degraded_paths: set[int] = set()

        if not self.paths:
            logger.debug("Interlacing: 输入中没有可用的路径, 跳过求解。")
            return

        self._prepare_paths()
        self._build_segments()
        self._cal_intersections()
        # 先按交叉事件补齐缺失的交点, 再做契约自检与降级判定
        self._align_all_rails()
        self._check_rail_geometry()
        if compute_overlaps:
            # 必须在 _set_holes 之前调用: 后者会向 d_seg_intersects 插入虚拟端点
            self._set_overlaps()
        self._set_holes()
        self._set_ribbons()

    def __repr__(self) -> str:
        return (
            f"Interlacing(paths={len(self.paths)}, offset={self.offset}, "
            f"holes={len(self.holes)}, ribbons={len(self.ribbons)})"
        )

    @property
    def is_empty(self) -> bool:
        """输入是否不含任何有效路径。"""
        return not self.paths

    def _align_all_rails(self) -> None:
        """对所有"左右偏移线交点数不等"的线段按**交叉事件**补齐缺失的交点。

        另一条丝带的偏移线恰好在本轨道拐角前结束时, 只有一条轨道登记到交点, 左右
        交点数相差 1; 按索引配对会把不同的交叉事件配到一起(双带同绘 / 丝带缺失)。
        这里把缺失的交点补回较短的轨道(拓扑上紧跟其配对事件), 恢复逐事件配对。
        """
        for i in range(len(self.paths)):
            for j in range(len(self.paths_l[i]) - 1):
                seg_id_l, seg_id_r = (i, 1, j), (i, 2, j)
                if len(self.d_seg_intersects[seg_id_l]) != len(self.d_seg_intersects[seg_id_r]):
                    self._align_rail_events(
                        self.d_seg_intersects[seg_id_l],
                        self.d_seg_intersects[seg_id_r],
                        seg_id_l,
                        seg_id_r,
                    )

    def _check_rail_geometry(self) -> None:
        """派生几何自检: 算法的配对契约是否仍然成立。

        契约是"同一条线段上, 左右偏移线的交点数相等" —— 这是 :meth:`_set_ribbons`
        按索引配对的前提。契约不成立时, 这些路径无法正确编织, 会被标记为**降级渲染**
        (退化成不编织的整条丝带), 而不是静默产出错乱图形。

        注意**不**把"偏移线自交"判为退化: 实测大量正常玫瑰线(如 CA n=12 L4 有 48 处)
        的偏移线自交, 且左右两侧对称、数量一致, 渲染完全正常; 自交本身并不破坏配对
        契约, 只是丝带在自己的凹处折了一下。
        """
        self.rail_issues = []
        self._degraded_paths = set()
        for i in range(len(self.paths)):
            num_seg = len(self.paths_l[i]) - 1
            bad = sum(
                1
                for j in range(num_seg)
                if len(self.d_seg_intersects[(i, 1, j)]) != len(self.d_seg_intersects[(i, 2, j)])
            )
            if bad:
                self.rail_issues.append(f"路径 {i}: {bad}/{num_seg} 条线段的左右偏移线交点数不等")
                self._degraded_paths.add(i)

        if self.rail_issues:
            warnings.warn(
                "偏移线不满足配对契约(同一线段左右交点数不等), 相关路径已退化为'不编织'的整条丝带; "
                "详见 Interlacing.rail_issues。要提前拒绝退化输入可用 Interlacing(validate='raise')。",
                UserWarning,
                stacklevel=2,
            )

    def _prepare_paths(self) -> None:
        """确定路径开闭性并生成左右偏移线。

        开放路径的 ``paths_flag`` 会交替为 ``True`` / ``False``, 保证多条独立路径
        交错出现"绘制 / 跳过", 避免同层丝带全部压在同一面上。
        """
        # 排序的目的是保证开放路径的 flag 初始值交替为 True 和 False
        self.paths.sort(key=lambda x: (x[0][0], x[0][1]))
        flag = True
        for path in self.paths:
            closed = bool(np.allclose(path[0], path[-1]))
            self.paths_closed.append(closed)
            if closed:
                # 确保闭合路径的首尾点完全相同, 消除浮点误差
                path[-1] = path[0]
                self.paths_flag.append(True)
            else:
                self.paths_flag.append(flag)
                flag = not flag

        for path in self.paths:
            path_l, path_r = generate_offset_lines(path, self.offset)
            self.paths_l.append(path_l)
            self.paths_r.append(path_r)

    def _build_segments(self) -> None:
        """把中线与两条偏移线离散成有向线段, 写入 :attr:`d_segments`。"""
        for i, (path, path_l, path_r) in enumerate(zip(self.paths, self.paths_l, self.paths_r)):
            for j in range(len(path) - 1):
                self.d_segments[(i, 0, j)] = (path[j], path[j + 1])
                self.d_segments[(i, 1, j)] = (path_l[j], path_l[j + 1])
                self.d_segments[(i, 2, j)] = (path_r[j], path_r[j + 1])

    def _cal_intersections(self) -> None:
        """用扫描线 + 向量化求交计算所有偏移线交点。

        结果写入 :attr:`d_intersections` 与 :attr:`d_seg_intersects`, 后者会按交点
        到线段起点的距离排序。若同一个位置有 3 条以上线段相交, 发出 UserWarning。
        """
        seg_coords_list = []
        seg_ids_list = []

        # --- 1. 从 d_segments 提取数据, 跳过中线(type_idx == 0) ---
        for (p_idx, t_idx, s_idx), (p_start, p_end) in self.d_segments.items():
            if t_idx == 0:
                continue
            seg_coords_list.append(np.hstack((p_start, p_end)))
            seg_ids_list.append((p_idx, t_idx, s_idx))

        if not seg_coords_list:
            return

        seg_arr = np.vstack(seg_coords_list)
        seg_ids_arr = np.array(seg_ids_list, dtype=object)
        num_segs = len(seg_arr)

        # --- 2. 构建 Augmented Segments 并按 xmin 排序 ---
        x1, y1, x2, y2 = seg_arr[:, 0], seg_arr[:, 1], seg_arr[:, 2], seg_arr[:, 3]
        xmin, xmax = np.minimum(x1, x2), np.maximum(x1, x2)
        ymin, ymax = np.minimum(y1, y2), np.maximum(y1, y2)

        # 列布局: [x1, y1, x2, y2, xmin, ymin, xmax, ymax]
        aug_segs = np.column_stack((seg_arr, xmin, ymin, xmax, ymax))

        sort_idx = np.argsort(xmin)
        aug_segs = aug_segs[sort_idx]
        sorted_ids = seg_ids_arr[sort_idx]
        s_xmin = aug_segs[:, 4]

        intersection_clusters: dict[tuple[float, float], set] = defaultdict(set)

        # --- 3. 扫描线循环 ---
        for i in range(num_segs - 1):
            curr_seg = aug_segs[i]
            curr_id = tuple(sorted_ids[i])  # (p_idx, t_idx, s_idx)

            # 快速筛选 X 轴范围
            search_limit = np.searchsorted(s_xmin, curr_seg[6], side="right")
            if search_limit <= i + 1:
                continue
            candidates_idx = np.arange(i + 1, search_limit)

            # Y 轴范围过滤
            y_mask = (curr_seg[7] >= aug_segs[candidates_idx, 5]) & (curr_seg[5] <= aug_segs[candidates_idx, 7])
            valid_candidates_indices = candidates_idx[y_mask]
            if len(valid_candidates_indices) == 0:
                continue

            # 向量化求交
            P1, P2 = curr_seg[:2], curr_seg[2:4]
            cand_segs = aug_segs[valid_candidates_indices]
            P3, P4 = cand_segs[:, 0:2], cand_segs[:, 2:4]
            points, valid_mask = vectorized_intersection(P1, P2, P3, P4)
            if not np.any(valid_mask):
                continue

            for point, m_idx in zip(points[valid_mask], valid_candidates_indices[valid_mask]):
                target_id = tuple(sorted_ids[m_idx])
                self.d_intersections[frozenset((curr_id, target_id))] = point
                self.d_seg_intersects[curr_id].append(target_id)
                self.d_seg_intersects[target_id].append(curr_id)

                coord_key = (round(point[0], 6), round(point[1], 6))
                intersection_clusters[coord_key].add(curr_id)
                intersection_clusters[coord_key].add(target_id)

        # --- 4. 收尾: 多线共点告警 + 按距离排序 ---
        for coord, seg_set in intersection_clusters.items():
            if len(seg_set) >= 3:
                warnings.warn(
                    f"Multi-segment intersection at {coord} involves {len(seg_set)} segments.",
                    UserWarning,
                    stacklevel=2,
                )

        for seg_id, tgt_ids in self.d_seg_intersects.items():
            seg_start = self.d_segments[seg_id][0]
            tgt_ids.sort(
                key=lambda tgt_id: np.linalg.norm(self.d_intersections[frozenset((seg_id, tgt_id))] - seg_start),
            )

    def _set_overlaps(self) -> None:
        """(实验性) 提取四条交点围成的交错重叠区域。

        结果写入 :attr:`overlaps`。该信息目前未参与渲染, 保留给需要显式处理
        重叠区域的进阶用法与拓扑分析。
        """
        self.overlaps = []
        nx_graph = networkx.Graph()
        for seg_id, tgt_ids in self.d_seg_intersects.items():
            # 正常情况下交点数应为偶数, 因为线段被双轨偏移线切割; 0 是线段起点
            for k in range(1, len(tgt_ids) - 1, 2):
                nx_graph.add_edge(
                    frozenset((seg_id, tgt_ids[k])),
                    frozenset((seg_id, tgt_ids[k + 1])),
                )

        for cycle in networkx.cycle_basis(nx_graph):
            # 4 个交点组成一个重叠区域
            if len(cycle) != 4:
                continue
            coords = np.array([self.d_intersections[node] for node in [*cycle, cycle[0]]])
            if not right_handed(coords):
                coords = coords[::-1]
            self.overlaps.append(coords)

    def _set_holes(self) -> None:
        """提取丝带围成的孔洞多边形。

        开放路径的端点会先被登记为虚拟交点(供 :meth:`_set_ribbons` 复用), 再用
        KDTree 把"断头"端点缝合成虚拟边以封闭区域。随后搜索图中的环, 并过滤掉
        面积最大的环(即整体外轮廓)与退化环。结果写入 :attr:`holes`。
        """
        # --- 0. 登记开放路径的端点 ---
        for i, (paths_l, paths_r) in enumerate(zip(self.paths_l, self.paths_r)):
            if self.paths_closed[i]:
                continue
            num_seg = len(paths_l) - 1

            seg_id_l, tgt_id_l = (i, 1, 0), 0
            self.d_intersections[frozenset((seg_id_l, tgt_id_l))] = paths_l[0]
            self.d_seg_intersects[seg_id_l].insert(0, tgt_id_l)

            seg_id_l, tgt_id_l = (i, 1, num_seg - 1), -1
            self.d_intersections[frozenset((seg_id_l, tgt_id_l))] = paths_l[-1]
            self.d_seg_intersects[seg_id_l].append(tgt_id_l)

            seg_id_r, tgt_id_r = (i, 2, 0), 0
            self.d_intersections[frozenset((seg_id_r, tgt_id_r))] = paths_r[0]
            self.d_seg_intersects[seg_id_r].insert(0, tgt_id_r)

            seg_id_r, tgt_id_r = (i, 2, num_seg - 1), -1
            self.d_intersections[frozenset((seg_id_r, tgt_id_r))] = paths_r[-1]
            self.d_seg_intersects[seg_id_r].append(tgt_id_r)

        nx_graph = networkx.Graph()

        # === 1. 收集所有 "断头" 节点 (Valid Caps) ===
        cap_nodes: list = []  # networkx 节点 ID (frozenset)
        cap_coords: list[np.ndarray] = []  # KDTree 用的坐标
        cap_info: list[tuple[int, int, int]] = []  # 元数据: (path_idx, side_idx, end_flag)

        for i in range(len(self.paths)):
            if self.paths_closed[i]:
                continue
            num_seg = len(self.paths_l[i]) - 1

            # 端点配置: (线段下标, 端点标志, 侧)
            # 端点标志: 0 是起点, -1 是终点;  侧: 1 是左, 2 是右
            endpoints = [
                (0, 0, 1),
                (0, 0, 2),
                (num_seg - 1, -1, 1),
                (num_seg - 1, -1, 2),
            ]

            for s_idx, e_flag, side in endpoints:
                node_id = frozenset(((i, side, s_idx), e_flag))
                if node_id in self.d_intersections:
                    cap_nodes.append(node_id)
                    cap_coords.append(self.d_intersections[node_id])
                    cap_info.append((i, side, e_flag))

        # === 2. 使用 KDTree 查找邻居并缝合 ===
        if cap_coords:
            tree = cKDTree(cap_coords)
            # k=3: 最近的是自己, 其次是孪生端点与目标邻居
            dists_all, idxs_all = tree.query(cap_coords, k=min(3, len(cap_coords)))
            added_edges: set[frozenset] = set()

            for i, (dists, idxs) in enumerate(zip(dists_all, idxs_all)):
                current_node = cap_nodes[i]
                current_path_idx = cap_info[i][0]
                current_eflag = cap_info[i][2]
                valid_neighbor_found = False

                for d, neighbor_idx in zip(dists, idxs):
                    if i == neighbor_idx:
                        continue  # 跳过自己

                    neighbor_path_idx = cap_info[neighbor_idx][0]
                    neighbor_eflag = cap_info[neighbor_idx][2]

                    # === 排除孪生端点 ===
                    # 同一条路径、同一个端点标志的两个端点其实是丝带的封口, 不连;
                    # 但同一条路径的首尾相接(Start -> End)是允许的, 可形成闭环。
                    if current_path_idx == neighbor_path_idx and current_eflag == neighbor_eflag:
                        valid_neighbor_found = True
                        continue

                    # 距离阈值保护, 避免连接到画布另一头
                    if d > MAX_CAP_DISTANCE:
                        continue

                    target_node = cap_nodes[neighbor_idx]
                    edge_sig = frozenset((current_node, target_node))
                    if edge_sig not in added_edges:
                        nx_graph.add_edge(current_node, target_node)
                        added_edges.add(edge_sig)
                    valid_neighbor_found = True
                    break  # 只需连接最近的一个合法邻居

                if not valid_neighbor_found:
                    warnings.warn(f"Node {current_node} has no valid neighbors.", UserWarning, stacklevel=2)

        # === 3. 连接丝带内部的 edges ===
        for seg_id, tgt_ids in self.d_seg_intersects.items():
            for k in range(0, len(tgt_ids), 2):
                if k + 1 < len(tgt_ids):
                    nx_graph.add_edge(
                        frozenset((seg_id, tgt_ids[k])),
                        frozenset((seg_id, tgt_ids[k + 1])),
                    )

        # === 4. 计算 Loop 面积并提取 Holes ===
        valid_cycle_data: list[tuple[np.ndarray, float]] = []
        for cycle in networkx.cycle_basis(nx_graph):
            if len(cycle) < 3:
                warnings.warn(f"Hole cycle has {len(cycle)} nodes.", UserWarning, stacklevel=2)
                continue

            coords = np.array([self.d_intersections[node] for node in [*cycle, cycle[0]]])

            # Shoelace formula
            x = coords[:, 0]
            y = coords[:, 1]
            area = 0.5 * np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
            valid_cycle_data.append((coords, area))

        # 面积最大的环是整体外轮廓, 需要排除; 其余环的总面积作为阈值
        areas = sorted(area for _, area in valid_cycle_data)
        total_area = sum(areas[:-1])
        logger.debug("Interlacing: 发现 %d 个候选环, 面积阈值 %.6g", len(areas), total_area)

        for coords, area in valid_cycle_data:
            if area > total_area:
                continue
            if not right_handed(coords):
                coords = coords[::-1]
            self.holes.append(coords)

    def _is_rail_corner(self, seg_id: SegmentId, tgt) -> bool:
        """判断 ``seg_id`` 上的交点 ``tgt`` 是否只是相邻同轨线段的共享角点(或封口)。"""
        if not isinstance(tgt, tuple):
            return True
        i, track, j = seg_id
        num_seg = len(self.paths_l[i]) - 1
        if self.paths_closed[i]:
            return tgt in {(i, track, (j - 1) % num_seg), (i, track, (j + 1) % num_seg)}
        return tgt in {(i, track, j - 1), (i, track, j + 1)}

    def _genuine_targets(self, seg_id: SegmentId) -> list:
        """返回线段 ``seg_id`` 上除"相邻同轨线段共享的角点"以外的真实交点。

        相邻偏移线段在折线拐点处共享一个端点, 求交算法会把它登记为交点; 这类
        "角点"不是真正的交叉事件, 不参与丝带切分。
        """
        return [tgt for tgt in self.d_seg_intersects[seg_id] if not self._is_rail_corner(seg_id, tgt)]

    def _is_simple_closed(self, i: int) -> bool:
        """闭合路径是否不含任何真实交点(其丝带应是一条完整环形带)。"""
        if not self.paths_closed[i]:
            return False
        num_seg = len(self.paths_l[i]) - 1
        return all(not self._genuine_targets((i, track, j)) for track in (1, 2) for j in range(num_seg))

    def _segment_line_intersection(self, seg_id: SegmentId, other_seg: SegmentId):
        """线段与另一线段所在**直线**求交, 允许线段端点外极短的延伸。

        返回交点坐标, 或 ``None``(平行 / 另一线段未穿过 / 交点跑得太远)。延伸上限
        取 ``max(3 * offset, 5% 线段长)``: 用于把"另一条丝带的偏移线恰好在本轨道
        拐角前结束"造成的近失交点补回来。
        """
        p1, p2 = self.d_segments[seg_id]
        p3, p4 = self.d_segments[other_seg]
        d1, d2 = p2 - p1, p4 - p3
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-12:
            return None
        d13 = p1 - p3
        ua = (d2[0] * d13[1] - d2[1] * d13[0]) / den
        ub = (d1[0] * d13[1] - d1[1] * d13[0]) / den
        if not 0.0 <= ub <= 1.0:
            return None
        length = float(np.linalg.norm(d1))
        if length <= 0.0:
            return None
        overshoot = max(0.0, -ua, ua - 1.0) * length
        if overshoot > max(3.0 * self.offset, 0.05 * length):
            return None
        return p1 + ua * d1

    def _insert_intersection(self, tgt_list: list, seg_id: SegmentId, new_tgt, point: np.ndarray) -> None:
        """按"到线段起点的距离"把 ``new_tgt`` 插回有序的交点列表。"""
        start = self.d_segments[seg_id][0]
        distance = float(np.linalg.norm(point - start))
        position = 0
        for existing in tgt_list:
            existing_point = self.d_intersections[frozenset((seg_id, existing))]
            if float(np.linalg.norm(existing_point - start)) > distance:
                break
            position += 1
        tgt_list.insert(position, new_tgt)

    def _align_rail_events(self, tgt_ids_a: list, tgt_ids_b: list, seg_a: SegmentId, seg_b: SegmentId) -> None:
        """把一侧缺失的交叉事件补到另一侧, 使左右轨道的事件序列按索引对齐。

        另一条丝带的偏移线恰好在本轨道拐角前结束时, 只有一条轨道登记到交点, 左右
        交点数相差 1(且总数为奇数); 按索引配对会把不同的交叉事件配到一起, 于是
        出现"双带同绘 / 丝带缺失"。这里把缺失的交点补回较短的轨道(两侧同步登记,
        保持对称性), 从而恢复逐事件配对。
        """
        for target, source, target_seg, source_seg in (
            (tgt_ids_a, tgt_ids_b, seg_a, seg_b),
            (tgt_ids_b, tgt_ids_a, seg_b, seg_a),
        ):
            partner = self._crossing_partners(source, source_seg)
            for tgt in list(source):
                if tgt in target or self._is_rail_corner(source_seg, tgt):
                    continue
                mate = partner.get(tgt)
                if mate is None or mate not in target:
                    continue
                point = self._segment_line_intersection(target_seg, tgt)
                if point is None:
                    continue
                key = frozenset((target_seg, tgt))
                if key in self.d_intersections:
                    continue
                self.d_intersections[key] = point
                # 拓扑插入: 紧跟它的配对事件, 保证左右轨道上同一个交叉事件相邻
                target.insert(target.index(mate) + 1, tgt)
                self._insert_intersection(self.d_seg_intersects[tgt], tgt, target_seg, point)
                logger.debug("Interlacing: 补登记近失交点 %s ∩ %s @ %s", target_seg, tgt, np.round(point, 6))

    @staticmethod
    def _group_crossings(cross_ids: list) -> list[tuple]:
        """把轨道上的真实交点两两归并成"同一次交叉"。

        另一条丝带穿过本丝带时, 它的左右两条偏移线各与本轨道相交一次, 形成相邻的
        一对交点(同属一条路径、分属两侧)。基于这个规律就能把交点按事件配对。
        """
        groups: list[tuple] = []
        k = 0
        while k < len(cross_ids):
            first = cross_ids[k]
            second = cross_ids[k + 1] if k + 1 < len(cross_ids) else None
            if second is not None and first[0] == second[0] and first[1] != second[1]:
                groups.append((first, second))
                k += 2
            else:
                groups.append((first, None))
                k += 1
        return groups

    def _crossing_partners(self, tgt_ids: list, seg_id: SegmentId) -> dict:
        """返回 ``{交点: 同一次交叉的配对交点}``(基于该轨道上的事件分组)。"""
        crossings = [tgt for tgt in tgt_ids if not self._is_rail_corner(seg_id, tgt)]
        partners: dict = {}
        for first, second in self._group_crossings(crossings):
            if second is not None:
                partners[first] = second
                partners[second] = first
        return partners

    def _set_ribbons(self) -> None:
        """提取丝带片段多边形。

        沿每条路径的左右偏移线行进, 每经过一组交点就翻转 ``flag``: ``flag`` 为真
        时补全当前片段并封口, 为假时跳过该段(留给其它丝带覆盖)。结果写入
        :attr:`ribbons`。

        两条轨道互为平行轨, 交点应成对出现且顺序一致; 缺失的近失交点已由
        :meth:`_align_all_rails` 在求解早期补齐, 这里直接逐事件配对。

        以下两类路径不参与编织切分, 直接产出一条**整条丝带**(外轮廓 + 内轮廓合成的
        环形带):

        * 无自交点的闭合路径: 否则左右偏移线会各自闭合成一个实心圆盘, 内侧圆盘把
          孔洞整个盖死(缺陷 1);
        * 派生几何不满足配对契约的路径(见 :meth:`_check_rail_geometry`): 强行切分
          只会产出跨越大半个图形的错乱片段(缺陷 3), 降级成"不编织"的整条丝带至少
          保证形状正确。
        """
        self.ribbons = []
        for i, path in enumerate(self.paths):
            if self._is_simple_closed(i) or i in self._degraded_paths:
                self.ribbons.append(annulus_polygon(self.paths_l[i], self.paths_r[i]))
                continue

            flag = self.paths_flag[i]
            nx_graph = networkx.Graph()
            num_seg = len(path) - 1

            # 开放路径的端点封口
            if not self.paths_closed[i]:
                nx_graph.add_edge(
                    frozenset(((i, 1, 0), 0)),
                    frozenset(((i, 2, 0), 0)),
                )
                nx_graph.add_edge(
                    frozenset(((i, 1, num_seg - 1), -1)),
                    frozenset(((i, 2, num_seg - 1), -1)),
                )

            for j in range(num_seg):
                seg_id_l = (i, 1, j)
                seg_id_r = (i, 2, j)
                tgt_ids_l = self.d_seg_intersects[seg_id_l]
                tgt_ids_r = self.d_seg_intersects[seg_id_r]

                # 左右偏移线互为平行轨, 正常情况下的交点数一致; 当某侧没有交点
                # (例如丝带边缘恰好落在另一条丝带之外) 时数量会不相等, 此时只按
                # 两侧对齐的部分切分, 避免索引越界。
                num_pairs = min(len(tgt_ids_l), len(tgt_ids_r))
                if num_pairs < 2:
                    continue
                if len(tgt_ids_l) != len(tgt_ids_r):
                    # 能走到这里说明补齐没能修好(退化路径已在前面跳过), 只记日志
                    logger.debug(
                        "Interlacing: 线段 %s 的左右交点数不一致 (L=%d, R=%d), 按较少的 %d 切分。",
                        seg_id_l,
                        len(tgt_ids_l),
                        len(tgt_ids_r),
                        num_pairs,
                    )

                prev_node_l = frozenset((seg_id_l, tgt_ids_l[0]))
                prev_node_r = frozenset((seg_id_r, tgt_ids_r[0]))

                for k in range(2, num_pairs - 1, 2):
                    # flag 为 True 表示当前线段会被 (k-1, k) 这组交点截断:
                    # 截断前补三条边构成 U 型, 截断后补一条边封口;
                    # flag 为 False 则延迟到下一轮再连接。
                    if flag:
                        curr_start_l = frozenset((seg_id_l, tgt_ids_l[k - 2]))
                        curr_start_r = frozenset((seg_id_r, tgt_ids_r[k - 2]))

                        if prev_node_l != curr_start_l:
                            nx_graph.add_edge(prev_node_l, curr_start_l)
                        if prev_node_r != curr_start_r:
                            nx_graph.add_edge(prev_node_r, curr_start_r)

                        nx_graph.add_edge(curr_start_l, frozenset((seg_id_l, tgt_ids_l[k - 1])))
                        nx_graph.add_edge(curr_start_r, frozenset((seg_id_r, tgt_ids_r[k - 1])))
                        nx_graph.add_edge(
                            frozenset((seg_id_r, tgt_ids_r[k - 1])),
                            frozenset((seg_id_l, tgt_ids_l[k - 1])),
                        )

                        next_start_l = frozenset((seg_id_l, tgt_ids_l[k]))
                        next_start_r = frozenset((seg_id_r, tgt_ids_r[k]))
                        nx_graph.add_edge(next_start_l, next_start_r)

                        prev_node_l = next_start_l
                        prev_node_r = next_start_r

                    flag = not flag

                end_node_l = frozenset((seg_id_l, tgt_ids_l[-1]))
                end_node_r = frozenset((seg_id_r, tgt_ids_r[-1]))

                if prev_node_l != end_node_l:
                    nx_graph.add_edge(prev_node_l, end_node_l)
                if prev_node_r != end_node_r:
                    nx_graph.add_edge(prev_node_r, end_node_r)

            for cycle in networkx.cycle_basis(nx_graph):
                if len(cycle) < 3:
                    continue
                coords = np.array([self.d_intersections[node] for node in [*cycle, cycle[0]]])
                if not right_handed(coords):
                    coords = coords[::-1]
                self.ribbons.append(coords)
