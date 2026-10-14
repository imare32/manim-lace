"""测试共享的路径构造工具与几何断言辅助。

玫瑰线(`manim_lace.rosette`)是**可选模块**: 下面用到它的构造器会先
``pytest.importorskip`` —— 将来把它拆成独立包后, 核心的编织测试仍然可以单独跑。
"""

from __future__ import annotations

import numpy as np
import pytest


def square_ring(size: float = 3.0, clockwise: bool = False) -> np.ndarray:
    """返回首尾闭合的正方形路径(默认逆时针)。"""
    corners = [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]
    if clockwise:
        corners = corners[::-1]
    corners.append(corners[0])
    return np.array(corners, dtype=float)


def square_segments(size: float = 3.0, clockwise: bool = False) -> list[np.ndarray]:
    """把正方形拆成 4 条独立线段, 用于测试 :func:`merge_paths`。"""
    ring = square_ring(size, clockwise)
    return [ring[i : i + 2] for i in range(len(ring) - 1)]


def lattice_paths(n: int = 3, spacing: float = 1.0) -> list[np.ndarray]:
    """``n×n`` 正交线阵。

    四角端点重合, 因此外圈会被 :func:`merge_paths` 合并成一个闭合环, 其余两条
    线保持开放。该输入会让同一条线段左右偏移线的交点数不相等, 是回归用例。
    """
    end = (n - 1) * spacing
    paths = []
    for i in range(n):
        paths.append(np.array([[0.0, i * spacing], [end, i * spacing]]))
        paths.append(np.array([[i * spacing, 0.0], [i * spacing, end]]))
    return paths


def weave_grid_paths(n: int = 4, spacing: float = 1.0, overhang: float = 0.5) -> list[np.ndarray]:
    """``n×n`` 编织网格。

    每条线都伸出网格外(``overhang``), 因此端点互不重合, 不会被合并。
    """
    end = (n - 1) * spacing
    paths = []
    for i in range(n):
        paths.append(np.array([[-overhang, i * spacing], [end + overhang, i * spacing]]))
        paths.append(np.array([[i * spacing, -overhang], [i * spacing, end + overhang]]))
    return paths


def crossing_lines(half_length: float = 2.0) -> list[np.ndarray]:
    """一横一竖两条交叉线。"""
    return [
        np.array([[-half_length, 0.0], [half_length, 0.0]]),
        np.array([[0.0, -half_length], [0.0, half_length]]),
    ]


def ring_path(sides: int = 65, radius: float = 2.0) -> np.ndarray:
    """返回闭合的正 ``sides`` 边形(近似圆环), 首尾点重复。"""
    angles = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    coords = np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])
    return np.vstack([coords, coords[:1]])


def lissajous_paths(step: float = 0.01) -> list[np.ndarray]:
    """密采样的利萨如曲线 ``(sin 2t, sin 3t)``: 一条自交 7 次的闭合路径。

    这是"密采样自交曲线"的最小输入(缺陷报告的 d5/d6)。``step`` 是**折线步长**(不是参数
    步长), 默认 ``0.01`` —— 与 ``offset=0.05`` 的丝带宽度之比约 ``0.3``: 一次自交的两个交点
    沿轨相距约 ``2 * offset``, 会跨 4~8 条线段, 逐段索引配对的模型不再成立。
    """
    t = np.arange(0.0, 2.0 * np.pi, step)
    coords = np.column_stack([np.sin(2.0 * t), np.sin(3.0 * t)])
    return [np.vstack([coords, coords[:1]])]


def ring_with_collinear_seam(size: float = 3.0) -> np.ndarray:
    """返回首尾边共线的闭合正方形(起点落在底边中点)。

    闭合点处的前后两条边共线, 属于"绕回型"冗余顶点, 是缺陷 2 的最小复现输入。
    """
    corners = [(size / 2.0, 0.0), (size, 0.0), (size, size), (0.0, size), (0.0, 0.0)]
    corners.append(corners[0])
    return np.array(corners, dtype=float)


def _mobject_paths(mobject) -> list[np.ndarray]:
    """按库的公开转换(`mobject_paths`)把对象掰成路径, 让测试走与 `Lace` 相同的输入通道。"""
    from manim_lace.lace import mobject_paths

    return [np.asarray(path, dtype=float) for path in mobject_paths(mobject)]


def level_zero_rosette_paths(n: int = 7, star_type: str = "PO") -> list[np.ndarray]:
    """返回 ``level=0`` 玫瑰线的全部子路径(花瓣互不相交, 无真实交点)。"""
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    from manim_lace import StarRosette

    rosette = StarRosette(n, 0, star_type)
    return [path for member in rosette.family_members_with_points() for path in _mobject_paths(member)]


def rosette_paths(n: int, level: int, star_type: str) -> tuple[list[np.ndarray], float]:
    """返回玫瑰线的子路径与按 ``r_max`` 1.5% 取定的丝带半宽。"""
    pytest.importorskip("manim_lace.rosette", reason="玫瑰线是可选模块")
    from manim_lace import StarRosette

    rosette = StarRosette(n, level, star_type)
    paths = [path for member in rosette.family_members_with_points() for path in _mobject_paths(member)]
    r_max = max(float(np.linalg.norm(path[:, :2], axis=1).max()) for path in paths)
    return paths, 0.015 * r_max


def polygon_area(coords: np.ndarray) -> float:
    """Shoelace 面积(无符号), 自动忽略重复的闭合点。"""
    pts = coords[:-1] if np.allclose(coords[0], coords[-1]) else coords
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def assert_closed_polygons(polygons, min_vertices: int = 3) -> None:
    """断言一组多边形都是闭合、有限且顶点数达标的多边形。"""
    assert len(polygons) > 0
    for polygon in polygons:
        arr = np.asarray(polygon)
        assert arr.ndim == 2, f"expected a 2D array, got shape {arr.shape}"
        assert arr.shape[1] == 2, f"expected 2D coordinates, got shape {arr.shape}"
        assert len(arr) >= min_vertices + 1, f"expected at least {min_vertices + 1} points, got {len(arr)}"
        assert np.all(np.isfinite(arr))
        np.testing.assert_allclose(arr[0], arr[-1])


def assert_is_counter_clockwise(polygons) -> None:
    """断言一组多边形的顶点绕向均为逆时针。"""
    for polygon in polygons:
        arr = np.asarray(polygon)
        x, y = arr[:-1, 0], arr[:-1, 1]
        signed_area = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
        assert signed_area > 0, f"polygon is not counter-clockwise:\n{arr}"
