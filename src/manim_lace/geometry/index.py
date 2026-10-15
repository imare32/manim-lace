"""Deterministic candidate index for line-segment intersection tests.

The index only *prunes* candidate pairs: every returned pair still goes through
the exact segment test in :mod:`manim_lace.geometry.intersections`. Results are
therefore independent of the acceleration structure (SPEC FR-035), and the
traversal order never depends on hash or dictionary order (SPEC FR-075).

The structure is a uniform grid over expanded segment bounding boxes:

* boxes are expanded by the caller's positional tolerance, so the broad phase is
  a superset of the narrow-phase bounding-box test used by the brute-force loop;
* the cell size is derived from the input extent only, so the same geometry
  always yields the same cells and the same pair list;
* the cell size never falls below the mean segment extent, which keeps the
  average insertion count per segment bounded. Segments that are much longer
  than the average may still span many cells; that costs time, never correctness.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Upper bound for the grid resolution along one axis. Together with the mean
#: segment extent this bounds memory for inputs that mix tiny and huge segments.
MAX_CELLS_PER_AXIS = 128


def all_pairs(segment_count: int) -> list[tuple[int, int]]:
    """Brute-force candidate list used as the reference implementation."""
    return [
        (first, second)
        for first in range(segment_count)
        for second in range(first + 1, segment_count)
    ]


@dataclass(frozen=True, slots=True)
class CandidatePairs:
    """Candidate pairs plus the counters needed for diagnostics."""

    pairs: list[tuple[int, int]]
    grid_cells: int


class SegmentCandidateIndex:
    """Uniform grid storing, for each cell, the segments whose box touches it."""

    __slots__ = ("_boxes_min", "_boxes_max", "_cell_size", "_origin")

    def __init__(
        self,
        boxes_min: np.ndarray,
        boxes_max: np.ndarray,
        *,
        cell_size: float,
        origin: np.ndarray,
    ) -> None:
        self._boxes_min = boxes_min
        self._boxes_max = boxes_max
        self._cell_size = float(cell_size)
        self._origin = origin

    @classmethod
    def build(
        cls,
        boxes_min: np.ndarray,
        boxes_max: np.ndarray,
        *,
        expansion: float,
    ) -> SegmentCandidateIndex:
        """Expand the boxes by ``expansion`` and derive a deterministic cell size."""
        expanded_min = boxes_min - expansion
        expanded_max = boxes_max + expansion
        origin = expanded_min.min(axis=0)
        extent = np.maximum(expanded_max.max(axis=0) - origin, 0.0)
        diagonal = float(np.linalg.norm(extent))
        mean_extent = float(np.mean(expanded_max - expanded_min))
        cell_size = max(mean_extent, diagonal / MAX_CELLS_PER_AXIS)
        if not np.isfinite(cell_size) or cell_size <= 0:
            cell_size = max(diagonal, 1.0)
        return cls(expanded_min, expanded_max, cell_size=cell_size, origin=origin)

    @property
    def cell_size(self) -> float:
        return self._cell_size

    def candidates(self) -> CandidatePairs:
        """Return sorted ``(lower, higher)`` pairs that share at least one cell."""
        index_min = np.floor((self._boxes_min - self._origin) / self._cell_size).astype(np.int64)
        index_max = np.floor((self._boxes_max - self._origin) / self._cell_size).astype(np.int64)
        cells: dict[tuple[int, int], list[int]] = {}
        for segment in range(len(self._boxes_min)):
            for column in range(int(index_min[segment, 0]), int(index_max[segment, 0]) + 1):
                for row in range(int(index_min[segment, 1]), int(index_max[segment, 1]) + 1):
                    # Segments are visited in ascending index order, so every
                    # member list stays sorted and pairs are already (lower, higher).
                    cells.setdefault((column, row), []).append(segment)
        pairs: set[tuple[int, int]] = set()
        for members in cells.values():
            if len(members) < 2:
                continue
            for position, first in enumerate(members):
                for second in members[position + 1:]:
                    pairs.add((first, second))
        return CandidatePairs(pairs=sorted(pairs), grid_cells=len(cells))


def neighbourhood_clusters(points: np.ndarray, radius: float) -> list[list[int]]:
    """Group point indices into non-transitive neighbourhood clusters.

    Roots are taken in ascending index order. A cluster holds the root plus every
    *still unvisited* index within ``radius`` of the root point, listed in
    ascending order. The relation is deliberately not transitive: a chain of
    merely-nearby points must not be collapsed into one cluster (SPEC FR-034).

    Bucketing the points by ``radius``-sized cells makes the scan proportional to
    the local point density instead of ``len(points) ** 2``, which matters because
    dense weave patterns produce many crossings.
    """
    total = len(points)
    if total == 0:
        return []
    cell = radius if radius > 0 else 1.0
    buckets: dict[tuple[int, int], list[int]] = {}
    for index in range(total):
        key = (int(np.floor(points[index, 0] / cell)), int(np.floor(points[index, 1] / cell)))
        buckets.setdefault(key, []).append(index)
    visited = [False] * total
    clusters: list[list[int]] = []
    for root in range(total):
        if visited[root]:
            continue
        visited[root] = True
        root_point = points[root]
        column = int(np.floor(root_point[0] / cell))
        row = int(np.floor(root_point[1] / cell))
        members: list[int] = []
        for neighbour_column in (column - 1, column, column + 1):
            for neighbour_row in (row - 1, row, row + 1):
                for index in buckets.get((neighbour_column, neighbour_row), ()):
                    if visited[index]:
                        continue
                    # Compare with np.linalg.norm, not with squared values: for
                    # rounded coordinates the two disagree exactly at the radius,
                    # and cluster membership decides the event kind.
                    if float(np.linalg.norm(points[index] - root_point)) <= radius:
                        visited[index] = True
                        members.append(index)
        members.sort()
        clusters.append([root, *members])
    return clusters
