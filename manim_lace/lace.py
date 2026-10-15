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
import warnings
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Literal

import manim
import numpy as np
from manim.utils.bezier import bezier as _bezier

from .interlacing import PARALLEL_SIN_ATOL, Interlacing
from .stroke import STROKE_UNITS_PER_WIDTH, StrokeWeave
from .swatches import random_swatch

__all__ = [
    "CURVE_SAMPLES",
    "HOLE_GROUP_METHODS",
    "RENDER_MODES",
    "RIBBON_GROUP_METHODS",
    "HoleGroupMethod",
    "Lace",
    "RenderMode",
    "RibbonGroupMethod",
    "mobject_paths",
]

logger = logging.getLogger(__name__)

#: 每条贝塞尔曲线在转成折线时采样的段数(见 :func:`mobject_paths`)。
#:
#: Manim 的 :meth:`~manim.VMobject.get_subpaths` 返回的是**控制点**(锚点 + 控制柄)而不是
#: 曲线上的点: 直接把控制点当折线用会让平滑曲线失真(控制柄把曲线"撑"开), 例如
#: ``ParametricFunction`` 的默认采样会得到一条不自交的之字形。这里按贝塞尔公式重采样,
#: 每段取 ``CURVE_SAMPLES`` 个点(不含末点, 避免与下一段重复)。
CURVE_SAMPLES = 8

#: 支持的孔洞分组方法。
HoleGroupMethod = Literal["by_area", "by_distance", "by_hole_index", "by_vertex_count"]
HOLE_GROUP_METHODS: tuple[str, ...] = ("by_area", "by_distance", "by_hole_index", "by_vertex_count")

#: 支持的丝带分组方法(``by_ribbon_index`` 逐片段轮换, 其余按分组线性铺开调色板)。
RibbonGroupMethod = Literal["by_area", "by_distance", "by_path", "by_ribbon_index", "by_vertex_count"]
RIBBON_GROUP_METHODS: tuple[str, ...] = ("by_area", "by_distance", "by_path", "by_ribbon_index", "by_vertex_count")

#: 编织通道(``Lace(..., render=...)``):
#:
#: - ``"ribbon"``(默认): 把丝带当作**区域**, 用偏移线交点把每条丝带切成片段多边形
#:   (`manim_lace.interlacing`), 有孔洞、可半透明、可 3D 挤出;
#: - ``"stroke"``: 把丝带当作**中心线 + ``stroke_width``**(`manim_lace.stroke`) —— 事件取中心线交叉
#:   的弧长参数、断口取 ``offset / |sinθ|``、孔洞不需要构造。**必须不透明**, 且没有孔洞/3D,
#:   详见 `PROGRESS.md` §3 P0-6。
RenderMode = Literal["ribbon", "stroke"]
RENDER_MODES: tuple[str, ...] = ("ribbon", "stroke")


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


def mobject_paths(mobject: manim.VMobject, samples: int = CURVE_SAMPLES) -> list[np.ndarray]:
    """把一个 Manim 对象拆成"曲线折线"列表(每个子路径一条)。

    与 :meth:`~manim.VMobject.get_subpaths` 的区别: 后者返回的是**控制点**(锚点 + 控制柄),
    直接当折线用会让平滑曲线失真 —— ``ParametricFunction`` 的默认采样会被控制柄"撑"成一条
    不自交的之字形, ``Circle`` 则变成控制点多边形(半径 2.069 的 17 边形)。这里按三次贝塞尔
    公式在每个子路径上重采样, 得到真正落在曲线上的折线。

    全是直线段的子路径(``Line`` / ``Rectangle`` / ``Polygram`` ...)直接取各段端点, 不做采样
    —— 与"采样后共线清理"的结果完全一致, 但少 8 倍的点, 因此这类输入的几何**与之前完全相同**
    (A/B 字节级基线依赖这一点)。

    参数:
        mobject: 任意 Manim 对象(会用到它的 ``points`` 与子路径切分)。传 ``VGroup`` 时请对
            ``family_members_with_points()`` 的每个成员分别调用(:class:`Lace` 就是这么做的)。
        samples: 每条贝塞尔曲线采样的段数, 必须 ``>= 2``。

    返回:
        折线坐标列表, 每项形如 ``(N, 3)``。

    异常:
        ValueError: ``samples < 2``。
    """
    if samples < 2:
        raise ValueError(f"samples must be >= 2, got {samples}")

    n_per_curve = int(getattr(mobject, "n_points_per_cubic_curve", 4))
    paths: list[np.ndarray] = []
    for subpath in mobject.get_subpaths():
        points = np.asarray(subpath, dtype=float)
        if n_per_curve != 4 or len(points) < n_per_curve or len(points) % n_per_curve:
            paths.append(points)  # 不是标准的三次贝塞尔结构: 原样当作折线
            continue

        curves = points.reshape(-1, n_per_curve, 3)
        if _all_straight(curves):
            # 全是直线段(Line / Rectangle / Polygon / Star ...): 折线就是各段端点,
            # 不必采样 —— 与下游的共线清理结果完全一致, 但少 8 倍的点。
            paths.append(np.vstack([curves[:, 0], curves[-1, -1]]))
            continue

        params = np.linspace(0.0, 1.0, samples, endpoint=False)
        # 向量化: 把每条曲线重复 samples 次, 一次求出所有段上的采样点
        stacked = np.repeat(curves.transpose(1, 0, 2), samples, axis=1)  # (4, M * samples, 3)
        polyline = _bezier(stacked)(np.tile(params, len(curves))[:, None])
        paths.append(np.vstack([polyline, curves[-1][-1]]))
    return paths


def _all_straight(curves: np.ndarray) -> bool:
    """判断一批三次贝塞尔段是否**全是直线**(两个控制柄都与弦共线)。

    用相对判据(夹角正弦)而不是绝对量: ``|u × v| / (|u||v|)``, 阈值同
    :data:`~manim_lace.interlacing.PARALLEL_SIN_ATOL`。
    """
    start, handle1, handle2, end = curves[:, 0], curves[:, 1], curves[:, 2], curves[:, 3]
    chord = end - start
    for handle in (handle1 - start, handle2 - start):
        scale = np.linalg.norm(chord, axis=1) * np.linalg.norm(handle, axis=1)
        cross = np.abs(chord[:, 0] * handle[:, 1] - chord[:, 1] * handle[:, 0])
        if np.any(cross > PARALLEL_SIN_ATOL * np.maximum(scale, 1e-300)):
            return False
    return True


def _polygon_area(coords: np.ndarray) -> float:
    """用 Shoelace 公式计算多边形面积(忽略首尾重复点)。"""
    pts = coords[:-1] if np.allclose(coords[0], coords[-1]) else coords
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * np.abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _signed_area(coords: np.ndarray) -> float:
    """Shoelace **有向**面积(逆时针为正, 忽略首尾重复点)。"""
    pts = coords[:-1] if np.allclose(coords[0], coords[-1]) else coords
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _annulus_loops(ribbon: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """把环形丝带拆回"外环 + 内环"两条各自闭合的环; 不是环形丝带时返回 ``None``。

    :func:`~manim_lace.interlacing.annulus_polygon` 把两条闭合环缝成**一条**轮廓:
    外环(逆时针) + 狭缝 + 反向内环(顺时针)。狭缝是两条零宽度重合边 —— 填充时被非零绕数
    规则抵消(只在环形带上着色), 但**描边会把它画成一条横跨带子的线**(缺陷 1 修复后
    残留的视觉瑕疵)。拆成两个独立子路径后, Manim 的 cairo 后端对每个子路径分别
    ``close_path`` 再描边, 狭缝线消失, 而填充结果完全一致(外环绕数 +1 / 内环 -1,
    内区为 0, 仍是镂空)。

    结构标记(由 ``annulus_polygon`` 的构造保证, 交织片段与开放路径条带不会满足):
    外环闭合点与数组首点**逐位相同**, 其后是自身闭合的反向内环, 数组以首点收尾;
    两环绕向相反且外环面积更大。找不到该结构时返回 ``None``, 按普通单轮廓多边形处理。

    参数:
        ribbon: :attr:`Interlacing.ribbons` 里的一条多边形, ``(N, 2)``。

    返回:
        ``(外环, 内环)``(均不含首尾重复点, 交给 :class:`~manim.Polygram` 闭合),
        或 ``None``。
    """
    pts = np.asarray(ribbon, dtype=float)
    if len(pts) < 8 or not np.array_equal(pts[0], pts[-1]):
        return None
    # 外环闭合点: 与首点逐位相同的内部顶点(annulus_polygon 里的 outer[:1])
    for i in np.flatnonzero((pts[1:-1] == pts[0]).all(axis=1)) + 1:
        outer, inner = pts[: i + 1], pts[i + 1 : -1]
        if len(outer) < 4 or len(inner) < 4:
            continue
        if not (np.array_equal(outer[0], outer[-1]) and np.array_equal(inner[0], inner[-1])):
            continue
        area_outer, area_inner = _signed_area(outer), _signed_area(inner)
        if area_outer <= 0.0 or area_inner >= 0.0:
            continue  # 必须外逆内顺, 否则非零绕数下填不出孔洞
        if area_outer <= -area_inner:
            continue  # 外环面积必须更大
        return outer[:-1], inner[:-1]
    return None


def _ribbon_mobject(ribbon: np.ndarray, poly_kwargs: dict[str, Any]) -> manim.VMobject:
    """把一个丝带多边形建成 Manim 对象。

    无自交闭合路径的环形丝带拆成"外环 + 内环"两个子路径(见 :func:`_annulus_loops`),
    用 :class:`~manim.Polygram` 一次构造 —— ``Polygon`` 本就是单组 ``Polygram``,
    因此逐条环的几何与描边和之前完全一致, 只是不再有狭缝描边; 其余丝带(交织片段 /
    开放路径条带)仍是单轮廓 :class:`~manim.Polygon`, 与之前逐字节一致。
    """
    loops = _annulus_loops(ribbon)
    if loops is None:
        return manim.Polygon(*to_3d(ribbon), **poly_kwargs)
    return manim.Polygram(*(to_3d(loop) for loop in loops), **poly_kwargs)


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

    丝带样式可以直接通过 Manim 关键字参数传入(如 ``stroke_color`` /
    ``stroke_width`` / ``fill_color`` / ``fill_opacity``), 它们会被转发给每个
    丝带片段的 :class:`~manim.mobject.geometry.polygram.Polygon`; 也可以按分组自动
    配色(与孔洞对称):

    - ``ribbon_color``: 所有丝带的统一填充色(优先级高于 ``ribbon_swatch``);
    - ``ribbon_swatch``: 自动着色使用的调色板; ``None``(默认)表示不按分组着色,
      即所有丝带沿用传入的 kwargs, 保持旧行为;
    - ``ribbon_group_method``: 丝带的分组方法, 默认 ``"by_ribbon_index"``:

      - ``"by_ribbon_index"``: 每个片段自成一组并**逐片段轮换**调色板, 相邻片段换色,
        便于看清交织结构的断口;
      - ``"by_path"``: 按丝带归属的输入路径分组(最近的路径), 同一条路径的丝带同色,
        适合多条路径组成的图形;
      - ``"by_distance"``: 按丝带中心到整体中心的距离分组, 适合径向对称图形;
      - ``"by_area"``: 按 (顶点数, 面积) 分组;
      - ``"by_vertex_count"``: 仅按片段的边数分组。

    编织通道(``render``):

    - ``"ribbon"``(默认): 把丝带当作**区域**切分 —— 有孔洞、可半透明、可 3D 挤出, 见上;
    - ``"stroke"``: 把丝带当作**中心线 + ``stroke_width``**(见 :mod:`manim_lace.stroke`) ——
      事件取中心线交叉的弧长参数、断口取 ``offset / |sinθ|``、孔洞不需要构造
      (没被描边盖住的地方自然是背景)。代价: **必须不透明**(断口端头的残差靠"不透明 + 顺序"
      兜住), 没有孔洞与 3D 挤出; 线宽被强制为 ``2 * offset / 0.01``, 冲突的 kwargs
      (``stroke_width`` / ``stroke_opacity`` / ``fill_opacity``)会被忽略并告警; 交替无解
      (约束成奇环)时退化成"每条路径一根完整描边"。

    显式传入 ``fill_color`` 时会覆盖分组配色。

    输入转换: 目标对象会先被拆成**曲线折线**(见 :func:`mobject_paths`: 每个三次贝塞尔段按
    :data:`CURVE_SAMPLES` 个点采样), 而不是把 Manim 的**控制点**直接当折线 —— 后者会让平滑
    曲线失真(``ParametricFunction`` 默认采样会被控制柄"撑"成一条不自交的之字形)。
    ``Line`` / ``Rectangle`` / ``Polygram`` 这类直线输入采样后会全部共线, 由共线清理还原,
    几何与之前完全一致。

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
            ``hole_group_method`` / ``ribbon_group_method`` 不被支持、
            ``hole_swatch`` / ``ribbon_swatch`` 为空列表, 或
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
        ribbon_color: Any | None = None,
        ribbon_swatch: Sequence[Any] | None = None,
        ribbon_group_method: str = "by_ribbon_index",
        render: str = "ribbon",
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
        if ribbon_group_method not in RIBBON_GROUP_METHODS:
            raise ValueError(
                f"unknown ribbon_group_method {ribbon_group_method!r}, expected one of {RIBBON_GROUP_METHODS}",
            )
        if ribbon_swatch is not None and len(ribbon_swatch) == 0:
            raise ValueError("ribbon_swatch must not be empty; pass None to keep the kwargs colour")
        if render not in RENDER_MODES:
            raise ValueError(f"unknown render {render!r}, expected one of {RENDER_MODES}")

        self.offset = offset
        self.hole_opacity = hole_opacity
        self.hole_color = hole_color
        self.hole_group_method = hole_group_method
        self.ribbon_color = ribbon_color
        self.ribbon_group_method = ribbon_group_method
        self.render = render
        self.kwargs = kwargs
        #: 实际用于孔洞着色的调色板。
        self.hole_swatch: tuple[Any, ...] = tuple(hole_swatch) if hole_swatch is not None else tuple(random_swatch())
        #: 实际用于丝带分组着色的调色板; ``None`` 表示不按分组着色。
        self.ribbon_swatch: tuple[Any, ...] | None = tuple(ribbon_swatch) if ribbon_swatch is not None else None

        paths: list[np.ndarray] = []
        for mob in list(target_mobject.family_members_with_points()):
            paths.extend(mobject_paths(mob))

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
        if self.render == "stroke":
            self._generate_stroke_visuals()
            return

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

        # 2. 丝带片段: 分组配色(如启用)只填 fill_color, 用户传入的 kwargs 优先级更高
        ribbon_colors = self._ribbon_colors()
        for index, ribbon in enumerate(self.interlacing.ribbons):
            poly_kwargs: dict[str, Any] = {"color": self.kwargs.get("stroke_color", manim.WHITE)}
            color = self.ribbon_color if self.ribbon_color is not None else None
            if color is None and ribbon_colors is not None:
                color = ribbon_colors[index]
            if color is not None and "fill_color" not in self.kwargs:
                poly_kwargs["fill_color"] = color
            poly_kwargs.update(self.kwargs)
            self.ribbons.add(_ribbon_mobject(ribbon, poly_kwargs))

    def _generate_stroke_visuals(self) -> None:
        """按"中心线 + ``stroke_width``"通道生成片段(见 :mod:`manim_lace.stroke`)。

        与 polygon 通道的差别:

        * 片段是**中心线的一段**, 线宽由 ``offset`` 强制决定
          (``2 * offset / STROKE_UNITS_PER_WIDTH``) —— 用户传的 ``stroke_width`` / 不透明参数会被
          忽略并告警, 否则"断口恰好被压上方盖住"这个前提不成立;
        * 必须**不透明**: 半透明会让"谁盖住谁"退化成混色(见 `PROGRESS.md` §3 P0-6);
        * ``holes`` 为空 —— 没被描边盖住的地方自然是背景;
        * 交替无解(约束成奇环)或切不出片段时**不编织**: 每条路径退化成一根完整描边并告警。

        配色与 polygon 通道同源: ``ribbon_color`` 优先, 其次 ``ribbon_swatch``
        (``ribbon_group_method == "by_path"`` 按路径取色, 否则按片段轮换), 否则用 kwargs 的
        ``stroke_color``; 其余分组方法对"中心线段"没有意义。
        """
        self.weave = StrokeWeave(self.interlacing.paths, self.offset)
        for issue in self.weave.issues:
            warnings.warn(f"stroke 通道: {issue}", UserWarning, stacklevel=2)

        width = 2.0 * self.offset / STROKE_UNITS_PER_WIDTH
        blocked = {"stroke_width", "stroke_opacity", "fill_opacity"}
        conflicts: list[str] = []
        if "stroke_width" in self.kwargs and not np.isclose(float(self.kwargs["stroke_width"]), width):
            conflicts.append(f"stroke_width={self.kwargs['stroke_width']}(应为 {width:.6g})")
        if float(self.kwargs.get("stroke_opacity", 1.0)) < 1.0:
            conflicts.append(f"stroke_opacity={self.kwargs['stroke_opacity']}(必须为 1)")
        if float(self.kwargs.get("fill_opacity", 0.0)) > 0.0:
            conflicts.append(f"fill_opacity={self.kwargs['fill_opacity']}(必须为 0)")
        if conflicts:
            warnings.warn(
                "stroke 通道按中心线宽度与不透明绘制, 以下参数被忽略: " + ", ".join(conflicts),
                UserWarning,
                stacklevel=3,
            )
        stroke_kwargs = {key: value for key, value in self.kwargs.items() if key not in blocked}

        def colour_for(path_index: int, index: int) -> Any:
            if self.ribbon_color is not None:
                return self.ribbon_color
            if self.ribbon_swatch is not None:
                swatch = self.ribbon_swatch
                if self.ribbon_group_method == "by_path":
                    return swatch[path_index % len(swatch)]
                return swatch[index % len(swatch)]
            return self.kwargs.get("stroke_color", self.kwargs.get("color", manim.WHITE))

        if self.weave.flags is None or not self.weave.segments:
            # 交替无解 / 切不出片段: 不编织, 但形状仍然正确(整条路径一根描边)
            pieces: list[dict[str, Any]] = [
                {"path": index, "points": np.asarray(path, dtype=float)[:, :2]}
                for index, path in enumerate(self.weave.paths)
            ]
        else:
            order = self.weave.order if self.weave.order is not None else range(len(self.weave.segments))
            pieces = [self.weave.segments[index] for index in order]

        for index, piece in enumerate(pieces):
            mobject = manim.VMobject(**stroke_kwargs)
            mobject.set_points_as_corners(to_3d(np.asarray(piece["points"], dtype=float)))
            mobject.set_stroke(color=colour_for(piece["path"], index), width=width, opacity=1.0)
            mobject.set_fill(opacity=0.0)
            self.ribbons.add(mobject)

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

    @functools.cached_property
    def ribbon_groups(self) -> dict[Any, list[int]]:
        """按 :attr:`ribbon_group_method` 对丝带片段分组。

        返回:
            ``{分组键: [片段下标, ...]}``, 键已排序以保证配色稳定可复现; 没有丝带时返回
            空字典。与 :attr:`hole_groups` 的区别: 丝带着色的关键是"哪个片段用哪种颜色",
            所以这里给的是**下标**而不是坐标。
        """
        ribbons = self.interlacing.ribbons
        if not ribbons:
            return {}

        groups: dict[Any, list[int]] = defaultdict(list)

        if self.ribbon_group_method == "by_ribbon_index":
            for index in range(len(ribbons)):
                groups[index].append(index)
        elif self.ribbon_group_method == "by_vertex_count":
            for index, ribbon in enumerate(ribbons):
                groups[len(ribbon) - 1].append(index)
        elif self.ribbon_group_method == "by_area":
            for index, ribbon in enumerate(ribbons):
                groups[(len(ribbon) - 1, round(_polygon_area(ribbon), 4))].append(index)
        elif self.ribbon_group_method == "by_path":
            for index, ribbon in enumerate(ribbons):
                groups[self._nearest_path(ribbon)].append(index)
        elif self.ribbon_group_method == "by_distance":
            centers = np.array([np.mean(np.asarray(ribbon, dtype=float)[:-1, :2], axis=0) for ribbon in ribbons])
            groups.update(self._group_indices_by_distance(centers))
        else:  # pragma: no cover - 构造时已校验, 仅作为防御
            raise ValueError(f"unknown ribbon_group_method {self.ribbon_group_method!r}")

        return {key: groups[key] for key in sorted(groups)}

    def _nearest_path(self, ribbon: np.ndarray) -> int:
        """丝带片段归属到最近的输入路径(按片段顶点到折线的平均最近距离)。"""
        verts = np.asarray(ribbon, dtype=float)[:-1, :2]
        best_index, best_distance = 0, np.inf
        for index, path in enumerate(self.interlacing.paths):
            coords = np.asarray(path, dtype=float)[:, :2]
            seg_a, seg_b = coords[:-1], coords[1:]
            ab = seg_b - seg_a
            ab_len2 = np.maximum(np.sum(ab * ab, axis=1), 1e-18)
            ap = verts[:, None, :] - seg_a[None, :, :]
            ratio = np.clip(np.sum(ap * ab[None, :, :], axis=2) / ab_len2[None, :], 0.0, 1.0)
            proj = seg_a[None, :, :] + ratio[:, :, None] * ab[None, :, :]
            distance = float(np.mean(np.linalg.norm(verts[:, None, :] - proj, axis=2).min(axis=1)))
            if distance < best_distance:
                best_index, best_distance = index, distance
        return best_index

    @staticmethod
    def _group_indices_by_distance(centers: np.ndarray) -> dict[int, list[int]]:
        """按"到整体中心的距离"把点分组: 排序后相邻距离出现明显跳跃就切一组。

        阈值取最小真实跳跃的一半(过滤浮点噪声), 与 :attr:`hole_groups` 的
        ``"by_distance"`` 保持一致。
        """
        global_center = np.mean(centers, axis=0)
        distances = np.linalg.norm(centers - global_center, axis=1)
        order = np.argsort(distances)
        sorted_distances = distances[order]
        diffs = np.diff(sorted_distances)
        significant = diffs[diffs > 1e-5]
        tolerance = float(np.min(significant) * 0.5) if len(significant) > 0 else 1e-3

        groups: dict[int, list[int]] = defaultdict(list)
        group_id = 0
        groups[group_id].append(int(order[0]))
        for position in range(len(sorted_distances) - 1):
            if sorted_distances[position + 1] - sorted_distances[position] > tolerance:
                group_id += 1
            groups[group_id].append(int(order[position + 1]))
        return groups

    def _ribbon_colors(self) -> list[Any] | None:
        """每个丝带片段的填充色(:attr:`ribbon_swatch` 为 ``None`` 时返回 ``None``)。

        ``"by_ribbon_index"`` 逐片段轮换调色板(相邻片段换色, 便于看清断口); 其余分组方法
        把调色板按组序线性铺开, 与孔洞的配色方式一致。
        """
        if self.ribbon_swatch is None:
            return None
        swatch = self.ribbon_swatch
        count = len(self.interlacing.ribbons)
        if self.ribbon_group_method == "by_ribbon_index":
            return [swatch[index % len(swatch)] for index in range(count)]

        colors: list[Any] = [swatch[0]] * count
        groups = list(self.ribbon_groups.values())
        for position, indices in enumerate(groups):
            if len(groups) > 1:
                color_index = int(round(position * (len(swatch) - 1) / (len(groups) - 1)))
            else:
                color_index = 0
            for index in indices:
                colors[index] = swatch[color_index % len(swatch)]
        return colors
