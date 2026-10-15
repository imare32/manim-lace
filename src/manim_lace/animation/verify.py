"""Verify that animation coordinates and IDs match the final geometry.

The animation layer highlights crossing events with dots and labels at
``crossing.point`` coordinates. The render layer cuts stroke pieces and builds
regions using the same ``CrossingEvent`` objects, but the coordinates it uses
for cutting are the crossing points too. This module verifies that the two
layers share the same coordinates and crossing IDs, so a highlight dot in the
animation is exactly where the final geometry made its cut.

This is the M5 milestone item "Verify animation highlights are at the same
coordinates and IDs as final geometry."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..model import LaceResult

__all__ = ["CoordConsistency", "verify_coordinate_consistency"]


@dataclass(frozen=True, slots=True)
class CoordConsistency:
    """Result of checking that animation and geometry share coordinates and IDs.

    ``consistent`` is ``True`` when every crossing ID in the trace's
    ``crossing.detected`` events matches a crossing in ``result.crossings``,
    and the point recorded in the trace data matches the crossing's ``point``
    to within tolerance. ``mismatches`` lists the ones that disagree, each with
    the crossing ID, the traced point, and the canonical point.
    """

    consistent: bool
    crossing_ids_in_trace: tuple[str, ...] = ()
    crossing_ids_in_result: tuple[str, ...] = ()
    mismatches: list[dict[str, Any]] = field(default_factory=list)


def verify_coordinate_consistency(
    result: LaceResult,
    *,
    tol: float = 1e-9,
) -> CoordConsistency:
    """Check that every traced crossing matches the final geometry.

    Parameters
    ----------
    result:
        The solved :class:`LaceResult` whose trace and crossings are to be
        compared.
    tol:
        Maximum Euclidean distance between the traced point and the crossing's
        canonical point for them to be considered the same.

    Returns
    -------
    CoordConsistency
        A report on whether the trace and the result agree. If the trace does
        not record crossing points (e.g. for a degenerate path with no
        crossings), the result is trivially consistent with empty ID sets.
    """
    canonical: dict[str, tuple[float, float]] = {
        crossing.crossing_id: crossing.point for crossing in result.crossings
    }
    traced_ids: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for event in result.trace:
        if event.event_type != "crossing.detected":
            continue
        data = event.data
        crossing_id = ""
        for obj_id in event.object_ids:
            if obj_id.startswith("X"):
                crossing_id = obj_id
                break
        if not crossing_id:
            continue
        traced_ids.append(crossing_id)
        canonical_point = canonical.get(crossing_id)
        if canonical_point is None:
            mismatches.append(
                {
                    "crossing_id": crossing_id,
                    "reason": "crossing ID in trace but not in result.crossings",
                }
            )
            continue
        traced_point = data.get("point")
        if traced_point is None:
            continue
        tp = (float(traced_point[0]), float(traced_point[1]))
        cp = (float(canonical_point[0]), float(canonical_point[1]))
        dx = tp[0] - cp[0]
        dy = tp[1] - cp[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > tol:
            mismatches.append(
                {
                    "crossing_id": crossing_id,
                    "traced_point": tp,
                    "canonical_point": cp,
                    "distance": dist,
                }
            )
    result_ids = tuple(sorted(canonical))
    traced_unique = tuple(sorted(set(traced_ids)))
    consistent = len(mismatches) == 0 and traced_unique == result_ids
    return CoordConsistency(
        consistent=consistent,
        crossing_ids_in_trace=traced_unique,
        crossing_ids_in_result=result_ids,
        mismatches=mismatches,
    )
