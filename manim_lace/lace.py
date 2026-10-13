"""Manim 渲染层: 把几何求解结果转换为可渲染的 :class:`manim.VGroup`。

:class:`Lace` 负责两件事:

* 从 ``target_mobject`` 中提取所有子路径, 交给
  :class:`~manim_lace.interlacing.Interlacing` 求解;
* 把求解得到的"孔洞"与"丝带片段"多边形数据转换成 Manim 的
  :class:`~manim.mobject.geometry.polygram.Polygon`。
"""

from __future__ import annotations

import functools
import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal

import manim
import numpy as np

from .interlacing import Interlacing
from .swatches import random_swatch

__all__ = ["HOLE_GROUP_METHODS", "HoleGroupMethod", "Lace"]

logger = logging.getLogger(__name__)

#: 支持的孔洞分组方法。
HoleGroupMethod = Literal["by_area", "by_distance", "by_hole_index", "by_vertex_count"]
HOLE_GROUP_METHODS: tuple[str, ...] = ("by_area", "by_distance", "by_hole_index", "by_vertex_count")


def to_3d(coords: np.ndarray) -> np.ndarray:
    """把 ``(N, 2)`` 或 ``(N, 3)`` 的坐标补齐为 Manim 需要的三维点。

    参数:
        coords: 二维或三维坐标数组。

    返回:
        ``(N, 3)`` 的坐标数组, 二维输入会被补上 ``z = 0``。
    """
    coords = np.asarray(coords, dtype=float)
    if coords.ndim != 2 or coords.shape[1] not in (2, 3):
        raise ValueError(f"coords must be a (N, 2) or (N, 3) array, got shape {coords.shape}")
    if coords.shape[1] == 3:
        return coords
    return np.hstack([coords, np.zeros((len(coords), 1))])


def _polygon_area(coords: np.ndarray) -> float:
    """用 Shoelace 公式计算多边形面积(忽略首尾重复点)。"""
    pts = coords[:-1] if np.allclose(coords[0], coords[-1]) else coords
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


class Lace(manim.VGroup):
    """把任意 Manim 路径转换为具有"编织交错"效果的丝带图案。

    该类是 :class:`manim.VGroup` 的子类, 内部包含两个子组:

    * ``holes``: 孔洞多边形(填充色块), 先绘制;
    * ``ribbons``: 丝带片段多边形, 后绘制, 从而遮盖下方孔洞的局部区域, 形成编织错觉。

    孔洞样式:

    - ``hole_opacity``: 孔的不透明度, 默认 ``1.0``;
    - ``hole_color``: 孔的颜色, 默认按分组自动着色;
    - ``hole_swatch``: 自动着色使用的调色板, 默认从内置色卡中随机取一组;
    - ``hole_group_method``: 孔的分组方法, 默认 ``"by_area"``:

      - ``"by_area"``: 按 (顶点数, 面积) 分组, 适合大多数几何图形;
      - ``"by_distance"``: 按孔中心到整体中心的距离分组, 适合径向对称图形;
      - ``"by_hole_index"``: 每个孔自成一组, 颜色偏随机;
      - ``"by_vertex_count"``: 仅按孔的边数分组。

    丝带样式直接通过 Manim 关键字参数传入(如 ``stroke_color`` /
    ``stroke_width`` / ``fill_color`` / ``fill_opacity``), 它们会被转发给每个
    丝带片段的 :class:`~manim.mobject.geometry.polygram.Polygon`。

    输入退化检查: ``validate`` 参数转发给
    :class:`~manim_lace.interlacing.Interlacing`(见
    :func:`~manim_lace.interlacing.validate_paths`)。默认 ``"warn"`` 只会发出
    ``UserWarning``; 传 ``"raise"`` 可以在输入含有共线重叠 / 多线共点时直接报错,
    而不是渲染出错乱的图案。检出的问题列表可从 ``lace.interlacing.path_issues`` 读取。

    示例:
        >>> from manim import Circle, WHITE
        >>> lace = Lace(Circle(radius=2), offset=0.2, stroke_color=WHITE, fill_opacity=1.0)
        >>> isinstance(lace, manim.VGroup)
        True

    异常:
        ValueError: ``offset`` 非正、``hole_opacity`` 不在 ``[0, 1]``、
            ``hole_group_method`` 不被支持、``hole_swatch`` 为空列表, 或
            ``validate="raise"`` 且输入退化时抛出。
    """

    def __init__(
        self,
        target_mobject: manim.VMobject,
        offset: float = 0.1,
        hole_opacity: float = 1.0,
        hole_color: Any | None = None,
        hole_swatch: Sequence[Any] | None = None,
        hole_group_method: str = "by_area",
        validate: str = "warn",
        **kwargs: Any,
    ):
        super().__init__()

        if not np.isfinite(offset) or offset <= 0:
            raise ValueError(f"offset must be a positive finite number, got {offset!r}")
        if not 0.0 <= hole_opacity <= 1.0:
            raise ValueError(f"hole_opacity must be within [0, 1], got {hole_opacity!r}")
        if hole_group_method not in HOLE_GROUP_METHODS:
            raise ValueError(
                f"unknown hole_group_method {hole_group_method!r}, expected one of {HOLE_GROUP_METHODS}",
            )
        if hole_swatch is not None and len(hole_swatch) == 0:
            raise ValueError("hole_swatch must not be empty; pass None to use a random palette")

        self.offset = offset
        self.hole_opacity = hole_opacity
        self.hole_color = hole_color
        self.hole_group_method = hole_group_method
        self.kwargs = kwargs
        #: 实际用于孔洞着色的调色板。
        self.hole_swatch: tuple[Any, ...] = tuple(hole_swatch) if hole_swatch is not None else tuple(random_swatch())

        paths: list[np.ndarray] = []
        for mob in list(target_mobject.family_members_with_points()):
            paths.extend(mob.get_subpaths())

        self.interlacing = Interlacing(paths, offset, validate=validate)

        self.ribbons = manim.VGroup()
        self.holes = manim.VGroup()
        self._generate_visuals()
        self.add(self.holes, self.ribbons)

    def __repr__(self) -> str:
        return f"Lace(holes={len(self.holes)}, ribbons={len(self.ribbons)}, offset={self.offset})"

    @property
    def num_holes(self) -> int:
        """孔洞数量。"""
        return len(self.holes)

    @property
    def num_ribbons(self) -> int:
        """丝带片段数量。"""
        return len(self.ribbons)

    def _generate_visuals(self) -> None:
        """生成 ``holes`` 与 ``ribbons`` 两组可视化对象。"""
        # 1. 孔洞: 按分组把调色板颜色线性映射到各组
        swatch = self.hole_swatch
        groups = list(self.hole_groups.values())
        num_groups = len(groups)
        swatch_len = len(swatch)

        for i, holes in enumerate(groups):
            if num_groups > 1:
                # 将 i 从 [0, num_groups-1] 线性映射到 [0, swatch_len-1]
                color_index = int(round(i * (swatch_len - 1) / (num_groups - 1)))
            else:
                color_index = 0
            color = swatch[color_index % swatch_len]

            for hole in holes:
                self.holes.add(
                    manim.Polygon(
                        *to_3d(hole),
                        stroke_width=0,
                        fill_opacity=self.hole_opacity,
                        fill_color=self.hole_color or color,
                    ),
                )

        # 2. 丝带片段: 用户传入的 kwargs 优先级更高
        for ribbon in self.interlacing.ribbons:
            poly_kwargs: dict[str, Any] = {"color": self.kwargs.get("stroke_color", manim.WHITE)}
            poly_kwargs.update(self.kwargs)
            self.ribbons.add(manim.Polygon(*to_3d(ribbon), **poly_kwargs))

    def draw_path(self, coords: np.ndarray) -> manim.VMobject:
        """调试辅助: 把一组坐标画成黑色折线。

        参数:
            coords: ``(N, 2)`` 或 ``(N, 3)`` 的坐标数组。

        返回:
            以折线顶点构建的 :class:`manim.VMobject`。
        """
        return manim.VMobject(stroke_color=manim.BLACK).set_points_as_corners(to_3d(coords))

    @functools.cached_property
    def hole_groups(self) -> dict[Any, list[np.ndarray]]:
        """按 :attr:`hole_group_method` 对孔洞分组。

        返回:
            ``{分组键: [孔洞坐标数组, ...]}``, 键已排序以保证配色稳定可复现。
            没有孔洞时返回空字典。
        """
        holes = self.interlacing.holes
        if not holes:
            return {}

        groups: dict[Any, list[np.ndarray]] = defaultdict(list)

        if self.hole_group_method == "by_area":
            for hole in holes:
                # 孔洞坐标首尾重复, 顶点数需要减一
                num_verts = len(hole) - 1
                area = _polygon_area(hole)
                # 面积保留 4 位小数以忽略浮点误差
                key = (num_verts, round(area, 4))
                groups[key].append(hole)
            # 排序优先级: 顶点数 -> 面积
            sorted_keys = sorted(groups.keys(), key=lambda k: (k[0], k[1]))

        elif self.hole_group_method == "by_vertex_count":
            for hole in holes:
                groups[len(hole) - 1].append(hole)
            sorted_keys = sorted(groups.keys())

        elif self.hole_group_method == "by_hole_index":
            for i, hole in enumerate(holes):
                groups[i].append(hole)
            sorted_keys = sorted(groups.keys())

        elif self.hole_group_method == "by_distance":
            coords = np.array([np.mean(hole[:-1], axis=0) for hole in holes])
            global_center = np.mean(coords, axis=0)

            # 按到整体中心的欧氏距离排序
            dists = np.linalg.norm(coords - global_center, axis=1)
            sort_indices = np.argsort(dists)
            sorted_dists = dists[sort_indices]
            sorted_holes = [holes[i] for i in sort_indices]

            # 智能阈值: 取最小真实距离跳跃的一半, 过滤 1e-5 以下的数值噪声
            diffs = np.diff(sorted_dists)
            significant_gaps = diffs[diffs > 1e-5]
            auto_tolerance = float(np.min(significant_gaps) * 0.5) if len(significant_gaps) > 0 else 1e-3

            current_group_id = 0
            groups[current_group_id].append(sorted_holes[0])
            for i in range(len(sorted_dists) - 1):
                if sorted_dists[i + 1] - sorted_dists[i] > auto_tolerance:
                    current_group_id += 1
                groups[current_group_id].append(sorted_holes[i + 1])

            sorted_keys = sorted(groups.keys())

        else:  # pragma: no cover - 构造时已校验, 仅作为防御
            raise ValueError(f"unknown hole_group_method {self.hole_group_method!r}")

        return {k: groups[k] for k in sorted_keys}
