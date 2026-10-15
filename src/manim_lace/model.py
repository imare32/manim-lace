"""Core data models. This module intentionally does not import Manim."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from .diagnostics import Diagnostic

FloatArray = NDArray[np.float64]
#: Evaluates the underlying source curve at a source parameter and returns ``(x, y)``.
#: The parameter space must be the same one stored in ``PolylinePath.parameters``.
CurveProbe = Callable[[float], Any]
CrossingKind = Literal[
    "transverse",
    "near_tangent",
    "endpoint_touch",
    "overlap",
    "multiway",
    "uncertain",
]
#: What to do with a contact event that is not an ordinary transverse crossing.
#: ``diagnose`` (default) keeps the classification and reports it, ``weave`` promotes
#: a point-like contact into an ordinary crossing so it enters the over/under solver,
#: and ``ignore`` keeps the geometry but drops the warning.
ContactPolicy = Literal["diagnose", "weave", "ignore"]
#: What to do with events that can never be a single binary crossing (a collinear
#: overlap is an interval, a multiway node has more than two strands).
ClusterPolicy = Literal["diagnose", "ignore"]
#: How to resolve a conflict between the user's over sides and automatic alternation
#: (SPEC FR-045). See ``topology.solver.solve_weave`` for the exact contract.
ConflictStrategy = Literal["error", "manual", "relax"]
#: Stroke end-cap style of the rendered pieces. ``butt`` ends exactly at the cut,
#: ``round`` and ``square`` protrude half the ribbon width along the tangent, which the
#: renderer compensates for by widening the gap (a visual approximation, reported).
CapStyle = Literal["butt", "round", "square"]
#: How the ribbon-region backend connects offset segments at a polyline vertex
#: (SPEC FR-053). ``miter`` is limited by ``miter_limit``.
JoinStyle = Literal["miter", "bevel", "round"]


@dataclass(frozen=True, slots=True)
class EventPolicy:
    """How the detector treats crossing candidates that are not plain crossings.

    The default keeps every event classified as detected and reports a warning for
    the ones the weave solver will not use, so nothing is silent. ``weave`` is only
    meaningful for the point-like contact events: an overlap is an interval and a
    multiway node has more than two strands, so neither can become one binary
    crossing.
    """

    endpoint_touch: ContactPolicy = "diagnose"
    near_tangent: ContactPolicy = "diagnose"
    collinear_overlap: ClusterPolicy = "diagnose"
    multiway: ClusterPolicy = "diagnose"

    def __post_init__(self) -> None:
        for name in ("endpoint_touch", "near_tangent"):
            value = getattr(self, name)
            if value not in ("diagnose", "weave", "ignore"):
                raise ValueError(
                    f"event policy {name} must be 'diagnose', 'weave' or 'ignore'; got {value!r}"
                )
        for name in ("collinear_overlap", "multiway"):
            value = getattr(self, name)
            if value not in ("diagnose", "ignore"):
                raise ValueError(
                    f"event policy {name} must be 'diagnose' or 'ignore'; got {value!r}"
                )

    @property
    def contact_fields(self) -> tuple[str, ...]:
        return ("endpoint_touch", "near_tangent")


def normalize_event_policy(
    policy: EventPolicy | Mapping[str, str] | str | None,
) -> EventPolicy:
    """Accept the explicit object, a partial mapping, or one value for everything."""
    if policy is None:
        return EventPolicy()
    if isinstance(policy, EventPolicy):
        return policy
    if isinstance(policy, str):
        return EventPolicy(
            endpoint_touch=policy,  # type: ignore[arg-type]
            near_tangent=policy,  # type: ignore[arg-type]
            collinear_overlap=policy,  # type: ignore[arg-type]
            multiway=policy,  # type: ignore[arg-type]
        )
    if isinstance(policy, Mapping):
        unknown = sorted(set(policy) - set(EventPolicy.__dataclass_fields__))
        if unknown:
            raise ValueError(
                f"event policy has no such field(s): {unknown}; "
                f"expected any of {sorted(EventPolicy.__dataclass_fields__)}"
            )
        return EventPolicy(**{str(key): str(value) for key, value in policy.items()})  # type: ignore[arg-type]
    raise ValueError(
        "event_policy must be an EventPolicy, a mapping of field names to values, "
        f"a single policy value, or None; got {type(policy).__name__}"
    )


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

    ``curve`` optionally retains an evaluator of the smooth source curve in the
    same parameter space as ``parameters``. It is used for local crossing
    refinement (SPEC FR-036) and is never required: a path built from plain
    coordinates simply has no probe and keeps the sampled-polyline estimate.
    """

    points: FloatArray
    path_id: str = "P0000"
    closed: bool = False
    source: PathSource = field(default_factory=PathSource)
    parameters: FloatArray | None = None
    sampling_error: float | None = None
    curve: CurveProbe | None = None

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
    """One geometric crossing candidate and the two path passes through it.

    ``segment_*``/``u_*`` locate the crossing inside the sampled polyline.
    ``parameter_a``/``parameter_b`` are the source-curve parameters; they are
    reported when the crossing was refined on the source curve (``refined``), so
    animation and diagnostics can point back at the original curve (SPEC FR-022).
    """

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
    refined: bool = False
    parameter_a: float | None = None
    parameter_b: float | None = None


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
    """Which side of a crossing is visually on top.

    ``source`` records where the decision came from: ``alternating`` (path-wise
    alternation), ``manual`` (an explicit user side), ``free`` (free-mode default) or
    ``relaxed`` (strict alternation had no solution and this crossing was relaxed by
    the declared conflict strategy).
    """

    crossing_id: str
    over_side: Literal["a", "b"]
    under_side: Literal["a", "b"]
    source: Literal["alternating", "manual", "free", "relaxed"]
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
class CrossingStats:
    """Observable counters for candidate pruning and the crossing narrow phase."""

    strategy: str
    segment_count: int
    candidate_pairs: int
    pair_checks: int
    grid_cells: int
    refined_events: int = 0

    @property
    def all_pairs(self) -> int:
        """Number of pairs a brute-force detector would consider."""
        return self.segment_count * (self.segment_count - 1) // 2


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
    detection_stats: CrossingStats | None = None
