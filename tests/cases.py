"""类二/类三/类四测试矩阵的**输入定义**(纯 numpy, 不依赖 manim 与玫瑰线)。

这三个类别原先只存在于 `media/` 的渲染矩阵里(`media/_review/campaign_simple.py` +
`media/lace_tests/{closed,mixed,open}/`), 渲染产物不入库 —— 于是"哪些配置合格、哪些必须
诚实降级"这条结论一旦有人改动几何层就可能悄悄失效。本模块把它们搬到 `tests/` 里,
由 `tests/test_cases.py` 固化成回归(PROGRESS §3 P1-7)。

判定与渲染必须**同尺度**:平铺/内接这类配置的退化对浮点极敏感, 所以
:func:`scaled` 与渲染管线(`media/_review/acceptance_render.py` 的
``RADIUS`` / ``OFFSET_FACTOR``)一字不差地把输入缩放到同一尺寸再求解。

刻意混入三类"通用输入"形态(与渲染矩阵一致), 用来量"降级机制"的真实影响面:

* **横穿**: 曲线正常相交 —— 应当合格;
* **相切 / 共顶点 / 共线共边**: 预期被输入校验或派生几何自检挡下(诚实降级);
* **超出当前判据**: 星形多边形自交、奇环(三圆链)这类"交替织法"本身无解/未覆盖的配置,
  门禁不收但也不该被静默当成合格。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from tests.helpers import lattice_paths, weave_grid_paths

#: 渲染管线的画幅半径与丝带半宽比例(`media/_review/acceptance_render.py` 的
#: ``RADIUS`` / ``OFFSET_FACTOR``): 判定与渲染必须用相同的缩放与偏移。
RADIUS = 2.5
OFFSET_FACTOR = 0.015


# --------------------------------------------------------------------------- 形状
def circle(cx: float, cy: float, radius: float, sides: int = 64, phase_deg: float = 0.0) -> np.ndarray:
    """正 ``sides`` 边形近似圆(首尾闭合); ``phase_deg`` 用来避开"直线正好穿过顶点"。"""
    angles = np.deg2rad(phase_deg) + np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    points = np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
    return np.vstack([points, points[:1]])


def rect(cx: float, cy: float, width: float, height: float, phase_deg: float = 0.0) -> np.ndarray:
    """矩形(可绕自身中心旋转 ``phase_deg``), 首尾闭合。"""
    half_w, half_h = width / 2.0, height / 2.0
    points = np.array([[-half_w, -half_h], [half_w, -half_h], [half_w, half_h], [-half_w, half_h]], dtype=float)
    if phase_deg:
        angle = np.deg2rad(phase_deg)
        rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        points = points @ rot.T
    points = points + np.array([cx, cy])
    return np.vstack([points, points[:1]])


def polygon(cx: float, cy: float, n: int, radius: float, phase_deg: float = 0.0) -> np.ndarray:
    """正 ``n`` 边形, 首尾闭合。"""
    angles = np.deg2rad(phase_deg) + np.arange(n) * 2.0 * np.pi / n
    points = np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
    return np.vstack([points, points[:1]])


def star_polygon(cx: float, cy: float, n: int, step: int, radius: float, phase_deg: float = 0.0) -> np.ndarray:
    """星形多边形 ``{n/step}``(顶点按步长跳接, 因此**自交**), 首尾闭合。"""
    order = [(index * step) % n for index in range(n)]
    angles = np.deg2rad(phase_deg) + np.array(order) * 2.0 * np.pi / n
    points = np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
    return np.vstack([points, points[:1]])


def line(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """开放线段。"""
    return np.array([[x0, y0], [x1, y1]], dtype=float)


def zigzag(x0: float, x1: float, y_center: float, amplitude: float, turns: int, phase: float = 0.0) -> np.ndarray:
    """开放折线: 沿 x 方向来回折 ``turns`` 次。"""
    xs = np.linspace(x0, x1, 2 * turns + 1)
    ys = y_center + amplitude * np.array([phase if index % 2 == 0 else -phase for index in range(len(xs))])
    return np.column_stack([xs, ys])


def sine_wave(x0: float, x1: float, y_center: float, amplitude: float, waves: float, samples: int = 64) -> np.ndarray:
    """开放正弦折线。"""
    xs = np.linspace(x0, x1, samples)
    ys = y_center + amplitude * np.sin(2.0 * np.pi * waves * (xs - x0) / (x1 - x0))
    return np.column_stack([xs, ys])


def angle_line(cx: float, cy: float, angle_deg: float, half_length: float) -> np.ndarray:
    """经过 ``(cx, cy)``、倾角 ``angle_deg`` 的开放线段。"""
    angle = np.deg2rad(angle_deg)
    direction = np.array([np.cos(angle), np.sin(angle)]) * half_length
    return np.array([[cx - direction[0], cy - direction[1]], [cx + direction[0], cy + direction[1]]])


def scaled(paths: Sequence[np.ndarray]) -> tuple[list[np.ndarray], float]:
    """按渲染口径把输入缩放(最大半径 → :data:`RADIUS`)并给出丝带半宽。"""
    r_max = max(float(np.linalg.norm(np.asarray(path, dtype=float)[:, :2], axis=1).max()) for path in paths)
    scale = RADIUS / r_max
    return [np.asarray(path, dtype=float)[:, :2] * scale for path in paths], OFFSET_FACTOR * RADIUS


# --------------------------------------------------------------------------- 候选
Case = tuple[str, str, list[np.ndarray]]

#: **类二**: 闭合 × 闭合 —— 圆 / 矩形 / 正多边形 / 星形多边形的嵌套与相交。
CLOSED_CASES: list[Case] = [
    ("Closed_two_circles", "两圆横穿", [circle(-0.8, 0.0, 1.5), circle(0.8, 0.0, 1.5)]),
    ("Closed_concentric_rings", "同心双圆(无交点)", [circle(0.0, 0.0, 2.1), circle(0.0, 0.0, 1.2)]),
    ("Closed_square_rot45", "正方形 + 旋转45°正方形", [rect(0.0, 0.0, 3.0, 3.0), rect(0.0, 0.0, 3.0, 3.0, 45.0)]),
    ("Closed_hexagon_rot30", "正六边形 + 旋转30°", [polygon(0.0, 0.0, 6, 1.9), polygon(0.0, 0.0, 6, 1.9, 30.0)]),
    (
        "Closed_pentagram_plus_pentagon",
        "正五边形 + {5/2} 星",
        [polygon(0.0, 0.0, 5, 1.5), star_polygon(0.0, 0.0, 5, 2, 1.95)],
    ),
    ("Closed_two_triangles", "正三角形 + 倒三角形", [polygon(0.0, 0.0, 3, 1.9), polygon(0.0, 0.0, 3, 1.9, 60.0)]),
    (
        "Closed_hexagon_plus_star_of_david",
        "正六边形 + 内接双三角(伸出)",
        [
            polygon(0.0, 0.0, 6, 1.9),
            polygon(0.0, 0.0, 3, 2.4),
            polygon(0.0, 0.0, 3, 2.4, 60.0),
        ],
    ),
    (
        "Closed_nested_three",
        "三重嵌套(方 3.0 / 圆 1.6 / 旋转方 2.4)",
        [
            rect(0.0, 0.0, 3.0, 3.0),
            circle(0.0, 0.0, 1.6),
            rect(0.0, 0.0, 2.4, 2.4, 45.0),
        ],
    ),
    ("Closed_star7_3_plus_circle", "{7/3} 星 + 外接圆", [star_polygon(0.0, 0.0, 7, 3, 1.9), circle(0.0, 0.0, 2.2)]),
    (
        "Closed_three_circles_chain",
        "三圆链(两两相交)",
        [
            circle(0.0, 1.0, 1.4),
            circle(-1.2, -0.8, 1.4),
            circle(1.2, -0.8, 1.4),
        ],
    ),
    ("Closed_square_inscribed_circle", "正方形 + 内接圆(四切点)", [rect(0.0, 0.0, 3.0, 3.0), circle(0.0, 0.0, 1.5)]),
    (
        "Closed_square_inscribed_rot_square",
        "正方形 + 内接旋转正方形(四切点)",
        [
            rect(0.0, 0.0, 3.0, 3.0),
            rect(0.0, 0.0, 3.0 / np.sqrt(2.0), 3.0 / np.sqrt(2.0), 45.0),
        ],
    ),
    ("Closed_two_squares_shared_edge", "两正方形共边(共线重叠)", [rect(-1.0, 0.0, 2.0, 2.0), rect(1.0, 0.0, 2.0, 2.0)]),
    (
        "Closed_triangle_hexagon_shared_vertices",
        "三角形 + 六边形(共 6 顶点)",
        [
            polygon(0.0, 0.0, 3, 1.9),
            polygon(0.0, 0.0, 3, 1.9, 60.0),
            polygon(0.0, 0.0, 6, 1.9),
        ],
    ),
]

#: **类三**: 闭合 + 开放 —— 闭合环穿开放折线 / 弦 / 斜线。
MIXED_CASES: list[Case] = [
    # 圆的相位偏半格(64 边形偏 2.8125°), 避免直线正好穿过多边形顶点 -> 假"多线共点"
    (
        "Mixed_circle_plus_line",
        "圆 + 一条穿过的直线",
        [circle(0.0, 0.0, 1.8, phase_deg=2.8125), line(-2.6, 0.0, 2.6, 0.0)],
    ),
    (
        "Mixed_circle_plus_two_chords",
        "圆 + 两条弦",
        [
            circle(0.0, 0.0, 1.8, phase_deg=2.8125),
            line(-1.9, 0.7, 1.9, 0.7),
            line(-1.9, -0.8, 1.9, -0.8),
        ],
    ),
    (
        "Mixed_circle_plus_three_lines",
        "圆 + 三条平行线",
        [
            circle(0.0, 0.0, 1.9, phase_deg=2.8125),
            line(-2.5, 0.6, 2.5, 0.6),
            line(-2.5, 0.0, 2.5, 0.0),
            line(-2.5, -0.6, 2.5, -0.6),
        ],
    ),
    (
        "Mixed_two_rings_plus_line",
        "同心双圆 + 一条穿过的斜线",
        [
            circle(0.0, 0.0, 2.1, phase_deg=2.8125),
            circle(0.0, 0.0, 1.1, phase_deg=2.8125),
            angle_line(0.0, 0.0, 30.0, 2.5),
        ],
    ),
    (
        "Mixed_square_plus_skew_lines",
        "正方形 + 两条 45° 斜线(不穿角点)",
        [
            rect(0.0, 0.0, 3.2, 3.2),
            line(-1.6, -0.6, 0.6, 1.6),
            line(-0.6, -1.6, 1.6, 0.6),
        ],
    ),
    (
        "Mixed_hexagon_plus_lines",
        "正六边形 + 三条平行线",
        [
            polygon(0.0, 0.0, 6, 1.9, 30.0),
            line(-2.4, 1.1, 2.4, 1.1),
            line(-2.4, 0.0, 2.4, 0.0),
            line(-2.4, -1.1, 2.4, -1.1),
        ],
    ),
    (
        "Mixed_ring_plus_zigzag",
        "圆 + 一条折线穿过",
        [
            circle(0.0, 0.0, 1.7, phase_deg=2.8125),
            zigzag(-2.6, 2.6, 0.0, 1.0, 3, 1.0),
        ],
    ),
    (
        "Mixed_triangle_plus_lines",
        "正三角形 + 三条穿过的直线",
        [
            polygon(0.0, 0.0, 3, 1.7, 30.0),
            line(-2.4, 0.9, 2.4, 0.9),
            line(-2.4, -0.9, 2.4, -0.9),
            line(-2.4, 0.0, 2.4, 0.0),
        ],
    ),
    (
        "Mixed_touching_circle_plus_line",
        "圆 + 与它相切的直线(预期退化)",
        [circle(0.0, 0.0, 1.5), line(-2.5, 1.5, 2.5, 1.5)],
    ),
    (
        "Mixed_ring_plus_crossing_chords",
        "圆 + 两条相交的长弦",
        [
            circle(0.0, 0.0, 1.8, phase_deg=2.8125),
            angle_line(-0.5, -0.5, 35.0, 2.6),
            angle_line(0.5, -0.5, -35.0, 2.6),
        ],
    ),
]

#: **类四**: 开放 + 开放 —— 网格线、斜线阵、折线与编织辫。
OPEN_CASES: list[Case] = [
    ("Open_weave_grid3", "3×3 编织网格(带外伸)", list(weave_grid_paths(3))),
    ("Open_weave_grid4", "4×4 编织网格", list(weave_grid_paths(4))),
    ("Open_weave_grid5", "5×5 编织网格", list(weave_grid_paths(5))),
    ("Open_lattice3", "3×3 线阵(四角重合, 外圈合并成环)", list(lattice_paths(3))),
    (
        "Open_skew_lattice",
        "水平线阵 × 60° 斜线阵",
        [
            *[line(-2.6, y, 2.6, y) for y in (-0.9, 0.0, 0.9)],
            *[angle_line(0.0, y, 60.0, 2.6) for y in (-0.9, 0.0, 0.9)],
        ],
    ),
    (
        "Open_diagonal_lattice",
        "±45° 斜线阵",
        [
            *[angle_line(0.0, y, 45.0, 2.6) for y in (-1.2, 0.0, 1.2)],
            *[angle_line(0.0, y, -45.0, 2.6) for y in (-1.2, 0.0, 1.2)],
        ],
    ),
    (
        "Open_braid_three",
        "三条正弦线互穿(辫)",
        [
            sine_wave(-2.6, 2.6, -0.9, 1.3, 1.0),
            sine_wave(-2.6, 2.6, 0.0, 1.3, 1.5),
            sine_wave(-2.6, 2.6, 0.9, 1.3, 2.0),
        ],
    ),
    ("Open_zigzag_pair", "两条折线互穿", [zigzag(-2.6, 2.6, -0.5, 1.0, 3, 1.0), zigzag(-2.6, 2.6, 0.5, 1.0, 3, -1.0)]),
    (
        "Open_two_waves",
        "两条相位相反的正弦线",
        [
            sine_wave(-2.6, 2.6, 0.0, 1.2, 2.0),
            sine_wave(-2.6, 2.6, 0.0, -1.2, 2.0),
        ],
    ),
    (
        "Open_crossing_pairs",
        "三对交叉线(共享格点)",
        [
            *[line(-2.4, y, 2.4, y) for y in (-1.2, 0.0, 1.2)],
            *[line(x, -1.8, x, 1.8) for x in (-1.2, 0.0, 1.2)],
        ],
    ),
    ("Open_fan_concurrent", "同点并发线束(预期退化)", [angle_line(0.0, -1.5, a, 2.6) for a in (60.0, 90.0, 120.0)]),
    (
        "Open_grid_plus_diagonals",
        "3×3 网格 + 两条对角线",
        [
            *[line(-2.4, y, 2.4, y) for y in (-0.8, 0.0, 0.8)],
            *[line(x, -1.6, x, 1.6) for x in (-1.2, 0.0, 1.2)],
            line(-2.4, -1.6, 2.4, 1.6),
            line(-2.4, 1.6, 2.4, -1.6),
        ],
    ),
]

CATEGORIES: dict[str, list[Case]] = {
    "closed": CLOSED_CASES,
    "mixed": MIXED_CASES,
    "open": OPEN_CASES,
}


def by_name(name: str) -> Case:
    """按场景名取用例(名字与渲染矩阵里的一致)。"""
    for cases in CATEGORIES.values():
        for case in cases:
            if case[0] == name:
                return case
    raise KeyError(name)
