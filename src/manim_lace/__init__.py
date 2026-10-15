"""Manim Lace: topology-first 2D weaving geometry.

The numeric engine is importable without Manim. The convenience ``Lace`` facade is
resolved lazily through module ``__getattr__`` (PEP 562), so importing the package never
imports Manim, while ``__all__`` and the ``TYPE_CHECKING`` import below keep the name
visible to static tools.
"""

from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

from .diagnostics import Diagnostic, InputPathError, LaceError, Severity, WeaveConflictError
from .engine import LaceEngine
from .geometry.sampling import sample_graph, sample_parametric
from .model import (
    CapStyle,
    ConflictStrategy,
    CrossingEvent,
    CrossingStats,
    EventPolicy,
    JoinStyle,
    LaceResult,
    Pass,
    PathSource,
    PolylinePath,
    RibbonBackend,
    TraceEvent,
    WeaveAssignment,
    WeaveTopology,
)

if TYPE_CHECKING:  # pragma: no cover - type checkers and IDEs only
    from .manim_api import Lace

__version__ = "0.1.0"


def _manim_available() -> bool:
    """Whether the optional Manim facade can be imported, without importing Manim.

    A blocked or half-initialised ``sys.modules`` entry can make ``find_spec`` raise
    instead of answering; treat anything other than a clean hit as unavailable.
    """
    try:
        return find_spec("manim") is not None
    except (ImportError, ValueError):
        return False


#: Whether the optional Manim facade can be imported.
_MANIM_AVAILABLE = _manim_available()

__all__ = [
    "CapStyle",
    "ConflictStrategy",
    "CrossingEvent",
    "CrossingStats",
    "Diagnostic",
    "EventPolicy",
    "InputPathError",
    "JoinStyle",
    "Lace",
    "LaceEngine",
    "LaceError",
    "LaceResult",
    "Pass",
    "PathSource",
    "PolylinePath",
    "RibbonBackend",
    "Severity",
    "TraceEvent",
    "WeaveAssignment",
    "WeaveConflictError",
    "WeaveTopology",
    "sample_graph",
    "sample_parametric",
]
if not _MANIM_AVAILABLE:
    # Keep __all__ truthful so that ``from manim_lace import *`` still works; the name
    # itself stays reachable and explains the missing dependency when asked for.
    __all__.remove("Lace")


def __getattr__(name: str) -> Any:
    """Import the optional Manim facade only when it is actually requested."""
    if name != "Lace":
        raise AttributeError(name)
    try:
        from .manim_api import Lace
    except Exception as exc:
        if _MANIM_AVAILABLE:
            # Manim is there, so this is a real import failure: do not blame the install.
            raise
        # Otherwise the missing dependency is the actionable part, whatever the
        # importer raised; the original error stays visible as the cause.
        raise ImportError("Lace 的 Manim 封装需要安装可选依赖：pip install 'manim-lace[manim]'") from exc
    return Lace


def __dir__() -> list[str]:
    """List the lazily loaded facade as well, so introspection matches reality."""
    names = set(globals())
    if _MANIM_AVAILABLE:
        names.add("Lace")
    return sorted(names)
