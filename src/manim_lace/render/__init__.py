"""Rendering backends: cut centerline strokes and area-based ribbon regions."""

from .regions import (
    RegionRenderResult,
    RegionRing,
    RibbonRegion,
    RibbonRegionRenderer,
    render_region_geometry,
)
from .stroke import StrokePiece, StrokeRenderResult, render_stroke_geometry

__all__ = [
    "RegionRenderResult",
    "RegionRing",
    "RibbonRegion",
    "RibbonRegionRenderer",
    "StrokePiece",
    "StrokeRenderResult",
    "render_region_geometry",
    "render_stroke_geometry",
]
