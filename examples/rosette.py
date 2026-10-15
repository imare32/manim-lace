"""星形玫瑰 (Star Rosette) 图案的几何生成。

本模块实现论文式"核 (kernel) + 镜像 + 旋转"的玫瑰线构造法:

1. :func:`cal_kernels` 计算第 ``0`` 到第 ``level`` 阶的基础骨架(核);
2. :func:`get_petals_by_kernel` 把核沿 x 轴镜像得到花瓣, 再旋转 ``n`` 份;
3. :func:`sort_petals` 按拓扑连接顺序重排花瓣, :func:`merge_adjacent_petals`
   把首尾相接的花瓣合并成连续多段线;
4. :class:`StarRosette` 把结果包装成 Manim 的 :class:`~manim.Polygram`。
"""

from __future__ import annotations

import math
import typing

import numpy as np
from manim import Polygram

__all__ = [
    "STAR_TYPE",
    "STAR_TYPE_VALUES",
    "StarRosette",
    "cal_kernels",
    "get_petals_by_kernel",
    "merge_adjacent_petals",
    "rosette",
    "sort_petals",
    "transform_reps",
]

#: 支持的花型标识。首位表示 Parallel / Convergent, 次位表示尖端处理方式。
STAR_TYPE = typing.Literal["PA", "PO", "PR", "CA", "CR"]
#: :data:`STAR_TYPE` 的取值元组。
STAR_TYPE_VALUES: tuple[str, ...] = typing.get_args(STAR_TYPE)

#: 允许的最小花瓣数。``n = 3`` 时 ``xk0 = cosθ + sinθ / tan2θ = 0``, 核会退化成一
#: 条从原点出发的径向线段, 最终只能得到几根交叉的辐射线, 没有实际意义。
MIN_PETALS = 4
#: 判定"旋转后的核线段是否与 x 轴平行"的容差。平行时该线段与 x 轴没有交点,
#: 高阶核无法构造(原实现会产生 inf/nan 坐标)。
PARALLEL_ATOL = 1e-9


def _check_second_kernel_realizable(n: int, star_type: str, theta: float) -> None:
    """检查第 2 阶的尖端线是否与 x 轴平行。

    ``"O"`` 型尖端的位置由 ``xk23 = xk22 - y2 * tan(2θ)`` 给出, 当 ``2θ = 90°``
    (即 ``n = 4``) 时 ``tan(2θ)`` 发散, 尖端线与 x 轴平行而不存在交点, 该阶不可实现。
    """
    if star_type[1] == "O" and math.isclose(math.cos(2 * theta), 0.0, abs_tol=PARALLEL_ATOL):
        raise ValueError(
            f"level 2 is not realizable for n={n}, star_type={star_type!r}: "
            "the O tip line is parallel to the x-axis, so the construction has no "
            "intersection to use; use level 0 or 1 instead",
        )


def _validate_params(n: int, level: int, star_type: str) -> None:
    """校验玫瑰线参数, 不合法时抛出 :class:`ValueError`。"""
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)):
        raise TypeError(f"n must be an integer, got {type(n).__name__}")
    if n < MIN_PETALS:
        raise ValueError(f"n must be >= {MIN_PETALS}, got {n}")
    if isinstance(level, bool) or not isinstance(level, (int, np.integer)):
        raise TypeError(f"level must be an integer, got {type(level).__name__}")
    if level < 0:
        raise ValueError(f"level must be >= 0, got {level}")
    if star_type not in STAR_TYPE_VALUES:
        raise ValueError(f"unknown star_type {star_type!r}, expected one of {STAR_TYPE_VALUES}")


def transform_reps(
    coords: np.ndarray,
    move: np.ndarray | None = None,
    rotate: float | None = None,
    scale: float | None = None,
    num: int = 1,
) -> list[np.ndarray]:
    """对一组坐标做 ``num`` 次"递增旋转 + 递增缩放 + 递增平移"复制。

    第 ``i`` 份副本的变换为: 旋转 ``rotate * i``, 缩放 ``scale ** i``,
    平移 ``move * i``。``i`` 从 ``0`` 开始, 因此第一份副本与原坐标相同。

    参数:
        coords: ``(N, 2)`` 的坐标数组。
        move: 每份副本的平移增量; ``None`` 表示不平移。
        rotate: 每份副本的旋转角增量(弧度); ``None`` 表示不旋转。
        scale: 每份副本的缩放比例增量; ``None`` 表示不缩放。
        num: 副本数量, 必须为正整数。

    返回:
        长度为 ``num`` 的坐标数组列表。

    异常:
        ValueError: ``num`` 小于 1。
    """
    if num < 1:
        raise ValueError(f"num must be >= 1, got {num}")

    move_arr = np.zeros(2) if move is None else np.asarray(move, dtype=float)
    rotate = 0 if rotate is None else rotate
    scale = 1 if scale is None else scale

    reps: list[np.ndarray] = []
    for i in range(num):
        theta = rotate * i
        c, s = np.cos(theta), np.sin(theta)
        rotation = np.array([[c, -s], [s, c]])

        new_coords = coords @ rotation.T
        new_coords = new_coords * (scale**i)
        new_coords = new_coords + move_arr * i
        reps.append(new_coords)

    return reps


def rosette(kernel: np.ndarray, n: int) -> list[np.ndarray]:
    """:func:`get_petals_by_kernel` 的底层实现, 返回 ``n`` 片花瓣点集。

    该函数基于 :func:`transform_reps` 实现, 等价于 :func:`get_petals_by_kernel`,
    保留它主要是为了展示纯变换视角的实现方式。

    参数:
        kernel: ``(K, 2)`` 的核坐标。
        n: 花瓣数量。

    返回:
        长度为 ``n`` 的花瓣坐标数组列表。
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    petal = np.vstack([kernel, kernel[::-1] * (1, -1)])[::-1]
    return transform_reps(petal, rotate=2 * np.pi / n, num=n)


def cal_kernels(n: int, level: int = 2, star_type: STAR_TYPE = "PA") -> list[np.ndarray]:
    """计算 Rosette 的基础几何骨架(kernels)。

    第 0 阶与第 1 阶由三角恒等式直接给出, 第 2 阶按 ``star_type`` 分叉,
    更高阶通过把前一阶旋转 ``π/n`` 再与 x 轴求交迭代得到。

    参数:
        n: 花瓣(角)数量, 必须 ``>= MIN_PETALS``。
        level: 阶数, 必须 ``>= 0``; 返回列表的第 ``level`` 项即目标骨架。
        star_type: 花型标识, 见 :data:`STAR_TYPE`。

    返回:
        长度为 ``max(2, level + 1)`` 的骨架列表(只会构造到请求的阶), 第 ``i`` 项包含
        ``i + 1`` 个点(``i >= 2`` 时为 3 个点)。

    异常:
        TypeError: ``n`` 或 ``level`` 不是整数。
        ValueError: ``n < MIN_PETALS``、``level < 0``、``star_type`` 不被支持, 或
            该 ``(n, star_type)`` 组合不存在第 ``level`` 阶骨架(见下)。

    .. note::
        高阶骨架由"旋转前一阶 + 与 x 轴求交"迭代得到。某些 ``(n, star_type)``
        组合会让旋转后的核线段恰好与 x 轴平行(例如 ``n=6`` 的 ``PA`` 在第 4 阶),
        此时该阶在数学上不存在 —— 函数会抛出 :class:`ValueError` 而不是产出
        ``inf`` / ``nan`` 坐标。可行阶数随 ``n`` 增大而增大, 但并非无限。
    """
    _validate_params(n, level, star_type)

    θ = np.pi / n

    # 1. 基础坐标与初始 kernel 计算
    x0, y0 = np.cos(θ), np.sin(θ)
    x1, y1 = np.cos(2 * θ), np.sin(2 * θ)

    xk0 = x0 + y0 / np.tan(2 * θ)
    xk1 = x1 + y1 / np.tan(θ)
    kernels = [np.array([[x0, y0], [xk0, 0]]), np.array([[x1, y1], [xk1, 0]])]

    # 2. 第 2 阶(封闭形式)。只构造到请求的阶, 避免为不需要的阶算出退化坐标。
    if level >= 2:
        _check_second_kernel_realizable(n, star_type, θ)
        x2, y2 = np.cos(3 * θ), np.sin(3 * θ)

        if star_type[0] == "P":  # Parallel 类型
            xk21 = xk0 + y2 / np.tan(2 * θ)
            xk22 = xk21 + y2 / np.cos(θ)
            if star_type[1] == "A":
                xk23 = xk22 + y2 * np.tan(θ)
            elif star_type[1] == "O":
                xk23 = xk22 - y2 * np.tan(2 * θ)
            else:  # "R"
                xk23 = xk22
            kernel_2 = np.array([[x2, y2], [xk22, y2], [xk23, 0]])
        else:  # Convergent 类型 ("C")
            xk22 = x2 + (y2 - y0) / np.tan(θ)
            if star_type[1] == "R":
                xk23 = xk22
            else:  # "A"
                xk23 = xk22 + y0 * np.tan(θ)
            kernel_2 = np.array([[x2, y2], [xk22, y0], [xk23, 0]])

        kernels.append(kernel_2)

    # 3. 迭代计算更高阶的 kernel
    rot_matrix = np.array([[x0, -y0], [y0, x0]])

    for order in range(3, level + 1):
        pre_kernel = kernels[-1]
        rotated_kernel = pre_kernel @ rot_matrix.T
        rot_p1, rot_p2, rot_p3 = rotated_kernel[:3]

        # 计算旋转后线段与 X 轴的交点
        rx2, ry2 = rot_p2
        rx3, ry3 = rot_p3
        if math.isclose(ry2, ry3, rel_tol=PARALLEL_ATOL, abs_tol=PARALLEL_ATOL):
            # 线段与 x 轴平行, 交点要么不存在要么不唯一, 说明该阶不可实现。
            # 这里显式报错, 而不是像早期实现那样除零并产出 inf/nan 坐标。
            raise ValueError(
                f"level {order} is not realizable for n={n}, star_type={star_type!r}: "
                "the rotated kernel segment is parallel to the x-axis, so the construction "
                f"has no intersection to use; the largest usable level for this (n, star_type) is {order - 1}",
            )
        px = np.array([rx2 - ry2 * (rx3 - rx2) / (ry3 - ry2), 0.0])

        kernels.append(np.array([rot_p1, rot_p2, px]))

    return kernels


def get_petals_by_kernel(kernel: np.ndarray, n: int) -> list[np.ndarray]:
    """把核沿 x 轴镜像成花瓣, 再旋转 ``n`` 份。

    参数:
        kernel: ``(K, 2)`` 的核坐标; 镜像时会去掉与 x 轴重合的中间点。
        n: 花瓣数量, 必须 ``>= 1``。

    返回:
        长度为 ``n`` 的花瓣坐标数组列表, 按逆时针方向排列。

    异常:
        ValueError: ``n < 1``。
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    θ = np.pi / n
    petals = []
    for i in range(n):
        # 镜像合并生成单个花瓣
        flip_part = kernel[-2::-1] * np.array([1, -1])
        petal = np.vstack([kernel, flip_part])[::-1]

        # 旋转到对应位置
        angle = i * 2 * θ
        c, s = np.cos(angle), np.sin(angle)
        rot_matrix = np.array([[c, -s], [s, c]])
        petals.append(petal @ rot_matrix.T)
    return petals


def sort_petals(petals: list[np.ndarray], level: int) -> list[np.ndarray]:
    """按拓扑连接顺序重排花瓣。

    花瓣之间以固定的步长 ``level + 1`` 跳步相连, 因此先把下标按该步长分解成
    若干条循环轨道, 再依次展开, 就能保证相邻花瓣首尾相接。

    参数:
        petals: 花瓣点集列表。
        level: 阶数, 决定跳步长度 ``level + 1``。

    返回:
        重排后的花瓣列表。
    """
    n = len(petals)
    if n == 0:
        return []
    step = level + 1
    num_cycles = math.gcd(n, step)
    cycle_len = n // num_cycles

    idxs = []
    for i in range(num_cycles):
        current = i
        for _ in range(cycle_len):
            idxs.append(current)
            current = (current + step) % n

    return [petals[i] for i in idxs]


def merge_adjacent_petals(petals: list[np.ndarray]) -> list[np.ndarray]:
    """合并首尾相接的花瓣点集。

    Manim 的 :class:`~manim.Polygram` 会自动闭合多边形, 因此合并后的每一段若首尾
    点重复, 需要去掉重复的末点。

    参数:
        petals: 已排好序的花瓣点集列表。

    返回:
        合并后的多段线列表; 输入为空时返回空列表。
    """
    if not petals:
        return []

    merged_groups: list[np.ndarray] = []
    current_poly = petals[0]

    for i in range(1, len(petals)):
        next_petal = petals[i]
        if np.allclose(current_poly[-1], next_petal[0]):
            current_poly = np.vstack((current_poly, next_petal[1:]))
        else:
            merged_groups.append(current_poly)
            current_poly = next_petal

    merged_groups.append(current_poly)

    # Polygram 会自动闭合多边形, 需要移除闭合的重复点
    final_result = []
    for poly in merged_groups:
        if np.allclose(poly[0], poly[-1]) and len(poly) > 2:
            final_result.append(poly[:-1])
        else:
            final_result.append(poly)

    return final_result


class StarRosette(Polygram):
    """基于星形图案的 Manim Rosette 对象。

    参数:
        n: 花瓣(角)数量, 必须 ``>= MIN_PETALS`` (即 4); ``n = 3`` 时核会退化。
        level: 阶数(复杂度), 必须 ``>= 0``; 越大, 图形内部连接越复杂。并非所有
            ``(n, star_type)`` 组合都存在任意高阶, 不可实现的阶会抛出
            :class:`ValueError`。
        star_type: 花型标识, 见 :data:`STAR_TYPE`, 默认 ``"PA"``。
        **kwargs: 其余关键字参数透传给 :class:`~manim.Polygram`
            (如 ``stroke_color`` / ``fill_color`` / ``fill_opacity``)。

    示例:
        >>> rosette = StarRosette(10, level=2, star_type="CA", fill_opacity=0.5)
        >>> rosette.n, rosette.level, rosette.star_type
        (10, 2, 'CA')

    异常:
        TypeError: ``n`` 或 ``level`` 不是整数。
        ValueError: ``n < 3``、``level < 0`` 或 ``star_type`` 不被支持。
    """

    def __init__(self, n: int, level: int = 2, star_type: STAR_TYPE = "PA", **kwargs) -> None:
        _validate_params(n, level, star_type)

        self.n = n
        self.level = level
        self.star_type = star_type

        kernels = cal_kernels(n, level, star_type)
        kernel = kernels[level]

        raw_petals = get_petals_by_kernel(kernel, n)
        sorted_petals = sort_petals(raw_petals, level)
        merged_points_list_2d = merge_adjacent_petals(sorted_petals)

        # 转换为 Manim 所需的三维坐标并初始化
        vertex_groups = [np.pad(points, ((0, 0), (0, 1))) for points in merged_points_list_2d]
        super().__init__(*vertex_groups, **kwargs)

    def __repr__(self) -> str:
        return f"StarRosette(n={self.n}, level={self.level}, star_type={self.star_type!r})"
