"""Core data models. This module intentionally does not import Manim."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from .diagnostics import Diagnostic

FloatArray = NDArray[np.float64]
CrossingKind = Literal[
    "transverse",
    "near_tangent",
    "endpoint_touch",
    "overlap",
    "multiway",
    "uncertain",
]


@dataclass(frozen=True, slots=True)
class PathSource:
    """Metadata that ties a normalized path back to its source object."""

    object_type: str = "array"
    object_label: str | None = None
    subpath_index: int = 0
    parameter_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolylinePath:
    """An ordered 2D polyline with an optional mapping to source parameters.

    Closed paths should repeat the first point as the last point. The explicit
    duplicate makes arc-length and renderer behavior unambiguous.
    """

    points: FloatArray
    path_id: str = "P0000"
    closed: bool = False
    source: PathSource = field(default_factory=PathSource)
    parameters: FloatArray | None = None
    sampling_error: float | None = None

    def __post_init__(self) -> None:
        arr = np.asarray(self.points, dtype=float)
        if arr.ndim != 2 or arr.shape[1] not in (2, 3):
            raise ValueError(f"points must have shape (N, 2) or (N, 3); got {arr.shape}")
        if arr.shape[1] == 3 and len(arr) and float(np.ptp(arr[:, 2])) > 1e-6:
            raise ValueError(
                "PolylinePath only models 2D paths in an XY-parallel plane; "
                "explicitly project non-planar input before constructing it"
            )
        arr = arr[:, :2].copy()
        if len(arr) < 2:
            raise ValueError("a path must contain at least two points")
        if not np.isfinite(arr).all():
            raise ValueError("PolylinePath contains non-finite points; split paths at discontinuities first")
        original_count = len(arr)
        appended_closure = False
        if self.closed:
            if np.allclose(arr[0], arr[-1], atol=1e-6):
                arr[-1] = arr[0]
            else:
                arr = np.vstack((arr, arr[0]))
                appended_closure = True
        self.points = arr
        if self.parameters is not None:
            params = np.asarray(self.parameters, dtype=float)
            if params.ndim != 1:
                raise ValueError("parameters must be one-dimensional")
            if appended_closure and len(params) == original_count:
                params = np.append(params, params[-1])
            if len(params) != len(arr):
                raise ValueError("parameters must be one-dimensional and match the point count")
            self.parameters = params.copy()
        else:
            self.parameters = None
        # A repeated endpoint is the canonical representation of a closed path.
        if len(arr) > 2 and np.allclose(arr[0], arr[-1], atol=1e-6):
            arr[-1] = arr[0]
            self.closed = True

    @property
    def segment_lengths(self) -> FloatArray:
        return np.linalg.norm(np.diff(self.points, axis=0), axis=1)

    @property
    def cumulative_lengths(self) -> FloatArray:
        return np.concatenate(([0.0], np.cumsum(self.segment_lengths)))

    @property
    def length(self) -> float:
        return float(self.cumulative_lengths[-1])

    @property
    def segment_count(self) -> int:
        return max(0, len(self.points) - 1)


@dataclass(frozen=True, slots=True)
class CrossingEvent:
    """One geometric crossing candidate and the two path passes through it."""

    crossing_id: str
    kind: CrossingKind
    point: tuple[float, float]
    path_a: str
    path_b: str
    path_index_a: int
    path_index_b: int
    s_a: float
    s_b: float
    segment_a: int
    segment_b: int
    u_a: float
    u_b: float
    sin_angle: float


@dataclass(frozen=True, slots=True)
class Pass:
    """One visit to a crossing, ordered along one path."""

    crossing_id: str
    path_id: str
    side: Literal["a", "b"]
    arc_length: float
    position: int


@dataclass(frozen=True, slots=True)
class WeaveAssignment:
    """Which side of a crossing is visually on top."""

    crossing_id: str
    over_side: Literal["a", "b"]
    under_side: Literal["a", "b"]
    source: Literal["alternating", "manual", "free"]
    explanation: str = ""


@dataclass(slots=True)
class WeaveTopology:
    crossings: list[CrossingEvent]
    passes_by_path: dict[str, list[Pass]]
    assignments: dict[str, WeaveAssignment]
    mode: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def assignment_for(self, crossing_id: str) -> WeaveAssignment | None:
        return self.assignments.get(crossing_id)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """A deterministic record of an actual algorithm step."""

    sequence: int
    stage: str
    event_type: str
    message: str
    object_ids: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LaceResult:
    paths: list[PolylinePath]
    crossings: list[CrossingEvent]
    topology: WeaveTopology
    pieces: list[Any]
    diagnostics: list[Diagnostic]
    trace: list[TraceEvent]
    render_mode: str = "stroke"
