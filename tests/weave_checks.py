"""编织(交错)可见性模型校验工具。

``Lace`` / ``Interlacing`` 的输出是"先画 ``holes`` 再按顺序画 ``ribbons``(后者居上)"
的一叠多边形。本模块按画家顺序重建最终可见图形, 并据此检验 ``DEFECTS.md`` 第 0 节
列出的性质:

======  ==========================================================
A       holes / ribbons 顶点有限、闭合、逆时针、正面积、无重复连续顶点
C       每个真交点处恰好一方压上, 且压上方的丝带是同一条
D       沿每条曲线按弧长遍历, 过 / 欠严格交替(闭合曲线首尾相接也交替)
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


def check_crossings_pressed(interlacing, problems: list[str]) -> int:
    """检查 C: 每个真交点处恰好一条丝带压上, 且该丝带属于相交的两条路径之一。"""
    bad = 0
    for crossing in centerline_crossings(interlacing.paths):
        point = jitter(crossing["point"][None, :], 1e-3 * interlacing.offset)[0]
        count = int(coverage_count(interlacing.ribbons, point[None, :])[0])
        if count != 1:
            bad += 1
            problems.append(f"C: 交点 {crossing['i']}-{crossing['j']} 处被 {count} 条丝带覆盖")
            continue
        top = top_ribbon(interlacing.ribbons, point)
        ribbon_path = ribbon_owner_path(interlacing.ribbons[top], interlacing.paths)
        if ribbon_path not in (crossing["i"], crossing["j"]):
            bad += 1
            problems.append(f"C: 交点 {crossing['i']}-{crossing['j']} 压上方属于无关路径 {ribbon_path}")
    return bad


def check_alternation(interlacing, problems: list[str]) -> int:
    """检查 D: 沿每条曲线, 真交点处的过 / 欠严格交替(含闭合曲线的首尾相接)。"""
    bad = 0
    crossings = centerline_crossings(interlacing.paths)
    for i, path in enumerate(interlacing.paths):
        events = []
        for crossing in crossings:
            if crossing["i"] == i:
                events.append((crossing["s_i"], crossing["point"], crossing["j"]))
            elif crossing["j"] == i:
                events.append((crossing["s_j"], crossing["point"], crossing["i"]))
        if len(events) < 2:
            continue
        events.sort(key=lambda item: item[0])

        over_flags = []
        for _, point, _other in events:
            probe = jitter(point[None, :], 1e-3 * interlacing.offset)[0]
            top = top_ribbon(interlacing.ribbons, probe)
            over_flags.append(top is not None and ribbon_owner_path(interlacing.ribbons[top], interlacing.paths) == i)

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


def check_rotational_symmetry(interlacing, n: int, problems: list[str], tol: float = 1e-6) -> int:
    """检查 G: 输出在旋转 ``2π/n`` 下不变。"""
    angle = 2 * np.pi / n
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    originals = [np.asarray(p, dtype=float) for p in (*interlacing.holes, *interlacing.ribbons)]
    if not originals:
        return 0
    scale = max(np.abs(p[:, :2]).max() for p in originals)
    bad = 0
    for label, polygon in zip(["hole"] * len(interlacing.holes) + ["ribbon"] * len(interlacing.ribbons), originals):
        rotated = polygon[:, :2] @ rot.T
        area = abs(signed_area(polygon))
        centroid = rotated[:-1].mean(axis=0)
        if not any(
            abs(abs(signed_area(other)) - area) <= tol * max(1.0, area)
            and np.linalg.norm(other[:-1].mean(axis=0) - centroid) <= tol * scale
            for other in originals
        ):
            bad += 1
            problems.append(f"G: {label} 在旋转 2π/{n} 后找不到对应多边形")
    return bad


def check_picture(interlacing, *, symmetry: int | None = None, sample_step_factor: float = 0.05) -> list[str]:
    """对一整幅图运行 A/C/D/E/F(/G) 全部检查, 返回问题列表(空列表表示全部通过)。"""
    problems: list[str] = []
    check_polygons_valid(interlacing.holes, "hole", problems)
    check_polygons_valid(interlacing.ribbons, "ribbon", problems)
    check_crossings_pressed(interlacing, problems)
    check_alternation(interlacing, problems)
    check_centerline_coverage(interlacing, problems, step_factor=sample_step_factor)
    check_holes_visible(interlacing, problems)
    if symmetry:
        check_rotational_symmetry(interlacing, symmetry, problems)
    return problems
