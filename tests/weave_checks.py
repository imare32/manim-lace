"""编织(交错)可见性模型校验工具。

``Lace`` / ``Interlacing`` 的输出是"先画 ``holes`` 再按顺序画 ``ribbons``(后者居上)"
的一叠多边形。本模块按画家顺序重建最终可见图形, 并据此检验 ``DEFECTS.md`` 第 0 节
列出的性质:

======  ==========================================================
A       holes / ribbons 顶点有限、闭合、逆时针、正面积、无重复连续顶点
C       每个真交点(含自交点)处恰好一方压上: 交点本身被唯一一条丝带覆盖, 且两条通过
        曲线里恰好一侧"连续穿过"(探针距离随夹角自适应, 见 :func:`crossing_probe_distance`;
        不可判定的交点会被跳过并计入 ``stats["skipped"]``)
D       沿每条曲线按弧长遍历, 过 / 欠严格交替(闭合曲线首尾相接也交替, 自交点的两次
        通过算两个事件)
E       中心线密集采样处恰好被一条丝带覆盖(无跨带重叠、无背景破洞)
F       每个孔洞至少部分可见(未被丝带完全涂盖)
G       holes / ribbons 在旋转 ``2π/n`` 下不变
======  ==========================================================

为了便于定位问题, 每个 ``check_*`` 函数接受一个 ``problems`` 列表并把发现的
问题以字符串形式追加进去; 全部通过时不追加任何内容。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: 几何比较容差。
ATOL = 1e-9


def signed_area(coords: np.ndarray) -> float:
    """Shoelace 有符号面积(自动忽略重复的闭合点)。"""
    pts = np.asarray(coords, dtype=float)
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def points_in_polygon(polygon: np.ndarray, points: np.ndarray) -> np.ndarray:
    """向量化的命中测试(交叉数法)。

    参数:
        polygon: ``(N, 2)`` 的多边形顶点, 允许首尾点重复。
        points: ``(M, 2)`` 或 ``(2,)`` 的待测点。

    返回:
        ``(M,)`` 的布尔数组; 恰好多边形边界上的点归属未定义, 采样时应避开。
    """
    poly = np.asarray(polygon, dtype=float)
    if len(poly) > 1 and np.allclose(poly[0], poly[-1]):
        poly = poly[:-1]
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    if len(poly) < 3 or pts.size == 0:
        return np.zeros(len(pts), dtype=bool)

    x = pts[:, 0][:, None]
    y = pts[:, 1][:, None]
    x1, y1 = poly[None, :, 0], poly[None, :, 1]
    x2, y2 = np.roll(poly, -1, axis=0)[None, :, 0], np.roll(poly, -1, axis=0)[None, :, 1]

    straddle = (y1 > y) != (y2 > y)
    dy = np.where(y2 == y1, 1.0, y2 - y1)
    x_cross = (x2 - x1) * (y - y1) / dy + x1
    hits = straddle & (x < x_cross)
    return np.logical_xor.reduce(hits, axis=1)


def coverage_count(polygons: Sequence[np.ndarray], points: np.ndarray) -> np.ndarray:
    """统计每个点被多少个多边形覆盖。"""
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    counts = np.zeros(len(pts), dtype=int)
    for polygon in polygons:
        counts += points_in_polygon(polygon, pts).astype(int)
    return counts


def top_ribbon(ribbons: Sequence[np.ndarray], point: np.ndarray) -> int | None:
    """返回压在最上面的丝带下标(画家顺序中最后一个覆盖该点的多边形)。"""
    hit = None
    for k, ribbon in enumerate(ribbons):
        if points_in_polygon(ribbon, point[None, :])[0]:
            hit = k
    return hit


def point_to_polyline(points: np.ndarray, polyline: np.ndarray) -> np.ndarray:
    """每个点到折线的最近距离(按线段投影, 而非顶点)。"""
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    poly = np.asarray(polyline, dtype=float)
    if len(poly) < 2:
        return np.linalg.norm(pts - poly[0], axis=1)
    seg_a, seg_b = poly[:-1], poly[1:]
    ab = seg_b - seg_a
    ab_len2 = np.sum(ab * ab, axis=1)
    ab_len2 = np.where(ab_len2 == 0.0, 1.0, ab_len2)
    ap = pts[:, None, :] - seg_a[None, :, :]
    t = np.clip(np.sum(ap * ab[None, :, :], axis=2) / ab_len2[None, :], 0.0, 1.0)
    proj = seg_a[None, :, :] + t[:, :, None] * ab[None, :, :]
    return np.linalg.norm(pts[:, None, :] - proj, axis=2).min(axis=1)


def _resample_polyline(coords: np.ndarray, step: float) -> np.ndarray:
    """按弧长把折线重采样为点列(含首尾点)。"""
    coords = np.asarray(coords, dtype=float)
    seg_len = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = cum[-1]
    if total <= 0:
        return coords[:1]
    n = max(1, int(np.ceil(total / step)))
    targets = np.linspace(0.0, total, n + 1)
    idx = np.clip(np.searchsorted(cum, targets, side="right") - 1, 0, len(seg_len) - 1)
    frac = np.where(seg_len[idx] > 0, (targets - cum[idx]) / np.maximum(seg_len[idx], ATOL), 0.0)
    return coords[idx] + (coords[idx + 1] - coords[idx]) * frac[:, None]


def centerline_samples(paths: Sequence[np.ndarray], step: float, *, drop_ends: bool = True) -> np.ndarray:
    """对每条中心线按给定步长采样, 返回拼接后的点列。

    ``drop_ends`` 会丢弃每条路径首尾各一个采样点: 它们恰好落在丝带的封口边上,
    命中测试在边界处无定义, 会造成假阳性。
    """
    chunks = []
    for path in paths:
        resampled = _resample_polyline(path, step)
        if drop_ends and len(resampled) > 2:
            resampled = resampled[1:-1]
        chunks.append(resampled)
    if not chunks:
        return np.empty((0, 2), dtype=float)
    return np.vstack(chunks)


def jitter(points: np.ndarray, amount: float, seed: int = 20261013) -> np.ndarray:
    """给采样点加上微小扰动, 避免恰好落在多边形边界上导致命中测试失真。"""
    pts = np.atleast_2d(np.asarray(points, dtype=float))
    if len(pts) == 0:
        return pts
    rng = np.random.default_rng(seed)
    return pts + rng.uniform(-amount, amount, size=pts.shape)


def _segment_intersection(p1, p2, p3, p4, tol: float = 1e-9):
    """返回 ``(point, ua, ub)``; 不相交或平行时返回 ``None``。"""
    d1, d2 = p2 - p1, p4 - p3
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return None
    d13 = p1 - p3
    ua = (d2[0] * d13[1] - d2[1] * d13[0]) / den
    ub = (d1[0] * d13[1] - d1[1] * d13[0]) / den
    if -tol <= ua <= 1 + tol and -tol <= ub <= 1 + tol:
        return p1 + ua * d1, float(ua), float(ub)
    return None


def centerline_self_crossings(paths: Sequence[np.ndarray]) -> list[dict]:
    """求**同一条路径**上的自交点(相邻线段共享端点不算, 闭合点处绕回也不算)。

    返回:
        与 :func:`centerline_crossings` 同构的字典列表, 其中 ``i == j``(同一条曲线),
        ``s_i`` / ``s_j`` 是同一点在该曲线上的两个弧长参数(两次通过)。

    说明: :func:`centerline_crossings` 只枚举**不同路径之间**的交点, 所以对单条闭合
    曲线(玫瑰线里很常见)它是空的 —— 自交点必须单独取, 否则"编织"这件事根本没被算到。
    """
    crossings: list[dict] = []
    for index, path in enumerate(paths):
        num_seg = len(path) - 1
        if num_seg < 2:
            continue
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
        closed = bool(np.allclose(path[0], path[-1]))
        for a in range(num_seg):
            for b in range(a + 1, num_seg):
                if b == a + 1 or (closed and a == 0 and b == num_seg - 1):
                    continue  # 相邻线段共享端点
                hit = _segment_intersection(path[a], path[a + 1], path[b], path[b + 1])
                if hit is None:
                    continue
                point, ua, ub = hit
                crossings.append(
                    {
                        "i": index,
                        "j": index,
                        "point": point,
                        "s_i": float(cum[a] + ua * (cum[a + 1] - cum[a])),
                        "s_j": float(cum[b] + ub * (cum[b + 1] - cum[b])),
                    },
                )
    return crossings


def crossing_count(paths: Sequence[np.ndarray]) -> tuple[int, int]:
    """返回 ``(路径间交点数, 自交点数)`` —— 判断一幅图到底在不在编织。"""
    return len(centerline_crossings(paths)), len(centerline_self_crossings(paths))


def all_centerline_crossings(paths: Sequence[np.ndarray]) -> list[dict]:
    """路径间交点 + 自交点。

    C(交点处上下压)与 D(过欠交替)必须把**自交点**算进去: 单条闭合曲线(玫瑰线里很常见)
    的编织全部发生在自交点上, 只看路径间交点等于什么都没测。
    """
    return [*centerline_crossings(paths), *centerline_self_crossings(paths)]


def path_tangent(path: np.ndarray, arc: float) -> np.ndarray:
    """折线在弧长 ``arc`` 处的单位切向(用于在交点两侧摆探针)。"""
    coords = np.asarray(path, dtype=float)
    seg_len = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    index = int(np.clip(np.searchsorted(cum, arc, side="right") - 1, 0, len(seg_len) - 1))
    direction = coords[index + 1] - coords[index]
    norm = float(np.linalg.norm(direction))
    return direction / norm if norm > 0 else np.array([1.0, 0.0])


def centerline_crossings(paths: Sequence[np.ndarray]) -> list[dict]:
    """求不同路径中心线之间的**真交点**。

    返回:
        字典列表, 每项含 ``i`` / ``j``(路径下标, ``i < j``)、``point``(交点坐标)、
        ``s_i`` / ``s_j``(沿各自路径的弧长参数)。
    """
    crossings: list[dict] = []
    cum = [np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]) for p in paths]
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            for a in range(len(paths[i]) - 1):
                for b in range(len(paths[j]) - 1):
                    hit = _segment_intersection(paths[i][a], paths[i][a + 1], paths[j][b], paths[j][b + 1])
                    if hit is None:
                        continue
                    point, ua, ub = hit
                    crossings.append(
                        {
                            "i": i,
                            "j": j,
                            "point": point,
                            "s_i": float(cum[i][a] + ua * (cum[i][a + 1] - cum[i][a])),
                            "s_j": float(cum[j][b] + ub * (cum[j][b + 1] - cum[j][b])),
                        },
                    )
    return crossings


def ribbon_owner_path(ribbon: np.ndarray, paths: Sequence[np.ndarray]) -> int:
    """把丝带片段归属到最近的路径(按顶点到中心线折线的平均距离)。"""
    ribbon = np.asarray(ribbon, dtype=float)[:-1]
    dists = [float(np.mean(point_to_polyline(ribbon, path))) for path in paths]
    return int(np.argmin(dists))


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------


def check_polygons_valid(polygons: Sequence[np.ndarray], label: str, problems: list[str]) -> None:
    """检查 A: 顶点有限、闭合、逆时针、正面积、无重复连续顶点。"""
    for k, polygon in enumerate(polygons):
        arr = np.asarray(polygon, dtype=float)
        tag = f"{label}[{k}]"
        if arr.ndim != 2 or arr.shape[1] != 2:
            problems.append(f"A {tag}: 形状异常 {arr.shape}")
            continue
        if len(arr) < 4:
            problems.append(f"A {tag}: 顶点数不足 ({len(arr)})")
            continue
        if not np.all(np.isfinite(arr)):
            problems.append(f"A {tag}: 含非有限坐标")
            continue
        if not np.allclose(arr[0], arr[-1], atol=1e-7):
            problems.append(f"A {tag}: 不闭合 {arr[0]} != {arr[-1]}")
        if np.any(np.all(np.isclose(arr[1:], arr[:-1], atol=1e-12), axis=1)):
            problems.append(f"A {tag}: 存在重复的连续顶点")
        area = signed_area(arr)
        if area <= ATOL:
            problems.append(f"A {tag}: 面积非正或绕向错误 (signed_area={area:.3g})")


def check_centerline_coverage(interlacing, problems: list[str], step_factor: float = 0.05) -> dict:
    """检查 E: 中心线密集采样处恰好被一条丝带覆盖。"""
    step = step_factor * interlacing.offset
    points = jitter(centerline_samples(interlacing.paths, step), 1e-2 * step)
    if len(points) == 0:
        return {"samples": 0, "overlap": 0, "holes": 0}
    counts = coverage_count(interlacing.ribbons, points)
    overlap = int(np.sum(counts > 1))
    holes = int(np.sum(counts == 0))
    if overlap:
        problems.append(f"E: {overlap}/{len(points)} 个中心线采样点被多条丝带重叠覆盖")
    if holes:
        problems.append(f"E: {holes}/{len(points)} 个中心线采样点落在背景(破洞)上")
    return {"samples": len(points), "overlap": overlap, "holes": holes}


def _interior_samples(polygon: np.ndarray, n: int = 9) -> np.ndarray:
    """在多边形包围盒内取落在其内部的网格采样点。"""
    polygon = np.asarray(polygon, dtype=float)
    lo, hi = polygon[:-1].min(axis=0), polygon[:-1].max(axis=0)
    if np.any(hi - lo < ATOL):
        return np.vstack([polygon[:-1].mean(axis=0)])
    gx = np.linspace(lo[0], hi[0], n)
    gy = np.linspace(lo[1], hi[1], n)
    grid = np.array([[x, y] for x in gx for y in gy])
    return grid[points_in_polygon(polygon, grid)]


def check_holes_visible(interlacing, problems: list[str]) -> int:
    """检查 F: 每个孔洞至少有一部分未被丝带盖住。"""
    hidden = 0
    for k, hole in enumerate(interlacing.holes):
        samples = _interior_samples(hole)
        if len(samples) == 0:
            continue
        if np.all(coverage_count(interlacing.ribbons, samples) > 0):
            hidden += 1
            problems.append(f"F: 孔洞 {k} 被丝带完全涂盖")
    return hidden


def _ribbon_boxes(ribbons: Sequence[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray]]:
    """每个丝带片段的包围盒(点命中测试前的快速筛除)。"""
    boxes = []
    for ribbon in ribbons:
        coords = np.asarray(ribbon, dtype=float)[:, :2]
        boxes.append((coords.min(axis=0), coords.max(axis=0)))
    return boxes


def _covering_indices(
    ribbons: Sequence[np.ndarray],
    boxes: Sequence[tuple[np.ndarray, np.ndarray]],
    point: np.ndarray,
) -> list[int]:
    """覆盖该点的丝带下标(先用包围盒筛, 再做多边形命中测试)。"""
    hits = []
    for index, (lo, hi) in enumerate(boxes):
        if np.any(point < lo) or np.any(point > hi):
            continue
        if points_in_polygon(ribbons[index], point[None, :])[0]:
            hits.append(index)
    return hits


#: 探针距离的默认倍数(见 :func:`crossing_probe_distance`)。
PROBE_FACTOR = 1.5
#: 探针与最近邻交点的最大间距占比: 更远就会同时探到下一个交叉, 判定不再可信。
PROBE_SAFE_FRACTION = 0.45


def crossing_probe_distance(
    interlacing,
    crossing: dict,
    probe_factor: float = PROBE_FACTOR,
    others: np.ndarray | None = None,
) -> tuple[float, bool]:
    """交点两侧探针的距离, 以及这个距离是否可用。

    压上方丝带沿**被压方切线方向**覆盖的长度是 ``offset / |sinθ|``(θ = 交叉夹角), 探针
    必须落在这段之外, 否则整个探针窗口都被压上方盖住, 两侧都会"看起来连续"。实测这正是
    浅角交叉的系统性假阳性: θ ≲ 42°(即 ``1/1.5``)时必然发生 —— PA n=12 L2 的 24 个交点里
    12 个是 20°/30°, 全部被误报成"没有编织", 而放大渲染显示它们是标准编织。

    返回 ``(distance, reliable)``: ``distance`` 取 ``probe_factor × offset / |sinθ|``;
    ``reliable=False`` 表示该距离会越过最近的另一个交点(或交叉近乎平行), 这个交点的判定
    不可信 —— 调用方应当**跳过**它, 而不是把它记成缺陷。
    """
    offset = interlacing.offset
    t_i = path_tangent(interlacing.paths[crossing["i"]], crossing["s_i"])
    t_j = path_tangent(interlacing.paths[crossing["j"]], crossing["s_j"])
    sin_theta = max(float(np.abs(t_i[0] * t_j[1] - t_i[1] * t_j[0])), 1e-3)
    distance = probe_factor * offset / sin_theta
    if others is not None and len(others):
        gaps = np.linalg.norm(np.asarray(others, dtype=float) - crossing["point"], axis=1)
        gaps = gaps[gaps > 1e-12]
        if len(gaps):
            limit = PROBE_SAFE_FRACTION * float(gaps.min())
            if distance > limit:
                return limit, False
    return distance, True


def crossing_pass_flags(
    interlacing,
    crossing: dict,
    probe_factor: float = PROBE_FACTOR,
    others: np.ndarray | None = None,
) -> tuple[list[bool], bool, bool]:
    """两条通过曲线各自是否"**连续穿过**"该交点, 探针是否干净, 以及判定是否可信。

    返回 ``(flags, clean, reliable)``:

    * ``flags``: 两条曲线各自的"压上"标志(``True`` = 连续穿过);
    * ``clean``: 每个探针都恰好被一条丝带覆盖(既不重叠也不落空);
    * ``reliable``: 探针距离没有越过相邻交点与近平行区(``False`` 时应跳过该交点)。

    判据(与画家顺序无关): 沿这一侧的**中心线方向**取 5 个探针 —— 交点本身, 以及离交点
    ``d`` / ``1.25d`` 的两对(``d`` 随夹角自适应, 见 :func:`crossing_probe_distance`)。
    若**存在同一条丝带**覆盖全部探针, 说明这一侧的带子连续穿过交点(压上方); 被压方的
    带子会在交点前被剪断: 远端探针落在它自己的片段上, 而**交点本身**已经被压上方盖住,
    于是 5 个探针的公共元素为空。

    ⚠️ **交点本身这个探针不能省**: 被压方的片段常常仍然是**同一个多边形**(比如两圆相交
    时黄带只在中间断一小段, 两截由环的另一侧连通), 只看远端探针会把"断开的带子"判成
    连续。远端距离也不能小(浅角会落进压上方带子里), 见 §缺陷 7。
    """
    ribbons = interlacing.ribbons
    boxes = _ribbon_boxes(ribbons)
    offset = interlacing.offset
    distance, reliable = crossing_probe_distance(interlacing, crossing, probe_factor, others)
    flags: list[bool] = []
    clean = True
    for path_index, arc in ((crossing["i"], crossing["s_i"]), (crossing["j"], crossing["s_j"])):
        direction = path_tangent(interlacing.paths[path_index], arc)
        covers: list[set[int]] = []
        for factor in (-1.25, -1.0, 0.0, 1.0, 1.25):
            sample = crossing["point"] + factor * distance * direction
            hits = _covering_indices(ribbons, boxes, jitter(sample[None, :], 1e-3 * offset)[0])
            if len(hits) != 1:
                clean = False
            covers.append(set(hits))
        flags.append(bool(set.intersection(*covers)) if all(covers) else False)
    return flags, clean, reliable


def check_crossings_pressed(
    interlacing,
    problems: list[str],
    probe_factor: float = PROBE_FACTOR,
    stats: dict | None = None,
) -> int:
    """检查 C: 每个真交点(含自交点)处**恰好一方压上**, 压上方连续穿过、被压方断开。

    要求:

    * **交点本身**恰好被 1 条丝带覆盖(压上方), 且该丝带属于相交的两条路径之一;
    * 两侧的探针都只被一条丝带覆盖(既不重叠也不落空);
    * 两条通过曲线里**恰好一侧连续穿过**(见 :func:`crossing_pass_flags`)。

    探针距离越过相邻交点(浅角/近平行)的交点**不可判定**, 会被跳过并计入
    ``stats["skipped"]``(通过 ``stats`` 传出), 而不是记成缺陷。
    """
    bad = 0
    ribbons = interlacing.ribbons
    paths = interlacing.paths
    offset = interlacing.offset
    crossings = all_centerline_crossings(paths)
    points = np.array([crossing["point"] for crossing in crossings]) if crossings else np.zeros((0, 2))
    if stats is not None:
        stats["crossings"] = len(crossings)
        stats["skipped"] = 0
    for crossing in crossings:
        tag = f"{crossing['i']}-{crossing['j']}"
        point = jitter(crossing["point"][None, :], 1e-3 * offset)[0]
        count = int(coverage_count(ribbons, point[None, :])[0])
        if count != 1:
            bad += 1
            problems.append(f"C: 交点 {tag} 处被 {count} 条丝带覆盖")
            continue
        top = top_ribbon(ribbons, point)
        if top is None or ribbon_owner_path(ribbons[top], paths) not in (crossing["i"], crossing["j"]):
            bad += 1
            problems.append(f"C: 交点 {tag} 压上方不属于相交的两条路径")
            continue
        flags, clean, reliable = crossing_pass_flags(interlacing, crossing, probe_factor, points)
        if not reliable:
            if stats is not None:
                stats["skipped"] += 1
            continue
        if not clean:
            bad += 1
            problems.append(f"C: 交点 {tag} 两侧探针没有被恰好一条丝带覆盖")
            continue
        if sum(flags) != 1:
            bad += 1
            problems.append(f"C: 交点 {tag} 处压上/被压关系不成立(连续穿过的一侧有 {sum(flags)} 个, 应为 1)")
    return bad


def check_alternation(
    interlacing,
    problems: list[str],
    probe_factor: float = PROBE_FACTOR,
    stats: dict | None = None,
) -> int:
    """检查 D: 沿每条曲线, 真交点处的过 / 欠严格交替(含闭合曲线的首尾相接)。

    **自交点算两个事件**(同一条曲线在 ``s_i`` / ``s_j`` 两次通过同一点), 否则玫瑰线这类
    单条闭合曲线的 D 检查是空跑 —— 它们的编织全都发生在自交点上。

    "过 / 欠"取自 :func:`crossing_pass_flags`(该侧是否**连续穿过**交点), 而不是"最上层
    丝带属于哪条路径": 自交点上两条通过属于同一条路径, 后者根本区分不出来。

    探针不可信(浅角/近平行/相邻交点太近)的交点**不参与**交替序列, 计入
    ``stats["skipped"]``。
    """
    bad = 0
    crossings = all_centerline_crossings(interlacing.paths)
    points = np.array([crossing["point"] for crossing in crossings]) if crossings else np.zeros((0, 2))
    flags_by_crossing: list[list[bool] | None] = []
    skipped = 0
    for crossing in crossings:
        flags, _clean, reliable = crossing_pass_flags(interlacing, crossing, probe_factor, points)
        flags_by_crossing.append(flags if reliable else None)
        skipped += 0 if reliable else 1
    if stats is not None:
        stats["crossings"] = len(crossings)
        stats["skipped"] = skipped

    for i, path in enumerate(interlacing.paths):
        events: list[tuple[float, bool]] = []
        for crossing, flags in zip(crossings, flags_by_crossing, strict=False):
            if flags is None:
                continue
            if crossing["i"] == i:
                events.append((crossing["s_i"], flags[0]))
            if crossing["j"] == i:  # 自交点(i == j)会因此算两次通过, 正是需要的
                events.append((crossing["s_j"], flags[1]))
        if len(events) < 2:
            continue
        events.sort(key=lambda item: item[0])
        over_flags = [flag for _arc, flag in events]

        closed = bool(np.allclose(path[0], path[-1]))
        pairs = list(zip(over_flags, over_flags[1:]))
        if closed and len(over_flags) > 1:
            pairs.append((over_flags[-1], over_flags[0]))
        for a, b in pairs:
            if a == b:
                bad += 1
                problems.append(f"D: 路径 {i} 的相邻真交点过/欠未交替")
                break
    return bad


def _area_centroid(polygon: np.ndarray) -> np.ndarray:
    """多边形**面积质心**(不是顶点平均 —— 后者对"环形带 + 狭缝"这类顶点分布不均的形状没有意义,
    旋转后会对不上)。退化多边形回退到顶点平均。"""
    pts = np.asarray(polygon, dtype=float)[:, :2]
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return pts.mean(axis=0) if len(pts) else np.zeros(2)
    x, y = pts[:, 0], pts[:, 1]
    next_x, next_y = np.roll(x, -1), np.roll(y, -1)
    cross = x * next_y - next_x * y
    area = float(cross.sum()) / 2.0
    if abs(area) < ATOL:
        return pts.mean(axis=0)
    centroid = np.array([float(((x + next_x) * cross).sum()), float(((y + next_y) * cross).sum())]) / (6.0 * area)
    return centroid


def visible_layer_labels(interlacing, points: np.ndarray) -> np.ndarray:
    """采样点的**可见图层**: ``0`` = 背景, ``1`` = 只见孔洞, ``2`` = 被丝带压上。

    按画家顺序: ``holes`` 先画、``ribbons`` 后画(后者居上), 所以只要有丝带覆盖就是 ``2``。
    """
    points = np.atleast_2d(np.asarray(points, dtype=float))
    labels = np.zeros(len(points), dtype=int)
    if interlacing.holes:
        labels[coverage_count(interlacing.holes, points) > 0] = 1
    if interlacing.ribbons:
        labels[coverage_count(interlacing.ribbons, points) > 0] = 2
    return labels


def check_rotational_symmetry(
    interlacing,
    n: int,
    problems: list[str],
    resolution: int = 64,
    max_mismatch_fraction: float = 0.02,
) -> int:
    """检查 G: 输出在旋转 ``2π/n`` 下**看起来**不变。

    判据是"可见图层光栅对比": 在图形范围内取 ``resolution × resolution`` 个采样点, 每个点
    分类成 背景 / 只见孔洞 / 有丝带压上; 整体旋转 ``2π/n`` 后重新分类, 不一致的采样点比例
    超过 ``max_mismatch_fraction`` 就判失败。

    为什么不用"逐多边形一一对应"或"同层区域覆盖": 同一块可见区域被拆成几个多边形、以及
    **被压上方盖住的那部分**划给谁, 都是任意的分解方式 —— 实测 ``PA n=12 L2`` 的 24 条丝带里
    有 4 条旋转后落在"没有任何丝带"的位置(它们被压在别的丝带下面), 但**可见画面**旋转后
    逐点一致(0/4516 不一致)。逐多边形判定会把这种**分解差异**误报成"不对称"。
    """
    polygons = [*interlacing.holes, *interlacing.ribbons]
    if not polygons:
        return 0
    lo = np.min([np.asarray(p, dtype=float)[:, :2].min(axis=0) for p in polygons], axis=0)
    hi = np.max([np.asarray(p, dtype=float)[:, :2].max(axis=0) for p in polygons], axis=0)
    if np.any(hi - lo < ATOL):
        return 0
    xs = np.linspace(lo[0], hi[0], resolution)
    ys = np.linspace(lo[1], hi[1], resolution)
    grid = np.array([[x, y] for x in xs for y in ys])
    angle = 2 * np.pi / n
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])

    before = visible_layer_labels(interlacing, grid)
    after = visible_layer_labels(interlacing, grid @ rot.T)
    relevant = (before > 0) | (after > 0)
    total = int(relevant.sum())
    if total == 0:
        return 0
    mismatched = int(np.sum(before[relevant] != after[relevant]))
    if mismatched <= max_mismatch_fraction * total:
        return 0
    problems.append(
        f"G: 旋转 2π/{n} 后可见图层不一致({mismatched}/{total} 个采样点, "
        f"{mismatched / total:.1%} > 容差 {max_mismatch_fraction:.0%})",
    )
    return 1


def check_picture(
    interlacing,
    *,
    symmetry: int | None = None,
    sample_step_factor: float = 0.05,
    stats: dict | None = None,
) -> list[str]:
    """对一整幅图运行 A/C/D/E/F(/G) 全部检查, 返回问题列表(空列表表示全部通过)。

    ``stats``(可选)会填入 ``crossings`` / ``skipped``: 交点总数, 以及因为浅角/近平行/
    相邻交点过近而**不可判定**、被跳过的交点数。
    """
    problems: list[str] = []
    check_polygons_valid(interlacing.holes, "hole", problems)
    check_polygons_valid(interlacing.ribbons, "ribbon", problems)
    check_crossings_pressed(interlacing, problems, stats=stats)
    check_alternation(interlacing, problems, stats=stats)
    check_centerline_coverage(interlacing, problems, step_factor=sample_step_factor)
    check_holes_visible(interlacing, problems)
    if symmetry:
        check_rotational_symmetry(interlacing, symmetry, problems)
    return problems
