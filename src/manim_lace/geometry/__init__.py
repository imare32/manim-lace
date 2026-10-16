"""Geometry primitives and curve sampling."""

from .implicit import ORIENTATION_RULES, sample_implicit
from .sampling import sample_graph, sample_parametric

__all__ = ["ORIENTATION_RULES", "sample_graph", "sample_implicit", "sample_parametric"]
