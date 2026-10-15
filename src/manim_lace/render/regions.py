"""Scaffold for the future planar-region ribbon backend.

Do not replace this interface with a cycle-basis polygon heuristic. The project
spec calls for a genuine planar arrangement/half-edge face walk or a validated
2D polygon-boolean strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..model import PolylinePath, WeaveTopology


@dataclass(slots=True)
class RegionRenderResult:
    ribbon_regions: list[Any]
    holes: list[Any]
    diagnostics: list[Any]


class RibbonRegionRenderer:
    """Extension point for exact area-based ribbons; not implemented in v0.1."""

    def render(
        self,
        paths: list[PolylinePath],
        topology: WeaveTopology,
        *,
        offset: float,
        join: str = "miter",
        miter_limit: float = 5.0,
    ) -> RegionRenderResult:
        raise NotImplementedError(
            "实体 Ribbon 区域后端尚未实现。当前 starter kit 提供可运行的 stroke 几何后端；"
            "区域后端需要可靠的 planar arrangement/half-edge 或经验证的布尔运算。"
        )
