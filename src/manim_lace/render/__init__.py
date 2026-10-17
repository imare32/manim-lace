"""Rendering backends: cut centerline strokes and area-based ribbon regions."""

from .arrangement import render_arrangement_regions
from .hybrid import render_hybrid_regions
from .order import paint_order
from .pixels import px_to_stroke_width, px_to_units, stroke_width_to_px
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
    "paint_order",
    "px_to_stroke_width",
    "px_to_units",
    "render_arrangement_regions",
    "render_hybrid_regions",
    "render_region_geometry",
    "render_stroke_geometry",
    "stroke_width_to_px",
]
