"""Rendering backends. Region rendering is currently an explicit scaffold."""

from .stroke import StrokePiece, StrokeRenderResult, render_stroke_geometry

__all__ = ["StrokePiece", "StrokeRenderResult", "render_stroke_geometry"]
