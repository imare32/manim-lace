"""Manim Lace: topology-first 2D weaving geometry.

The numeric engine is importable without Manim. The convenience ``Lace`` class
is loaded lazily and requires the optional ``manim`` dependency.
"""

from importlib.util import find_spec

from .diagnostics import Diagnostic, InputPathError, LaceError, Severity, WeaveConflictError
from .engine import LaceEngine
from .geometry.sampling import sample_graph, sample_parametric
from .model import (
    CrossingEvent,
    LaceResult,
    Pass,
    PathSource,
    PolylinePath,
    TraceEvent,
    WeaveAssignment,
    WeaveTopology,
)

__version__ = "0.1.0"

__all__ = [
    "CrossingEvent", "Diagnostic", "InputPathError", "LaceEngine", "LaceError",
    "LaceResult", "Pass", "PathSource", "PolylinePath", "Severity", "TraceEvent",
    "WeaveAssignment", "WeaveConflictError", "WeaveTopology", "sample_graph", "sample_parametric",
]
if find_spec("manim") is not None:
    __all__.append("Lace")


def __getattr__(name: str):
    if name == "Lace":
        try:
            from .manim_api import Lace
        except ImportError as exc:
            raise ImportError("Lace 的 Manim 封装需要安装可选依赖：pip install 'manim-lace[manim]'") from exc
        return Lace
    raise AttributeError(name)
