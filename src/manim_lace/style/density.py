"""Density-aware visual simplification (SPEC §9 "密集交叉区域的视觉简化").

Two halves, deliberately separated:

* :func:`analyze_density` only *measures*: it buckets crossings into a uniform
  grid and groups crossings that sit within ``cluster_radius`` of each other.
  It is read-only and safe to call on any result, including for debug overlays.
* :func:`simplify_for_density` *decides what to stop drawing*: inside a dense
  cluster it hides visible slivers shorter than a threshold, because at that
  scale they read as noise rather than as lace. Everything it hides is listed in
  ``dropped_ids`` and reported through ``RENDER-DENSITY-SIMPLIFIED``; crossings,
  assignments and the geometry the engine produced stay exactly as they were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..diagnostics import Diagnostic, Severity

__all__ = [
    "DensityCluster",
    "DensityPolicy",
    "DensityReport",
    "DensitySimplification",
    "analyze_density",
    "simplify_for_density",
]

#: Default cluster radius and grid cell size, as a fraction of the pattern's
#: bounding-box diagonal (so the defaults follow the drawing's scale).
DEFAULT_CLUSTER_FRACTION = 0.05
#: How many real clusters (of at least ``min_cluster_size`` crossings) make a
#: pattern "dense" in :attr:`DensityReport.is_dense`.
DEFAULT_MIN_CLUSTER_SIZE = 3


def _object_id(item: Any) -> str:
    identifier = getattr(item, "piece_id", None) or getattr(item, "region_id", None)
    if identifier is None:
        raise ValueError(f"unsupported piece object without piece_id/region_id: {type(item).__name__}")
    return str(identifier)


def _pattern_diagonal(result: Any) -> float:
    """A scale for the pattern: the diagonal of the visible geometry's bbox."""
    chunks: list[np.ndarray] = []
    for piece in getattr(result, "pieces", []) or []:
        points = getattr(piece, "points", None)
        if points is None:
            exterior = getattr(piece, "exterior", None)
            points = getattr(exterior, "points", None) if exterior is not None else None
        if points is not None and len(points):
            chunks.append(np.asarray(points, dtype=float)[:, :2])
    if not chunks:
        for path in getattr(result, "paths", []) or []:
            points = np.asarray(path.points, dtype=float)[:, :2]
            if len(points):
                chunks.append(points)
    if not chunks:
        return 0.0
    stacked = np.vstack(chunks)
    extent = stacked.max(axis=0) - stacked.min(axis=0)
    return float(np.hypot(extent[0], extent[1]))


def _polyline_midpoint(points: np.ndarray) -> np.ndarray:
    """The point half-way along a polyline, by arc length."""
    array = np.asarray(points, dtype=float)[:, :2]
    if len(array) == 1:
        return array[0]
    lengths = np.linalg.norm(np.diff(array, axis=0), axis=1)
    total = float(lengths.sum())
    if total <= 0:
        return array[0]
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    index = int(np.searchsorted(cumulative, total / 2.0, side="right") - 1)
    index = int(np.clip(index, 0, len(lengths) - 1))
    segment = lengths[index]
    ratio = (total / 2.0 - cumulative[index]) / segment if segment > 0 else 0.0
    return array[index] + ratio * (array[index + 1] - array[index])


@dataclass(frozen=True, slots=True)
class DensityCluster:
    """A group of crossings that sit closer to each other than ``cluster_radius``."""

    cluster_id: str
    crossing_ids: tuple[str, ...]
    centroid: tuple[float, float]
    radius: float
    cell: tuple[int, int]

    @property
    def size(self) -> int:
        return len(self.crossing_ids)


@dataclass(frozen=True, slots=True)
class DensityReport:
    """Where the crossings crowd together, and by how much."""

    cell_size: float
    cluster_radius: float
    crossing_count: int
    cell_counts: dict[tuple[int, int], int] = field(default_factory=dict)
    clusters: tuple[DensityCluster, ...] = ()
    points: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def max_per_cell(self) -> int:
        """How many crossings the busiest grid cell holds (0 when there are none)."""
        return max(self.cell_counts.values(), default=0)

    def cell_count(self, cell: tuple[int, int]) -> int:
        return int(self.cell_counts.get((int(cell[0]), int(cell[1])), 0))

    def hotspots(self, limit: int = 5) -> tuple[tuple[tuple[int, int], int], ...]:
        """The busiest cells, most crowded first, deterministic on ties."""
        ordered = sorted(self.cell_counts.items(), key=lambda item: (-item[1], item[0]))
        return tuple(ordered[: max(0, int(limit))])

    @property
    def dense_crossing_ids(self) -> frozenset[str]:
        """Every crossing that belongs to a cluster."""
        return frozenset(
            crossing_id for cluster in self.clusters for crossing_id in cluster.crossing_ids
        )

    @property
    def is_dense(self) -> bool:
        """Whether the pattern has at least one cluster worth simplifying."""
        return bool(self.clusters)


def _cluster_cell(point: tuple[float, float], size: float) -> tuple[int, int]:
    return int(np.floor(point[0] / size)), int(np.floor(point[1] / size))


def analyze_density(
    result: Any,
    *,
    cell_size: float | None = None,
    cluster_radius: float | None = None,
    min_cluster_size: int = 2,
) -> DensityReport:
    """Measure the crossing density of a solved ``result``.

    Crossings are bucketed into a uniform grid of side ``cell_size`` and merged
    into clusters whenever two crossings are closer than ``cluster_radius``
    (neighbour lookups only visit the 3x3 surrounding cells, so this stays linear
    in the crossing count).

    ``cell_size`` and ``cluster_radius`` default to
    ``2 *`` and ``1 *`` :data:`DEFAULT_CLUSTER_FRACTION` of the visible geometry's
    bounding-box diagonal; pass explicit world-space values when the pattern is
    unusually elongated. ``min_cluster_size`` is the smallest cluster that is
    reported at all.

    Raises ``ValueError`` for a non-positive scale or ``min_cluster_size < 2``.
    """
    if min_cluster_size < 2 or isinstance(min_cluster_size, bool):
        raise ValueError(f"min_cluster_size must be an integer >= 2; got {min_cluster_size!r}")
    diagonal = _pattern_diagonal(result)
    if cluster_radius is None:
        cluster_radius = DEFAULT_CLUSTER_FRACTION * diagonal
    if cell_size is None:
        cell_size = 2.0 * cluster_radius
    if not np.isfinite(cluster_radius) or cluster_radius <= 0:
        raise ValueError(f"cluster_radius must be positive and finite; got {cluster_radius!r}")
    if not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError(f"cell_size must be positive and finite; got {cell_size!r}")

    crossings = list(getattr(result, "crossings", []) or [])
    points = {crossing.crossing_id: (float(crossing.point[0]), float(crossing.point[1])) for crossing in crossings}
    cell_counts: dict[tuple[int, int], int] = {}
    radius_cells: dict[tuple[int, int], list[str]] = {}
    for crossing_id, point in points.items():
        cell_counts[_cluster_cell(point, cell_size)] = cell_counts.get(_cluster_cell(point, cell_size), 0) + 1
        radius_cells.setdefault(_cluster_cell(point, cluster_radius), []).append(crossing_id)

    seen: set[str] = set()
    clusters: list[DensityCluster] = []
    for crossing_id in points:  # insertion order == deterministic crossing order
        if crossing_id in seen:
            continue
        point = points[crossing_id]
        base_cell = _cluster_cell(point, cluster_radius)
        members: list[str] = []
        stack = [crossing_id]
        seen.add(crossing_id)
        while stack:
            current = stack.pop()
            members.append(current)
            current_point = np.asarray(points[current], dtype=float)
            cell = _cluster_cell(current_point, cluster_radius)
            for dx in (cell[0] - 1, cell[0], cell[0] + 1):
                for dy in (cell[1] - 1, cell[1], cell[1] + 1):
                    for candidate in radius_cells.get((dx, dy), ()):
                        if candidate in seen:
                            continue
                        if float(np.linalg.norm(np.asarray(points[candidate]) - current_point)) <= cluster_radius:
                            seen.add(candidate)
                            stack.append(candidate)
        members.sort()
        if len(members) < min_cluster_size:
            continue
        coords = np.asarray([points[member] for member in members], dtype=float)
        centroid = coords.mean(axis=0)
        spread = float(np.max(np.linalg.norm(coords - centroid, axis=1)))
        clusters.append(
            DensityCluster(
                cluster_id=f"C{len(clusters):03d}",
                crossing_ids=tuple(members),
                centroid=(float(centroid[0]), float(centroid[1])),
                radius=spread,
                cell=base_cell,
            )
        )
    clusters.sort(key=lambda cluster: (-cluster.size, cluster.cluster_id))
    return DensityReport(
        cell_size=float(cell_size),
        cluster_radius=float(cluster_radius),
        crossing_count=len(points),
        cell_counts=cell_counts,
        clusters=tuple(clusters),
        points=points,
    )


@dataclass(frozen=True, slots=True)
class DensityPolicy:
    """How aggressively dense areas are simplified.

    ``sliver_length`` is an absolute arc length; when it is ``None`` the threshold
    is ``sliver_fraction * cluster_radius`` of the report, so it scales with the
    drawing.
    """

    enabled: bool = True
    cluster_radius: float | None = None
    cell_size: float | None = None
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE
    sliver_length: float | None = None
    sliver_fraction: float = 0.25

    def __post_init__(self) -> None:
        for name in ("cluster_radius", "cell_size"):
            value = getattr(self, name)
            if value is not None and (not np.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be positive and finite or None; got {value!r}")
        if self.sliver_length is not None and (not np.isfinite(self.sliver_length) or self.sliver_length <= 0):
            raise ValueError(
                f"sliver_length must be positive and finite or None; got {self.sliver_length!r}"
            )
        if not np.isfinite(self.sliver_fraction) or self.sliver_fraction <= 0:
            raise ValueError(
                f"sliver_fraction must be positive and finite; got {self.sliver_fraction!r}"
            )
        if not isinstance(self.min_cluster_size, int) or isinstance(self.min_cluster_size, bool) or self.min_cluster_size < 2:
            raise ValueError(f"min_cluster_size must be an integer >= 2; got {self.min_cluster_size!r}")

    def threshold(self, report: DensityReport) -> float:
        """The arc length below which a piece inside a cluster is simplified away."""
        if self.sliver_length is not None:
            return float(self.sliver_length)
        return float(self.sliver_fraction) * report.cluster_radius


@dataclass(frozen=True, slots=True)
class DensitySimplification:
    """What the density policy decided to draw, and what it decided to hide."""

    report: DensityReport
    policy: DensityPolicy
    threshold: float
    kept_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...]
    applied: bool
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def dropped_count(self) -> int:
        return len(self.dropped_ids)

    def kept(self, result: Any) -> list[Any]:
        """The piece objects to draw, in the geometry's own draw order."""
        keep = set(self.kept_ids)
        pieces = [piece for piece in getattr(result, "pieces", []) or [] if _object_id(piece) in keep]
        return sorted(
            pieces,
            key=lambda piece: (
                getattr(piece, "draw_index", 0),
                str(getattr(piece, "piece_id", None) or getattr(piece, "region_id", "")),
            ),
        )


def simplify_for_density(result: Any, policy: DensityPolicy) -> DensitySimplification:
    """Hide visible slivers that sit inside dense crossing clusters.

    The rule is deliberately narrow: a piece is only hidden when its midpoint is
    inside a cluster *and* its arc length is below the policy's threshold. So a
    long strand passing through a dense area is never touched, and the topology,
    the crossings and the engine's own geometry are left exactly as they were —
    the caller decides what to draw using :meth:`DensitySimplification.kept`.

    Region (ribbon) results are not simplified: there the cut is real geometry, so
    the simplification is skipped and reported instead of silently doing nothing.

    Raises ``ValueError`` when ``policy`` is not a :class:`DensityPolicy`.
    """
    if not isinstance(policy, DensityPolicy):
        raise ValueError(f"policy must be a DensityPolicy; got {type(policy).__name__}")
    report = analyze_density(
        result,
        cell_size=policy.cell_size,
        cluster_radius=policy.cluster_radius,
        min_cluster_size=policy.min_cluster_size,
    )
    pieces = list(getattr(result, "pieces", []) or [])
    threshold = policy.threshold(report)
    all_ids = tuple(_object_id(piece) for piece in pieces)
    if not policy.enabled or not report.clusters or not pieces:
        return DensitySimplification(
            report=report,
            policy=policy,
            threshold=threshold,
            kept_ids=all_ids,
            dropped_ids=(),
            applied=False,
        )
    if not hasattr(pieces[0], "arc_start"):
        return DensitySimplification(
            report=report,
            policy=policy,
            threshold=threshold,
            kept_ids=all_ids,
            dropped_ids=(),
            applied=False,
            diagnostics=(
                Diagnostic(
                    code="RENDER-DENSITY-SKIPPED",
                    severity=Severity.INFO,
                    message=(
                        f"密度简化跳过：{getattr(result, 'render_mode', 'ribbon')} 后端的切口是真实几何，"
                        "只对描边片段按弧长简化。"
                    ),
                    details={
                        "pieces": len(pieces),
                        "clusters": len(report.clusters),
                        "render_mode": str(getattr(result, "render_mode", "")),
                    },
                    hints=("ribbon 模式可用调色板与边框做视觉层次，而不是丢片段。",),
                ),
            ),
        )

    cluster_points = [
        np.asarray([report.points[crossing_id] for crossing_id in cluster.crossing_ids], dtype=float)
        for cluster in report.clusters
    ]
    kept: list[str] = []
    dropped: list[str] = []
    for piece in pieces:
        object_id = _object_id(piece)
        length = float(getattr(piece, "arc_end", 0.0)) - float(getattr(piece, "arc_start", 0.0))
        midpoint = _polyline_midpoint(np.asarray(piece.points, dtype=float))
        in_cluster = any(
            bool(np.min(np.linalg.norm(points - midpoint, axis=1)) <= report.cluster_radius)
            for points in cluster_points
        )
        if in_cluster and length < threshold:
            dropped.append(object_id)
        else:
            kept.append(object_id)
    if not dropped:
        return DensitySimplification(
            report=report,
            policy=policy,
            threshold=threshold,
            kept_ids=tuple(kept),
            dropped_ids=(),
            applied=False,
        )
    return DensitySimplification(
        report=report,
        policy=policy,
        threshold=threshold,
        kept_ids=tuple(kept),
        dropped_ids=tuple(dropped),
        applied=True,
        diagnostics=(
            Diagnostic(
                code="RENDER-DENSITY-SIMPLIFIED",
                severity=Severity.INFO,
                message=(
                    f"密集交叉区视觉简化：{len(dropped)} 个短于 {threshold:g} 的可见片段未绘制"
                    f"（{len(report.clusters)} 个密集簇，簇半径 {report.cluster_radius:g}）。"
                ),
                details={
                    "dropped_ids": list(dropped),
                    "dropped_count": len(dropped),
                    "threshold": threshold,
                    "cluster_count": len(report.clusters),
                    "cluster_radius": report.cluster_radius,
                    "cell_size": report.cell_size,
                    "crossing_count": report.crossing_count,
                },
                hints=(
                    "交叉与上下关系未被改动；这只影响哪些片段被绘制。",
                    "调小 sliver_fraction/sliver_length 或关闭 enabled 可保留全部片段。",
                ),
            ),
        ),
    )
