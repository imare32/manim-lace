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
#: 求交时判定"平行"的夹角正弦容差(尺度无关): ``|d1 × d2| / (|d1||d2|) < PARALLEL_SIN_ATOL``。
#:
#: 不能用叉积的绝对量: 叉积 ≈ ``|d1||d2|sinθ`` 随线段长度平方缩小, 折线点一密, 相邻两段就会被
#: 误判成平行 —— 共享角点事件随之丢失, 丝带链断开, 整幅图输出为空(实测 800 段的采样圆弧命中)。
PARALLEL_SIN_ATOL = 1e-9
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

    狭缝处留有结构标记: **外环闭合点与数组首点逐位相同**。渲染层
    (:func:`manim_lace.lace._annulus_loops`)据此把环形丝带拆回"外环 + 内环"两个
    子路径, 使描边不出现狭缝线(填充结果不变); 改动这里的输出格式时记得同步那边。

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
    """判断相邻两条边向量是否**不共线**(夹角的正弦不小于容差)。

    判据必须是**尺度无关**的: 叉积模长 ``|v_in||v_out|sinθ`` 会随边长平方缩小, 直接与
    绝对容差比较会把"点很密"的曲线里的**每一段**都判成共线 —— 实测
    ``Lace(ParametricFunction(...))`` 的默认采样会让整条曲线塌成首尾两点(渲染成一条
    直线), 采样更密时整条路径被删空(输出空白)。改成比较 ``sinθ`` 后, 只有**真正
    共线**的冗余顶点(如 Manim 贝塞尔控制点落在直线上)才会被删除。
    """
    cross = v_in[:, 0] * v_out[:, 1] - v_in[:, 1] * v_out[:, 0]
    scale = np.linalg.norm(v_in, axis=1) * np.linalg.norm(v_out, axis=1)
    scale[scale <= 0.0] = 1.0
    return np.abs(cross) / scale >= atol


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
        parallel = np.abs(cross) / (len_i * lens) < PARALLEL_SIN_ATOL

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
        # 端点判据与 vectorized_intersection 保持一致: 固定参数容差会漏掉"落在对方端点附近"
        # 的共点(参数误差可达 1e-7), 所以同样用"几何距离 <= DEFAULT_ATOL"的尺度无关写法。
        tol_i = DEFAULT_ATOL / max(len_i, DEFAULT_ATOL)
        tol_j = DEFAULT_ATOL / np.maximum(lens[~parallel], DEFAULT_ATOL)
        hit = (ua >= -tol_i) & (ua <= 1 + tol_i) & (ub >= -tol_j) & (ub <= 1 + tol_j)
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

    注意: "平行"判据是**尺度无关**的(比较 `sinθ = |d1 × d2| / (|d1||d2|)`), 而不是比较
    叉积的绝对量 —— 后者在很短的线段上会把相邻折线段误判成平行(见 :data:`PARALLEL_SIN_ATOL`),
    于是折线的"共享角点"事件丢失、丝带链断开, 输出直接变空。
    """
    d1, d2, d13 = P2 - P1, P4 - P3, P1 - P3
    denom = d1[0] * d2[:, 1] - d1[1] * d2[:, 0]
    scale = np.linalg.norm(d1) * np.linalg.norm(d2, axis=1)
    is_p = (scale <= 0.0) | (np.abs(denom) < PARALLEL_SIN_ATOL * scale)
    denom_s = np.where(is_p, 1.0, denom)
    ua = (d2[:, 0] * d13[:, 1] - d2[:, 1] * d13[:, 0]) / denom_s
    ub = (d1[0] * d13[:, 1] - d1[1] * d13[:, 0]) / denom_s
    # 端点判据也必须是**尺度无关**的: 参数容差写成"几何距离 <= DEFAULT_ATOL", 也就是
    # ``DEFAULT_ATOL / |d|``。**不能**用固定的参数容差(旧值是 1e-9): 当交点落在对方线段的
    # 端点附近时(两条路径的中心线恰好交在**拐点**上, 玫瑰线一族大量存在), 参数误差可达
    # 1e-7 量级 —— 固定 1e-9 会把这些交点**整条丢掉**, 于是"只有一侧登记到交叉事件",
    # 配对契约被破坏、整条路径降级(缺陷 10)。
    tol_a = DEFAULT_ATOL / np.maximum(np.linalg.norm(d1), DEFAULT_ATOL)
    tol_b = DEFAULT_ATOL / np.maximum(np.linalg.norm(d2, axis=1), DEFAULT_ATOL)
    mask = (~is_p) & (ua >= -tol_a) & (ua <= 1 + tol_a) & (ub >= -tol_b) & (ub <= 1 + tol_b)
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
        self._woven_paths: dict[int, list[np.ndarray]] = {}

        if not self.paths:
            logger.debug("Interlacing: 输入中没有可用的路径, 跳过求解。")
            return

        self._prepare_paths()
        self._build_segments()
        self._cal_intersections()
        # 按"交叉配对"重归属事件(修左右接缝弧长不同导致的逐段错位) → 补近失交点 →
        # 最后做契约自检与降级判定
        self._normalize_rail_attribution()
        self._align_all_rails()
        self._check_rail_geometry()
        self._fix_path_flags()
        # 对"现行降级"的路径试一次按交叉身份的切分(只修坏的: 健康路径不进这里)
        self._try_crossing_weave()
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

    def _rail_events(self, i: int, track: int) -> tuple[list[dict], list[tuple[list, list]]]:
        """一条轨道上的事件记录与各线段的"接缝事件"。

        返回 ``(records, seams)``:

        * ``records``: 除接缝(相邻同轨线段的共享角点、开放路径端点封口)以外的全部事件,
          每项含 ``seg``(所在线段下标)、``tgt``(对方线段标识)、``point``(交点坐标)、
          ``arc``(沿轨道的弧长), 按弧长升序排列;
        * ``seams``: 每个线段的 ``(前导接缝, 后继接缝)`` 标识列表, 保持原始登记顺序。

        接缝事件负责把逐段子图缝成整条轨道, 不参与交叉配对, 重组时原样留在首尾。
        """
        num_seg = len(self.paths_l[i]) - 1
        rail = self.paths_l[i] if track == 1 else self.paths_r[i]
        starts = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(rail, axis=0), axis=1))])

        records: list[dict] = []
        seams: list[tuple[list, list]] = []
        for j in range(num_seg):
            seg_id = (i, track, j)
            raw = list(self.d_seg_intersects[seg_id])
            if self.paths_closed[i]:
                prev_id, next_id = (i, track, (j - 1) % num_seg), (i, track, (j + 1) % num_seg)
            else:
                prev_id, next_id = (i, track, j - 1), (i, track, j + 1)
            # 接缝按"对方是上一段 / 下一段"分开, 而不是按列表里的位置切分: 一条**没有任何
            # 交叉事件**的弧段也要能与另一条轨道对上(按位置切分会把两个角点都塞进前导,
            # 两侧长度不等 -> 整条路径被跳过重归属, 于是"两圆相交"这种最基础的情形也降级)。
            leading = [tgt for tgt in raw if tgt == prev_id]
            trailing = [tgt for tgt in raw if tgt == next_id]
            caps = [tgt for tgt in raw if not isinstance(tgt, tuple)]  # 开放路径的端点封口
            if caps:
                if j == 0:
                    leading = [*caps, *leading]
                if j == num_seg - 1:
                    trailing = [*trailing, *caps]
            seams.append((leading, trailing))
            for tgt in raw:
                if self._is_rail_corner(seg_id, tgt):
                    continue
                point = self.d_intersections[frozenset((seg_id, tgt))]
                records.append(
                    {
                        "seg": j,
                        "tgt": tgt,
                        "point": point,
                        "arc": float(starts[j] + np.linalg.norm(point - rail[j])),
                    },
                )
        records.sort(key=lambda record: record["arc"])
        return records, seams

    def _is_mirror_event(self, i: int, first: dict, second: dict) -> bool:
        """两个事件是否互为"同一个交叉"在左右两条轨道上的那一对。

        判据: 对方路径相同、间隔接近丝带宽度(实测配对距离集中在 2.0 ~ 2.9 × offset),
        且对方轨道要么相同(与另一条丝带横穿), 要么互为两侧(本丝带自交时两条轨各自与
        自己的另一侧相交)。
        """
        tgt_first, tgt_second = first["tgt"], second["tgt"]
        if not isinstance(tgt_first, tuple) or not isinstance(tgt_second, tuple):
            return False
        if tgt_first[0] != tgt_second[0]:
            return False
        gap = float(np.linalg.norm(first["point"] - second["point"]))
        if not 0.1 * self.offset <= gap <= 8.0 * self.offset:
            return False
        if tgt_first[1] != tgt_second[1]:
            # 对方轨道不同: 只可能出现在本丝带自交(自交的两条轨各与自己的另一侧相交)
            return tgt_first[0] == i
        return True

    @staticmethod
    def _centerline_segment_index(path: np.ndarray, point: np.ndarray) -> int:
        """把点投影到中心线折线, 返回最近线段的下标。"""
        seg_a, seg_b = path[:-1], path[1:]
        ab = seg_b - seg_a
        ab_len2 = np.maximum(np.sum(ab * ab, axis=1), 1e-18)
        ratio = np.clip(np.sum((point - seg_a) * ab, axis=1) / ab_len2, 0.0, 1.0)
        proj = seg_a + ratio[:, None] * ab
        return int(np.argmin(np.linalg.norm(point - proj, axis=1)))

    def _normalize_rail_attribution(self) -> None:
        """按"交叉配对"重新归属偏移线交点, 使同一条线段上左右事件数相等。

        左右偏移线互为平行轨, 但**接缝(拐点)的弧长位置不同**(miter 在凸角外侧延伸、
        凹角内侧收缩), 于是同一个交叉的两侧交点可能被登记到相邻的线段上: 逐段计数不再
        相等, :meth:`_check_rail_geometry` 据此把整条路径降级, 按索引配对也会错配事件
        (CA n=9/15/16 的 L4~L5 就是这种情形, 两侧事件总数其实完全相等)。

        做法: 把两侧事件按**沿轨道的弧长顺序**逐位配对, 用配对中点在**中心线**上的投影
        决定线段归属 —— 两侧共用同一个中点, 归属结果必然一致, 逐段计数随之相等。
        提交改挂交给 :meth:`_commit_rail_reattribution`(事件的"身份"是
        ``(线段标识, 对方线段标识)``, 两个标识都要跟着改写)。

        只有整条路径的每一对都通过 :meth:`_is_mirror_event` 校验时才重建; 否则原样保留,
        交由 :meth:`_check_rail_geometry` 按既有策略降级(不会比原来更差)。逐段计数本来
        就相等的路径**直接跳过**, 保证对正常输入的输出不变(重建虽然不改变丝带的并集, 但会
        把片段切得更碎)。

        已知局限: CR/PR/PO 一族的偏移线**自交**事件在两条轨道上的位置不同, 会把两侧事件的
        相对顺序打乱, 逐位配对随之失效(这些路径继续走降级); 另有部分交叉的镜像事件在几何
        上根本不存在(对方偏移线段被 miter 接头截短), 需要先修接头拓扑才能编织。
        """
        for i in range(len(self.paths)):
            num_seg = len(self.paths_l[i]) - 1
            if all(
                len(self.d_seg_intersects[(i, 1, j)]) == len(self.d_seg_intersects[(i, 2, j)]) for j in range(num_seg)
            ):
                continue
            left, seams_l = self._rail_events(i, 1)
            right, seams_r = self._rail_events(i, 2)
            if not left or len(left) != len(right):
                continue
            if any(len(a) != len(b) for a, b in zip(seams_l, seams_r)):
                continue
            if not all(self._is_mirror_event(i, a, b) for a, b in zip(left, right)):
                # 两侧事件不是逐位对应(真漏登记 / 相切退化 / 自交事件打乱顺序):
                # 保留原样交给降级与近失补齐
                logger.debug("Interlacing: 路径 %d 的左右轨道事件无法逐位配对, 跳过重归属。", i)
                continue

            for first, second in zip(left, right):
                owner = self._centerline_segment_index(self.paths[i], (first["point"] + second["point"]) / 2.0)
                first["owner"] = owner
                second["owner"] = owner

            if not self._reservation_is_consistent(i, left, right):
                # 逐位配对得到的"新归属"会让同一个交点出现两条记录(同一条轨道上的自交事件
                # 共用一把 key), 无法同时改挂 —— 整条路径放弃重归属, 交给既有降级策略,
                # 而不是让求解中途抛 KeyError。
                logger.debug("Interlacing: 路径 %d 的重归属目标不自洽(自交事件共用交点), 跳过重归属。", i)
                continue

            self._commit_rail_reattribution(i, left, right, seams_l, seams_r)

    def _centerline_crossings(self, i: int) -> list[dict]:
        """路径 ``i`` 的中心线交叉(含与自身的自交)。

        枚举**所有**与路径 ``i`` 相关的路径对(``q`` 取遍全部路径, 否则 ``i > 0`` 时会漏掉与
        前面路径的交叉); 自交时跳过相邻线段(含闭合处的绕回), 因为它们共享端点。
        返回 ``[{"point", "i_seg", "q", "q_seg", "sin_theta"}]``(``sin_theta`` 为两支的夹角正弦,
        用于让"角点到交叉点的距离"这一阈值随夹角自适应)。
        """
        crossings: list[dict] = []
        num_seg = len(self.paths[i]) - 1
        for q in range(len(self.paths)):
            other = self.paths[q]
            b0, b1 = other[:-1], other[1:]
            for j in range(num_seg):
                a0, a1 = self.paths[i][j], self.paths[i][j + 1]
                points, mask = vectorized_intersection(a0, a1, b0, b1)
                for m in np.flatnonzero(mask):
                    m = int(m)
                    if q == i and (m <= j + 1 or (j == 0 and m == num_seg - 1 and not self.paths_closed[i])):
                        # 自交: 只数一次(避免 (j, m) / (m, j) 重复), 并跳过相邻线段(共享端点);
                        # 闭合路径的首尾线段相邻(绕回), 开放路径的 0 号与末号段不算相邻
                        continue
                    d1, d2 = a1 - a0, b1[m] - b0[m]
                    scale = float(np.linalg.norm(d1) * np.linalg.norm(d2))
                    sin_theta = float(abs(d1[0] * d2[1] - d1[1] * d2[0]) / scale) if scale > 0.0 else 0.0
                    crossings.append(
                        {"point": points[m], "i_seg": j, "q": q, "q_seg": m, "sin_theta": sin_theta},
                    )
        return crossings

    def _merge_crossings(self, crossings: list[dict]) -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
        """把**重合**的中心线交叉锚点并成一组(单链聚类, 阈值 5% offset)。

        返回 ``(锚点坐标, 归属阈值)``; 阈值取组内最松的那个(``2.5 * offset / max(min sinθ, 0.3)``),
        保证组内所有角点都能被吸进来。
        """
        points = np.array([crossing["point"] for crossing in crossings])
        sin_theta = np.array([max(float(crossing["sin_theta"]), 0.3) for crossing in crossings])
        close = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2) <= 0.05 * self.offset

        parent = list(range(len(crossings)))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for a, b in zip(*np.nonzero(np.triu(close, k=1)), strict=True):
            parent[find(int(b))] = find(int(a))

        clustered: dict[int, list[int]] = {}
        for index in range(len(crossings)):
            clustered.setdefault(find(index), []).append(index)
        anchors = np.array([points[members].mean(axis=0) for members in clustered.values()])
        limits = np.array([2.5 * self.offset / float(sin_theta[members].min()) for members in clustered.values()])
        return anchors, limits, list(clustered.values())

    def _crossing_groups(
        self,
        i: int,
        left: list[dict] | None = None,
        right: list[dict] | None = None,
    ) -> list[tuple[list[tuple[int, dict]], list[dict]]] | None:
        """把路径 ``i`` 的轨记录按**中心线交叉**归拢成组(只读)。

        分组判据: 每条非接缝轨记录归属到"距离最近的交叉点", 阈值 ``2.5 * offset / max(sinθ, 0.3)``
        (实测角点到交叉中心的距离在 ``1.0 ~ 1.6 x offset``; 1.5 太紧, 会把正常交叉的角点判成孤立 ——
        见 ``media/_review/crossing_group_probe.py`` 的阈值校准)。**有孤立或歧义(同时落在两个交叉的
        阈值内)时返回 ``None``** —— 这是阶段 1 的启用护栏: 分组不干净就不动它(宁缺勿滥)。
        """
        crossings = self._centerline_crossings(i)
        if not crossings:
            return None
        # 合并**重合锚点**: 交叉恰好落在折线顶点上时(离散化使然), 同一位置会被两条相邻的
        # 线段对各枚举一次(实测相距 1.7e-5 = 3e-4 x offset) —— 不合并的话记录会"同时命中两个
        # 锚点"而被判歧义。合并阈值取 5% offset: 真实的不同交叉不会这么近。
        anchors, limits, crossings_per_group = self._merge_crossings(crossings)
        groups: list[list[tuple[int, dict]]] = [[] for _ in anchors]
        for track, provided in ((1, left), (2, right)):
            # ⚠️ 必须复用调用方送进来的那批记录对象(否则 `owner` 写在了另一批字典上, 提交看不到)
            records = provided if provided is not None else self._rail_events(i, track)[0]
            for record in records:
                hits = np.flatnonzero(np.linalg.norm(anchors - record["point"], axis=1) <= limits)
                if len(hits) != 1:
                    logger.debug(
                        "Interlacing: 路径 %d 的分组不干净(孤立或歧义): track=%d seg=%d 命中 %d 个交叉。",
                        i,
                        track,
                        record["seg"],
                        len(hits),
                    )
                    return None
                groups[int(hits[0])].append((track, record))
        return [
            (members, [crossings[index] for index in indices])
            for members, indices in zip(groups, crossings_per_group, strict=True)
        ]

    def _segment_window(self, i: int) -> int:
        """分簇/归属共用的**段数窗口**: 同一分支的角点沿轨相距约 ``2 * offset``。

        换算成段数的阈值(``8 * offset / 段长``)同时用于 :meth:`_branch_clusters` 的分簇与
        :meth:`_crossing_attribution` 的归属半径。
        """
        step = float(np.median(np.linalg.norm(np.diff(self.paths[i], axis=0), axis=1)))
        return max(1, int(np.ceil(8.0 * self.offset / max(step, 1e-12))))

    @staticmethod
    def _segment_gap(first: float, second: float, num_seg: int, closed: bool) -> float:
        """两个线段号之间的**环距**(闭合路径取绕回方向, 与 :meth:`_branch_clusters` 一致)。"""
        gap = abs(float(first) - float(second))
        return min(gap, num_seg - gap) if closed else gap

    @staticmethod
    def _nearest_segment(candidates: set[int], segs: list[int], num_seg: int, closed: bool) -> int:
        """在候选线段里挑离这一簇记录最近的那一段(闭合路径用环距)。

        一次交叉的两对镜像记录必须落在**同一段**上: `_set_ribbons` 只有看到"同一段上左右各
        一对事件"才会切一刀 —— 实测取"这一对自己所在的段"会让两对落在相隔 7 段的两个段上,
        于是整个交叉都不切分、画成双带同绘。
        """
        reference = float(np.median(segs))
        best, best_gap = None, None
        for candidate in sorted(candidates):
            gap = abs(reference - candidate)
            if closed:
                gap = min(gap, num_seg - gap)
            if best_gap is None or gap < best_gap:
                best, best_gap = candidate, gap
        return int(best)

    def _branch_clusters(self, i: int, members: list[tuple[int, dict]]) -> list[list[tuple[int, dict]]]:
        """按**中心线段号的环距**把一次交叉的记录分成"分支"簇(单链聚类)。

        阈值取 ``8 * offset / 中心线段的段长``: 同一分支的角点沿轨相距约 ``2 * offset``,
        而不同分支沿轨相隔很远(实测利萨如原点交叉的两支相隔约 500 段); 闭合路径用环距,
        因为交叉落在闭合点附近时同一分支会横跨绕回处。
        """
        if len(members) <= 1:
            return [list(members)]
        segs = np.array([record["seg"] for _track, record in members])
        num_seg = len(self.paths_l[i]) - 1
        window = self._segment_window(i)
        gaps = np.abs(segs[:, None] - segs[None, :])
        if self.paths_closed[i]:
            gaps = np.minimum(gaps, num_seg - gaps)
        parent = list(range(len(members)))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if gaps[a, b] <= window:
                    parent[find(b)] = find(a)
        clustered: dict[int, list[tuple[int, dict]]] = {}
        for index, member in enumerate(members):
            clustered.setdefault(find(index), []).append(member)
        return list(clustered.values())

    @staticmethod
    def _pair_cluster_records(cluster: list[tuple[int, dict]]) -> list[tuple[dict, dict]] | None:
        """把"一次穿越"在一个分支簇里的记录按**对方线段**配对(左轨记录 ↔ 它的镜像)。

        判据是对方线段标识**完全相同**(对方路径 + 对方轨道 + 对方段号): 对方丝带的两条偏移线
        与本丝带相交, 每个交点在本丝带的左右两条轨道上各有一条记录, 它们指向**同一条**对方
        偏移线段。找不到唯一镜像时返回 ``None``(调用方放弃按交叉重建)。
        """
        rights = [record for track, record in cluster if track == 2]
        pairs: list[tuple[dict, dict]] = []
        for track, record in cluster:
            if track != 1:
                continue
            target = record["tgt"]
            if not isinstance(target, tuple):
                return None
            matched = [other for other in rights if isinstance(other["tgt"], tuple) and other["tgt"] == target]
            if len(matched) != 1:
                return None
            rights.remove(matched[0])
            pairs.append((record, matched[0]))
        return pairs or None

    @staticmethod
    def _cluster_pass_records(cluster: list[tuple[int, dict]]) -> tuple[tuple[dict, dict], tuple[dict, dict]] | None:
        """把一个分支簇整理成"一次穿越"的四个角点。

        对方丝带的两条偏移线各与本丝带的左右两条轨道相交, 所以一次穿越在**每条轨道上**留下
        两个交点。这里按**对方轨道**索引它们(1 = 对方左偏移线, 2 = 对方右偏移线), 返回
        ``(左轨的一对, 右轨的一对)``; 同一个交叉的两条偏移线在同一位置的不同段上被登记
        (密采样时更是跨 4~8 段), 所以不能用对方**段号**来配对。

        任一条轨道的记录不是恰好两条、或对方轨道索引凑不齐 ``{1, 2}`` 时返回 ``None``。
        """
        result: dict[int, tuple[dict, dict]] = {}
        for track in (1, 2):
            records = [record for record_track, record in cluster if record_track == track]
            if len(records) != 2:
                return None
            slots: dict[int, dict] = {}
            for record in records:
                target = record["tgt"]
                if not isinstance(target, tuple) or target[1] not in (1, 2):
                    return None
                slots[target[1]] = record
            if set(slots) != {1, 2}:
                return None
            result[track] = (slots[1], slots[2])
        return result[1], result[2]

    def _crossing_attribution(self, i: int) -> tuple[list[dict], list, list[dict], list, int] | None:
        """按交叉分组算出新的线段归属(阶段 1); 分组不干净或配对不完整时返回 ``None``。

        组内先按"记录自己所在的线段"分簇(= 两条分支), 每条分支内按**对方路径 + 对方轨道**配对
        (同一对的两个角点落在对方同一条偏移轨上), 归属取这一对自己所在的线段 —— 一次自交的
        四个角点分属两条分支, 各自留在自己分支的线段上, 分支上的切分才不会丢。
        """
        left, seams_l = self._rail_events(i, 1)
        right, seams_r = self._rail_events(i, 2)
        if not left or len(left) != len(right) or any(len(a) != len(b) for a, b in zip(seams_l, seams_r)):
            return None
        groups = self._crossing_groups(i, left, right)
        if groups is None:
            return None

        num_seg = len(self.paths_l[i]) - 1
        window = self._segment_window(i)
        pairs = 0
        for group_index, (members, raw_crossings) in enumerate(groups):
            if not members:
                logger.debug("Interlacing: 路径 %d 的交叉 %d 没有任何轨记录, 放弃按交叉重建。", i, group_index)
                return None
            # 本次交叉在**本路径**上的候选线段: 交叉自己的段; 自交时两条分支各有一段
            candidates = {int(crossing["i_seg"]) for crossing in raw_crossings}
            candidates |= {int(crossing["q_seg"]) for crossing in raw_crossings if crossing["q"] == i}
            # 按"自己所在的线段"分簇(= 分支)。用**中心线段号**当公共参照系: 两条轨道的
            # `arc` 参照系并不可比(实测同段号处两轨 arc 差 0.78), 而段号是共同的; 阈值换算成
            # 段数(`8 * offset / 段长`), 闭合路径用**环距**(交叉落在闭合点附近时同一分支横跨绕回处)。
            clusters = self._branch_clusters(i, members)
            for cluster in clusters:
                cluster_pairs = self._pair_cluster_records(cluster)
                if cluster_pairs is None:
                    logger.debug(
                        "Interlacing: 路径 %d 的交叉 %d 里同一分支的镜像记录不唯一, 放弃按交叉重建。",
                        i,
                        group_index,
                    )
                    return None
                cluster_segs = [record["seg"] for _track, record in cluster]
                owner = self._nearest_segment(
                    candidates,
                    cluster_segs,
                    num_seg,
                    self.paths_closed[i],
                )
                for first, second in cluster_pairs:
                    own_seg = int(round(float(np.median([first["seg"], second["seg"]]))))
                    pair_owner = owner
                    if self._segment_gap(pair_owner, own_seg, num_seg, self.paths_closed[i]) > window:
                        # 候选段离这一对太远: 自交的两条分支可以相隔近半个曲线, 而它们共用
                        # 同一批候选段 —— 强行归过去会把两条分支折叠到同一段(不同旧键 ->
                        # 同一新键, 坐标互相覆盖), 事件于是挂在"不在其上的线段"上, 后续按段
                        # 切分整片错乱。保留这一对自己所在的段。
                        pair_owner = own_seg
                    first["owner"] = second["owner"] = pair_owner
                    pairs += 1
        return left, seams_l, right, seams_r, pairs

    def _commit_rail_reattribution(
        self,
        i: int,
        left: list[dict],
        right: list[dict],
        seams_l: list[tuple[list, list]],
        seams_r: list[tuple[list, list]],
    ) -> None:
        """提交 :meth:`_normalize_rail_attribution` 算出的"新归属"(逐段重挂交点)。

        事件的**身份**是 ``(本方线段, 对方线段)`` 这一对标识, 改挂时两端都要写成"改挂后"的
        标识: 对方线段那一端的新标识 = **它的另一端记录**自己的 owner(两条记录互为对方)。
        任何一处漏改, "列表里引用的标识"就与"交点表的键"对不上 —— 后续
        :meth:`_fix_path_flags` / :meth:`_set_holes` 取交点坐标时会抛 :class:`KeyError`
        (实测 ``PA n=7 L7`` / ``CA n=12 L6`` / ``CR n=19 L4`` 等配置命中, 见 ``DEFECTS.md`` 缺陷 9)。

        ⚠️ 不能按"线段"整体替换标识: 同一条线段上常常只有**一部分事件**改挂, 其余留在原线段
        (实测 ``CA n=9 L4`` 的 36 号线段 6 个事件里只走 1 个), 按线段替换会把没动的事件也搬走。

        提交后立刻校验"所有引用都能查到交点键", 不过就整体回滚(保持原样, 交给既有降级策略),
        保证求解不会中途崩掉。
        """
        events: dict[tuple[SegmentId, SegmentId], dict] = {}
        for track, records in ((1, left), (2, right)):
            for record in records:
                events[((i, track, record["seg"]), record["tgt"])] = record

        # 每一条记录都去找它的"另一端记录"(自己的线段正是本条记录的对方线段、且对方线段正是
        # 本条记录自己的线段), 对方的新标识就是那条记录自己的 owner。⚠️ 不能按"线段"整体替换:
        # 同一条线段上常常只有**一部分事件**改挂, 其余留在原线段(CA n=9 L4 的 36 号线段就是
        # 6 个事件里只走 1 个), 按线段替换会把没动的事件也一起搬走。
        moves: list[tuple[frozenset, frozenset]] = []
        for track, records in ((1, left), (2, right)):
            for record in records:
                partner = record["tgt"]
                if isinstance(partner, tuple):
                    reverse = events.get((partner, (i, track, record["seg"])))
                    if reverse is not None:
                        partner = (partner[0], partner[1], reverse["owner"])
                record["partner"] = partner
                old_key = frozenset(((i, track, record["seg"]), record["tgt"]))
                new_key = frozenset(((i, track, record["owner"]), partner))
                if old_key != new_key:
                    moves.append((old_key, new_key))
        if len({old for old, _ in moves}) != len(set(moves)):
            logger.debug("Interlacing: 路径 %d 的重归属目标互相冲突, 跳过重归属。", i)
            return
        folded: dict[frozenset, set[frozenset]] = defaultdict(set)
        for old_key, new_key in moves:
            folded[new_key].add(old_key)
        if any(len(olds) > 1 for olds in folded.values()):
            # 两条**不同**的边被折到同一把新键上: 字典写入会互相覆盖, 一个交点的坐标被另一个
            # 顶替 —— 事件挂在"不在其上的线段"上, 后续按段切分会整片错乱(实测稠密自交曲线)。
            # 宁可保持降级, 也不静默画错。
            logger.debug("Interlacing: 路径 %d 的重归属会把不同交点折叠到同一把键上, 跳过重归属。", i)
            return
        try:
            # 同一次改挂里两条记录共用旧键(同一事件的另一端), 所以先一并读出、再一并删除/写入
            points = {new_key: self.d_intersections[old_key] for old_key, new_key in moves}
        except KeyError:
            logger.debug("Interlacing: 路径 %d 的重归属引用了不存在的交点, 跳过重归属。", i)
            return
        # 没有线段改挂时(两份记录都留在原线段)键表不变, 只剩下面"按新顺序重排列表"这一步
        snapshot = None
        if moves:
            snapshot = (
                dict(self.d_intersections),
                {seg_id: list(targets) for seg_id, targets in self.d_seg_intersects.items()},
            )
            for old_key in {old_key for old_key, _ in moves}:
                del self.d_intersections[old_key]
            self.d_intersections.update(points)

        # --- 2. 本路径两条轨道的列表: 按"新归属"整段重建(接缝事件留在首尾) ---
        for track, records, seams in ((1, left, seams_l), (2, right, seams_r)):
            buckets: dict[int, list] = defaultdict(list)
            for record in records:
                buckets[record["owner"]].append(record["partner"])
            for j, (leading, trailing) in enumerate(seams):
                self.d_seg_intersects[(i, track, j)] = [*leading, *buckets[j], *trailing]

        # --- 3. 其它路径的列表: 把引用本路径旧线段标识的反向引用换成新标识 ---
        for track, records in ((1, left), (2, right)):
            for record in records:
                partner = record["tgt"]
                old_seg, new_seg = (i, track, record["seg"]), (i, track, record["owner"])
                if not isinstance(partner, tuple) or partner[0] == i or old_seg == new_seg:
                    continue
                targets = self.d_seg_intersects.get(partner)
                if targets and old_seg in targets:
                    targets[targets.index(old_seg)] = new_seg

        if snapshot is not None and not self._rail_references_are_consistent():
            intersections, lists = snapshot
            self.d_intersections.clear()
            self.d_intersections.update(intersections)
            self.d_seg_intersects.clear()
            self.d_seg_intersects.update(lists)
            logger.debug("Interlacing: 路径 %d 的重归属结果不自洽, 已回滚。", i)
            return
        logger.debug("Interlacing: 路径 %d 按交叉配对重归属了 %d 个偏移线交点。", i, len(left))

    def _rail_references_are_consistent(self) -> bool:
        """每一条"线段列表里引用的交点"都必须能在 :attr:`d_intersections` 里查到坐标。

        这是重归属的提交护栏: 事件的身份是 ``(本方线段, 对方线段)``, 一旦只改了一边, 列表
        里就会留下查不到的标识, 后续按标识取坐标时会抛 :class:`KeyError`(见缺陷 9)。
        """
        return all(
            not isinstance(tgt, tuple) or frozenset((seg_id, tgt)) in self.d_intersections
            for seg_id, targets in self.d_seg_intersects.items()
            for tgt in targets
        )

    def _reservation_is_consistent(self, i: int, left: list[dict], right: list[dict]) -> bool:
        """预演一遍 :meth:`_normalize_rail_attribution` 的改挂, 判断能否安全执行。

        每条记录要把交点键 ``{原线段, 对方线段}`` 换成 ``{新线段, 对方线段}``。**同一条
        轨道上的自交事件**的两条记录共用同一把键, 改挂时第二条记录会指向与第一条不同的
        新键(或 pop 到不存在的键) —— 这种情形必须在动手之前查出来, 否则求解会中途抛
        :class:`KeyError`(实测稠密自交曲线会命中, 见 ``tests/test_lace.py::TestDenseCurves``)。
        """
        keys = set(self.d_intersections)
        for track, records in ((1, left), (2, right)):
            for record in records:
                old_seg, new_seg = (i, track, record["seg"]), (i, track, record["owner"])
                if new_seg == old_seg:
                    continue
                old_key = frozenset((old_seg, record["tgt"]))
                if old_key not in keys:
                    return False
                keys.discard(old_key)
                keys.add(frozenset((new_seg, record["tgt"])))
        return True

    def _align_all_rails(self) -> None:
        """对所有"左右偏移线交点数不等"的线段按**交叉事件**补齐缺失的交点。

        另一条丝带的偏移线恰好在本轨道拐角前结束时, 只有一条轨道登记到交点, 左右
        交点数相差 1; 按索引配对会把不同的交叉事件配到一起(双带同绘 / 丝带缺失)。
        这里把缺失的交点补回较短的轨道(拓扑上紧跟其配对事件), 恢复逐事件配对。

        重归属(:meth:`_normalize_rail_attribution`)之后这里只剩"真正漏登记"的近失
        交点(共线端点、对方线段在到达本轨前结束), 见 :meth:`_align_rail_events`。
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

        契约有两条, 都是 :meth:`_set_ribbons` 按索引配对的前提:

        1. "同一条线段上, 左右偏移线的交点数相等";
        2. "交叉不与偏移线拐点重合" —— 即两侧交点能按索引一一对应(见 :meth:`_has_joint_crossing`)。

        契约不成立时, 这些路径无法正确编织, 会被标记为**降级渲染**(退化成不编织的整条
        丝带), 而不是静默产出错乱图形。

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
                # 整条路径降级(而不是只在坏段上"不切分"): 后者在不对称普遍存在时
                # 会让整条丝带一次都不切, 双带同绘比例从 19% 涨到 72%, 详见 CHANGELOG。
                self._degraded_paths.add(i)
            elif self._has_joint_crossing(i):
                self.rail_issues.append(f"路径 {i}: 存在落在偏移线拐点上的交叉(接头处退化)")
                self._degraded_paths.add(i)

    def _try_crossing_weave(self) -> None:
        """对"现行降级"的路径试一次**按交叉身份**的编织(阶段 1 第三步)。

        流程 = :meth:`_crossing_ribbon_cycles`, **不改任何中间状态**(失败即放弃)。成功的路径
        改用编织片段并撤销降级标记, 其余保持"不编织"的整条丝带 —— 即"只修坏的": 健康路径根本
        不进这里, 救不回来的配置输出也逐字节不变。降级结论与**告警**在这里统一给出(此前
        :meth:`_check_rail_geometry` 只写 :attr:`rail_issues`, 结论要等这次尝试之后才最终确定)。
        """
        self._woven_paths: dict[int, list[np.ndarray]] = {}
        for i in sorted(self._degraded_paths):
            cycles = self._crossing_ribbon_cycles(i)
            if cycles is None:
                continue
            self._woven_paths[i] = cycles
            self._degraded_paths.discard(i)
            prefix = f"路径 {i}:"
            self.rail_issues = [issue for issue in self.rail_issues if not issue.startswith(prefix)]
        if self.rail_issues:
            warnings.warn(
                "偏移线不满足配对契约(同一线段左右交点数不等或交叉落在拐点上), "
                "相关路径已退化为'不编织'的整条丝带; 详见 Interlacing.rail_issues。"
                "要提前拒绝退化输入可用 Interlacing(validate='raise')。",
                UserWarning,
                stacklevel=2,
            )

    def _has_joint_crossing(self, i: int) -> bool:
        """路径 ``i`` 上是否存在"落在偏移线拐点上的交叉"。

        当两条丝带的中心线恰好交在**对方的拐点**上时(旋转全等的星形图案大量存在这种位置:
        一个角尖正好压在另一条边的中段), 偏移线求交会落在对方 miter 接头上 —— 表现为
        "同一个交叉的四个角点分属拐点两侧的两条线段", 按索引配对无法表达。实测这类配置
        强行切分后 C/D/E/F 全亮(破洞 + 双带同绘), 因此与"逐段计数不等"一样按退化处理。

        判据只看**结构性事实**: 交点到参与求交的两条线段的某个端点距离 <=
        :data:`DEFAULT_ATOL`, 且这两条线段不是同轨相邻(相邻就是结构角点, 由
        :meth:`_fill_rail_corners` 登记, 不算退化)。
        """
        for track in (1, 2):
            for j in range(len(self.paths_l[i]) - 1):
                seg_id = (i, track, j)
                first_start, first_end = self.d_segments[seg_id]
                for tgt in self.d_seg_intersects[seg_id]:
                    if not isinstance(tgt, tuple) or self._is_rail_corner(seg_id, tgt):
                        continue
                    point = self.d_intersections[frozenset((seg_id, tgt))]
                    second_start, second_end = self.d_segments[tgt]
                    if any(
                        float(np.linalg.norm(u - v)) <= DEFAULT_ATOL
                        for u in (first_start, first_end)
                        for v in (second_start, second_end)
                    ):
                        continue  # 同轨相邻线段共享端点: 这是结构角点, 不是退化
                    if not any(
                        float(np.linalg.norm(point - vertex)) <= DEFAULT_ATOL
                        for vertex in (first_start, first_end, second_start, second_end)
                    ):
                        continue
                    return True
        return False

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

        # --- 4. 补齐"相邻同轨线段共享端点"的角点(结构事实, 不依赖浮点判定) ---
        self._fill_rail_corners()

        # --- 5. 收尾: 多线共点告警 + 按距离排序 ---
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

    def _plain_band(self, i: int) -> np.ndarray:
        """整条丝带(不参与编织的降级形态)。

        * **闭合路径**: 环形带(外环 + 反向内环 + 一条狭缝, 见 :func:`annulus_polygon`),
          中间的孔洞得以露出;
        * **开放路径**: 左右偏移线合围的条带(左轨正向 + 右轨反向 + 首尾封口)。

        之前两种情况都走 :func:`annulus_polygon`, 而它假定输入是**两条闭合环** —— 开放路径
        会因此得到一个自交的怪多边形(非零环绕填充下会出现"凭空的白洞")。
        """
        left, right = self.paths_l[i], self.paths_r[i]
        if self.paths_closed[i]:
            return annulus_polygon(left, right)
        strip = np.vstack([left, right[::-1], left[:1]])
        return strip if right_handed(strip) else strip[::-1]

    def _fill_rail_corners(self) -> None:
        """补齐"相邻同轨线段共享端点"的角点事件。

        这类事件本该由通用求交登记, 但采样很密的折线上两条相邻线段的夹角极小, 共享端点的
        判定会落在浮点误差里(``denom ≈ |d1||d2|sinθ`` 很小, 相对误差被放大) —— 于是角点事件
        丢失, 逐段子图连不成整条轨道, 整幅图**输出为空**(实测 800 段的采样圆弧: 末 3 段
        事件数 1/0/0)。

        共享端点是构造保证的, 所以这里按结构直接登记, 而不是去求交。**已经登记过的角点
        原样保留**(因此对既有输入零影响)。

        开放路径的首尾封口不在这里处理(:meth:`_set_holes` 负责)。
        """
        for i in range(len(self.paths_l)):
            num_seg = len(self.paths_l[i]) - 1
            if num_seg < 2:
                continue
            for track in (1, 2):
                rail = self.paths_l[i] if track == 1 else self.paths_r[i]
                pairs = [(j, j + 1) for j in range(num_seg - 1)]
                if self.paths_closed[i]:
                    pairs.append((num_seg - 1, 0))
                for first, second in pairs:
                    seg_a, seg_b = (i, track, first), (i, track, second)
                    key = frozenset((seg_a, seg_b))
                    if key in self.d_intersections:
                        continue
                    self.d_intersections[key] = rail[second]
                    self.d_seg_intersects[seg_a].append(seg_b)
                    self.d_seg_intersects[seg_b].append(seg_a)

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
        scale = float(np.linalg.norm(d1) * np.linalg.norm(d2))
        if scale <= 0.0 or abs(den) < PARALLEL_SIN_ATOL * scale:  # 平行(尺度无关, 同求交)
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

    def _path_crossings(self, i: int) -> list[tuple[np.ndarray, int]]:
        """路径 ``i`` 上**按先后顺序**排列的交叉: ``(代表点, 对方路径下标)``。

        一个交叉 = 同一线段上成对出现的两个真实事件(对方丝带的左右两条轨), 与
        :meth:`_set_ribbons` 里 ``flag`` 翻转的粒度一致(每段按事件对逐个翻转)。
        """
        sequence: list[tuple[np.ndarray, int]] = []
        for j in range(len(self.paths_l[i]) - 1):
            seg_id = (i, 1, j)
            genuine = [tgt for tgt in self.d_seg_intersects[seg_id] if not self._is_rail_corner(seg_id, tgt)]
            for k in range(0, len(genuine) - 1, 2):
                first, second = genuine[k], genuine[k + 1]
                if not isinstance(first, tuple) or not isinstance(second, tuple):
                    continue
                point = (
                    self.d_intersections[frozenset((seg_id, first))] + self.d_intersections[frozenset((seg_id, second))]
                ) / 2.0
                sequence.append((point, first[0]))
        return sequence

    def _fix_path_flags(self) -> None:
        """修正各路径的起始 ``flag``, 使**每个交叉恰好一方压上**(织法自洽)。

        每条路径的 ``flag`` 在**每个交叉**处翻转一次, 所以它在自己第 ``pos`` 个交叉处的
        取值是 ``paths_flag[i] ^ (pos % 2)``; 自洽要求一个交叉的两方取值相反 —— 这构成一个
        以路径为顶点的二元约束系统, 用 BFS 二着色求解。

        为什么必须修: 闭合路径的 ``paths_flag`` 一律为 ``True``, 当两条闭合曲线只相交两次
        (最典型的"两圆相交")时, 双方在交叉处的取值**同时**为真 -> 双方都下压、丝带根本不
        切分。实测这正是"简单闭合几何体组合"大面积不编织的原因(冲突数 = 0 与能否编织完全
        对应: 平铺 A / Kaplan / 双三角 / X 基准全为 0, 两圆 / 三圆链为 4)。

        **当前取值本来就自洽时一个字节都不动**, 保证对既有正常输入零影响。
        """
        sequences = [self._path_crossings(i) for i in range(len(self.paths))]
        constraints: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for i, sequence in enumerate(sequences):
            for position, (point, partner) in enumerate(sequence):
                if partner == i or partner < 0 or not sequences[partner]:
                    continue
                distances = [float(np.linalg.norm(point - other)) for other, _ in sequences[partner]]
                position_j = int(np.argmin(distances))
                if distances[position_j] > 2.0 * self.offset:
                    continue  # 离得太远, 不是同一个交叉(或匹配不可靠), 不下约束
                required = 1 ^ (position % 2) ^ (position_j % 2)
                constraints[i].append((partner, required))
                constraints[partner].append((i, required))
        if not constraints:
            return

        current = list(self.paths_flag)
        if not any((current[i] ^ current[j]) != required for i, pairs in constraints.items() for j, required in pairs):
            return  # 本来就自洽, 不动

        solved = list(current)
        visited: set[int] = set()
        for start in sorted(constraints):
            if start in visited:
                continue
            colouring: dict[int, bool] = {start: current[start]}
            visited.add(start)
            queue = [start]
            consistent = True
            while queue:
                node = queue.pop()
                for neighbour, required in constraints[node]:
                    expected = bool(colouring[node] ^ bool(required))
                    if neighbour in colouring:
                        consistent = consistent and colouring[neighbour] == expected
                        continue
                    colouring[neighbour] = expected
                    visited.add(neighbour)
                    queue.append(neighbour)
            if not consistent:
                logger.debug("Interlacing: 路径 %d 所在的上下压约束不自洽, 保持既有 flag。", start)
                continue
            # 两种着色取"与现状差异更小"的那个, 尽量少动既有行为
            flips = sum(1 for index, value in colouring.items() if value != current[index])
            inverted = sum(1 for index, value in colouring.items() if (not value) != current[index])
            if inverted < flips:
                colouring = {index: not value for index, value in colouring.items()}
            for index, value in colouring.items():
                solved[index] = value
        if solved != current:
            logger.debug("Interlacing: 修正起始 flag 以满足交叉处的上下压自洽: %s -> %s", current, solved)
        self.paths_flag = solved

    def _outer_boundary_vertices(self, first: dict, second: dict) -> list[tuple]:
        """一次穿越的两条记录所连的**对方偏移线**上、两个交点之间的折线顶点。

        切口端头必须贴着对方丝带的边界, 否则(密采样时对方边界本身也跨若干段)端头直线会
        **斜穿中心线**: 实测交叉附近出现"一侧双覆盖、另一侧破洞"各一处。返回
        ``[(节点键, 坐标), ...]``(不含两个交点本身); 对方轨道/段号对不上时返回空列表。
        """
        target_a, target_b = first["tgt"], second["tgt"]
        if not isinstance(target_a, tuple) or not isinstance(target_b, tuple):
            return []
        if target_a[0] != target_b[0] or target_a[1] != target_b[1]:
            return []
        path_index, track = int(target_a[0]), int(target_a[1])
        rail = self.paths_l[path_index] if track == 1 else self.paths_r[path_index]
        num_seg = len(rail) - 1
        if num_seg < 1:
            return []
        start, end = int(target_a[2]), int(target_b[2])
        if start == end:
            return []
        if self.paths_closed[path_index]:
            forward = (end - start) % num_seg
            backward = (start - end) % num_seg
        else:
            forward, backward = end - start, start - end
        if forward <= backward:
            indices = [(start + 1 + k) % num_seg for k in range(max(forward, 0))]
        else:
            indices = [(start - k) % num_seg for k in range(max(backward, 0))]
        return [((path_index, "o", track, index), rail[index]) for index in indices]

    def _crossing_ribbon_cycles(self, i: int) -> list[np.ndarray] | None:
        """按**交叉身份**切分路径 ``i`` 的丝带(阶段 1 第三步, 只用于现行降级路径)。

        :meth:`_set_ribbons` 的逐段索引配对有一个隐含前提: "一次穿越的两个交点落在同一条
        线段的左右两条轨道上"。密采样时这两个交点沿轨相距约 ``2 * offset``(正好是对方丝带的
        宽度), 会跨 4~8 条线段 —— 逐段配对足以把整条曲线连成一片(交点处双带同绘)。契约自检
        只保证"每段左右计数相等", 抓不到这种跨段错位(实测密采样利萨如的载荷里出现 (3,3) 的
        奇数段)。

        这里改用与"段"无关的表示:

        * **穿越** = :meth:`_crossing_groups` 给出的一个中心线交叉在某条分支上的一次通过,
          它在左/右轨道上各有 2 个交点(与对方丝带的两条偏移线), 由
          :meth:`_cluster_pass_records` 按**对方轨道**配对;
        * **覆盖区间** = 这一对交点在轨道上的区间(可以跨段), 按弧长顺序处理;
        * **过/欠**仍按交替赋值: 实测自交交叉的两次通过在通过序列里的位置差恒为奇数, 所以
          交替一定自洽(`paths_flag[i]` 只决定相位); 被压的一方在覆盖区间处断开, 并在区间两端
          与另一条轨道连成丝带端头。

        返回片段多边形列表; 任何一步对不上(分组不干净 / 镜像不唯一 / 一次穿越不是 2 个交点)
        都返回 ``None``, 调用方保持降级(宁缺勿滥)。**只对现行降级路径调用**, 因此健康配置的
        输出逐字节不变。
        """
        left, _seams_l = self._rail_events(i, 1)
        right, _seams_r = self._rail_events(i, 2)
        if not left or len(left) != len(right):
            return None
        groups = self._crossing_groups(i, left, right)
        if groups is None:
            return None

        passes: list[tuple[tuple[dict, dict], tuple[dict, dict]]] = []
        for members, _raw in groups:
            for cluster in self._branch_clusters(i, members):
                corners = self._cluster_pass_records(cluster)
                if corners is None:
                    return None
                passes.append(corners)
        if not passes:
            return None
        passes.sort(key=lambda corners: min(record["arc"] for pair in corners for record in pair))

        cuts: list[tuple[tuple[dict, dict], tuple[dict, dict]]] = []
        flag = self.paths_flag[i]
        for corners in passes:
            if flag:
                cuts.append(corners)
            flag = not flag
        if not cuts:
            return None

        nodes: list[np.ndarray] = []
        seen: dict = {}

        def node(key, point) -> int:
            if key not in seen:
                seen[key] = len(nodes)
                nodes.append(np.asarray(point, dtype=float)[:2])
            return seen[key]

        graph = networkx.Graph()
        chains: dict[int, list[int]] = {}
        positions: dict[int, dict[int, int]] = {}
        for track, rail, records in ((1, self.paths_l[i], left), (2, self.paths_r[i], right)):
            num_seg = len(rail) - 1
            by_seg: dict[int, list[dict]] = defaultdict(list)
            for record in records:
                by_seg[record["seg"]].append(record)
            chain: list[int] = []
            position: dict[int, int] = {}
            for j in range(num_seg):
                chain.append(node((track, "v", j), rail[j]))
                for record in by_seg.get(j, []):
                    position[id(record)] = len(chain)
                    chain.append(node((track, "e", id(record)), record["point"]))
            if not self.paths_closed[i]:
                chain.append(node((track, "v", num_seg), rail[num_seg]))
            for first, second in zip(chain, chain[1:]):
                graph.add_edge(first, second)
            if self.paths_closed[i]:
                graph.add_edge(chain[-1], node((track, "v", 0), rail[0]))
            chains[track] = chain
            positions[track] = position

        for left_pair, right_pair in cuts:
            for track, pair in ((1, left_pair), (2, right_pair)):
                chain = chains[track]
                position = positions[track]
                start, end = position[id(pair[0])], position[id(pair[1])]
                if start > end:
                    start, end = end, start
                if end - start > len(chain) // 2:
                    # 覆盖区间跨过闭合点(原点这类"两次通过都贴着起点"的自交): 该挖的是补集
                    spans = [(0, start), (end, len(chain) - 1)]
                else:
                    spans = [(start, end)]
                for span_start, span_end in spans:
                    for k in range(span_start, span_end):
                        if graph.has_edge(chain[k], chain[k + 1]):
                            graph.remove_edge(chain[k], chain[k + 1])
            for left, right in ((left_pair[0], right_pair[0]), (left_pair[1], right_pair[1])):
                previous = node((1, "e", id(left)), left["point"])
                for key, point in self._outer_boundary_vertices(left, right):
                    current = node(key, point)
                    graph.add_edge(previous, current)
                    previous = current
                graph.add_edge(previous, node((2, "e", id(right)), right["point"]))

        cycles: list[np.ndarray] = []
        for cycle in networkx.cycle_basis(graph):
            if len(cycle) < 3:
                continue
            coords = np.array([nodes[index] for index in [*cycle, cycle[0]]])
            if not right_handed(coords):
                coords = coords[::-1]
            if len(coords) < 4 or abs(_signed_area(coords)) <= DEFAULT_ATOL:
                # 退化片段(顶点不足 / 面积为零): 说明这次切分没对上, **整体放弃**保持降级。
                # 这是"宁缺勿滥"的运行期兜底 —— 实测 PR n=6 L=3 会切出退化的零面积片段,
                # 画面 A/C/D/E 全亮(证据见 PROGRESS §3 P0-5)。
                return None
            cycles.append(coords)
        if len(cycles) != len(cuts):
            # 片段数与"该切几刀"不符, 同样视为没对上
            return None
        return cycles or None

    def _set_ribbons(self) -> None:
        """提取丝带片段多边形。

        沿每条路径的左右偏移线行进, 每经过一组交点就翻转 ``flag``: ``flag`` 为真
        时补全当前片段并封口, 为假时跳过该段(留给其它丝带覆盖)。结果写入
        :attr:`ribbons`。

        两条轨道互为平行轨, 交点应成对出现且顺序一致; 缺失的近失交点已由
        :meth:`_align_all_rails` 在求解早期补齐, 这里直接逐事件配对。

        以下路径不参与逐段编织切分:

        * 无自交点的闭合路径: 否则左右偏移线会各自闭合成一个实心圆盘, 内侧圆盘把
          孔洞整个盖死(缺陷 1), 直接产出一条"整条丝带"(外轮廓 + 内轮廓合成的环形带);
        * 派生几何不满足配对契约的路径(见 :meth:`_check_rail_geometry`): 强行按索引配对
          只会产出跨越大半个图形的错乱片段(缺陷 3)。这类路径先试一次
          :meth:`_crossing_ribbon_cycles`(按交叉身份切分, 见 :meth:`_try_crossing_weave`),
          成功就用编织片段, 否则降级成"不编织"的整条丝带(至少保证形状正确)。
        """
        self.ribbons = []
        for i, path in enumerate(self.paths):
            if self._is_simple_closed(i):
                self.ribbons.append(self._plain_band(i))
                continue
            if i in self._woven_paths:
                # 现行降级、但"按交叉身份"切分成功(阶段 1 第三步): 用编织片段
                self.ribbons.extend(self._woven_paths[i])
                continue
            if i in self._degraded_paths:
                self.ribbons.append(self._plain_band(i))
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
                # 两侧对齐的部分切分, 避免索引越界。注意: 左右交点数不等的路径已在
                # 前面整条降级, 正常情况下走不到这里。
                num_pairs = min(len(tgt_ids_l), len(tgt_ids_r))
                if num_pairs < 2:
                    continue
                if len(tgt_ids_l) != len(tgt_ids_r):
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
                if any(node not in self.d_intersections for node in cycle):
                    # 自交事件在"按交叉重归属"里改挂线段时, 另一条轨道的反向引用可能仍是旧
                    # 标识, 极端情况下会攒出缺坐标的节点。跳过该环(少一条丝带)而不是让整幅
                    # 图崩掉 —— 缺的丝带会被 C/D/E/F 检查抓出来。
                    logger.debug("Interlacing: 跳过缺少坐标的丝带环 %s", cycle)
                    continue
                coords = np.array([self.d_intersections[node] for node in [*cycle, cycle[0]]])
                if not right_handed(coords):
                    coords = coords[::-1]
                self.ribbons.append(coords)
