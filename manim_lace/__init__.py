"""manim_lace: 为任意 Manim 路径赋予"编织交错"效果。

快速开始::

    from manim import Circle, WHITE
    from manim_lace import Lace

    lace = Lace(Circle(radius=2), offset=0.2, stroke_color=WHITE)

主要导出:

* :class:`~manim_lace.lace.Lace`: 渲染层入口, 把路径转换为丝带图案;
* :class:`~manim_lace.interlacing.Interlacing`: 纯几何求解器(无 Manim 依赖);
* :func:`~manim_lace.swatches.random_swatch`: 内置日式配色色卡随机取色。

**可选模块**: :mod:`manim_lace.rosette`(星形玫瑰图案生成器)与核心的"任意路径 → 编织丝带"
无关 —— 它只依赖 ``numpy`` 与 ``manim``, 不引用 ``interlacing`` / ``lace``。因此这里**不在
导入包时加载它**(惰性 ``__getattr__``, PEP 562): ``from manim_lace import StarRosette`` 仍然
可用, 但 ``import manim_lace`` 不会把玫瑰线拉进内存, 将来把它拆成独立包时只需删掉本文件的
转发即可。
"""

from __future__ import annotations

from .interlacing import VALIDATE_MODES, Interlacing, validate_paths
from .lace import HOLE_GROUP_METHODS, RIBBON_GROUP_METHODS, Lace
from .swatches import random_swatch, swatches

#: 版本号。此处是唯一数据源, 打包时由 hatchling 读取(见 pyproject.toml)。
__version__ = "0.3.0"

#: 可选模块 `manim_lace.rosette` 的公开名(惰性转发, 见模块 docstring)。
_ROSETTE_EXPORTS = ("STAR_TYPE", "STAR_TYPE_VALUES", "StarRosette", "cal_kernels")

__all__ = [
    "HOLE_GROUP_METHODS",
    "RIBBON_GROUP_METHODS",
    "STAR_TYPE",
    "STAR_TYPE_VALUES",
    "VALIDATE_MODES",
    "Interlacing",
    "Lace",
    "StarRosette",
    "__version__",
    "cal_kernels",
    "random_swatch",
    "swatches",
    "validate_paths",
]


def __getattr__(name: str):
    """惰性转发可选模块 :mod:`manim_lace.rosette` 的公开名。

    可选模块缺失时抛 :class:`AttributeError`(而不是 :class:`ImportError`), 这样 ``hasattr``
    与 IDE 的补全都能正常工作, 拆分出去之后也只会影响这几个名字。
    """
    if name in _ROSETTE_EXPORTS:
        try:
            from . import rosette
        except ImportError as exc:  # pragma: no cover - 只在玫瑰线被拆走时触发
            raise AttributeError(f"可选模块 manim_lace.rosette 不可用: {exc}") from exc
        return getattr(rosette, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_ROSETTE_EXPORTS})
