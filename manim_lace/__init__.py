"""manim_lace: 为任意 Manim 路径赋予"编织交错"效果。

快速开始::

    from manim import Circle, WHITE
    from manim_lace import Lace

    lace = Lace(Circle(radius=2), offset=0.2, stroke_color=WHITE)

主要导出:

* :class:`~manim_lace.lace.Lace`: 渲染层入口, 把路径转换为丝带图案;
* :class:`~manim_lace.rosette.StarRosette`: 星形玫瑰图案生成器;
* :class:`~manim_lace.interlacing.Interlacing`: 纯几何求解器(无 Manim 依赖);
* :func:`~manim_lace.swatches.random_swatch`: 内置日式配色色卡随机取色。
"""

from .interlacing import VALIDATE_MODES, Interlacing, validate_paths
from .lace import HOLE_GROUP_METHODS, Lace
from .rosette import STAR_TYPE, STAR_TYPE_VALUES, StarRosette, cal_kernels
from .swatches import random_swatch, swatches

#: 版本号。此处是唯一数据源, 打包时由 hatchling 读取(见 pyproject.toml)。
__version__ = "0.3.0"

__all__ = [
    "HOLE_GROUP_METHODS",
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
