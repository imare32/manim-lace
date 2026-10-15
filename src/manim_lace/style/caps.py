"""Cut-end treatments: end-cap outlines and the "cover allowance" contract.

Two different things live behind "cut-end treatment":

* **Cover allowance** — a *geometry* knob. It shortens the gap at an underpass by
  ``cover_allowance * offset`` on each side, so the end of a lower strand tucks a
  little further under the strand on top of it. It may only eat slack the cut
  already has (the engine's ``overshoot``), so a visible end can never reach past
  the true crossing: ``0 <= cover_allowance <= overshoot``. The stroke backend
  implements it through :func:`trim_cut_half_length` and reports
  ``RENDER-COVER-ALLOWANCE``.
* **End-cap outline** — a *geometry read-out*. :func:`stroke_piece_outline` turns a
  visible piece into the closed polygon a stroked ribbon would cover (butt,
  square and round caps included), so callers that need the real outline no longer
  have to guess it. It is pure NumPy, so the stroke channel stays Shapely-free.

Neither helper changes crossings or the over/under solution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..model import CapStyle

__all__ = [
    "DEFAULT_MITER_LIMIT",
    "CapTreatment",
    "PieceOutline",
    "stroke_piece_outline",
    "trim_cut_half_length",
    "validate_cover_allowance",
]

#: Miter limit used when the caller does not forward the engine's own.
DEFAULT_MITER_LIMIT = 5.0
#: Tolerance for treating two consecutive points as the same point.
_POINT_TOL = 1e-12


def validate_cover_allowance(allowance: float, overshoot: float) -> float:
    """Check the cover-allowance contract and return ``allowance`` as a float.

    ``overshoot`` is the slack the cut already contains, in the same unit as
    ``allowance`` (both are multiples of ``offset``), so ``allowance > overshoot``
    would push the visible end past the true crossing and is rejected here.
    """
    if not np.isfinite(allowance) or allowance < 0:
        raise ValueError(f"cover_allowance must be finite and non-negative; got {allowance!r}")
    if not np.isfinite(overshoot) or overshoot < 0:
        raise ValueError(f"overshoot must be finite and non-negative; got {overshoot!r}")
    if allowance > overshoot + 1e-12:
        raise ValueError(
            f"cover_allowance {allowance!r} exceeds overshoot {overshoot!r}: the cut has no slack "
            "that large, so the visible end would reach past the true crossing"
        )
    return float(allowance)


def trim_cut_half_length(radius: float, *, allowance: float, offset: float) -> float:
    """The cut half-length after the cover allowance tucks both ends under.

    ``radius`` is the half-length the stroke backend would cut (already including
    its overshoot and any cap compensation). Trimming happens *before* the cut is
    clamped to the path ends and wrapped around the seam, because the clamp
    depends on the untrimmed value.
    """
    return float(radius) - float(allowance) * float(offset)


def _shoelace(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _close(points: np.ndarray) -> np.ndarray:
    """Append the first point if needed and drop consecutive duplicates."""
    array = np.asarray(points, dtype=float)
    keep = [array[0]]
    for point in array[1:]:
        if np.linalg.norm(point - keep[-1]) > _POINT_TOL:
            keep.append(point)
    if np.linalg.norm(keep[-1] - keep[0]) > _POINT_TOL:
        keep.append(keep[0])
    else:
        keep[-1] = keep[0]
    if len(keep) < 4:
        raise ValueError("an outline ring needs at least three distinct points")
    return np.asarray(keep)


def _orient(points: np.ndarray, *, counter_clockwise: bool) -> np.ndarray:
    """Return the ring closed and with the requested orientation."""
    ring = _close(points)
    if (_shoelace(ring) > 0) is not counter_clockwise:
        ring = _close(ring[::-1])
    return ring


def _dedupe(points: np.ndarray) -> np.ndarray:
    array = np.asarray(points, dtype=float)
    keep = [array[0]]
    for point in array[1:]:
        if np.linalg.norm(point - keep[-1]) > _POINT_TOL:
            keep.append(point)
    return np.asarray(keep)


def _offset_side(points: np.ndarray, distance: float, *, miter_limit: float) -> np.ndarray:
    """Offset an open polyline to its left (``distance > 0``) or to its right.

    Interior vertices use a miter join, replaced by a bevel when the miter would
    grow past ``miter_limit`` times the offset. End points move along the end
    normal, so a caller that wants square caps extends the centerline first.
    """
    if len(points) < 2:
        raise ValueError("cannot offset a polyline with fewer than two points")
    segments = np.diff(points, axis=0)
    lengths = np.linalg.norm(segments, axis=1)
    if float(np.min(lengths)) <= _POINT_TOL:
        raise ValueError("cannot offset a polyline with a zero-length segment")
    directions = segments / lengths[:, None]
    normals = np.column_stack((-directions[:, 1], directions[:, 0]))
    offsets = [points[0] + distance * normals[0]]
    for index in range(1, len(points) - 1):
        first, second = normals[index - 1], normals[index]
        bisector = first + second
        norm = float(np.linalg.norm(bisector))
        if norm <= _POINT_TOL:
            # The centerline reverses on itself: no unique miter direction.
            offsets.append(points[index] + distance * first)
            continue
        bisector = bisector / norm
        cosine = float(np.dot(bisector, first))
        if cosine <= _POINT_TOL or 1.0 / cosine > miter_limit:
            offsets.append(points[index] + distance * first)
            offsets.append(points[index] + distance * second)
        else:
            offsets.append(points[index] + distance * bisector / cosine)
    offsets.append(points[-1] + distance * normals[-1])
    return np.asarray(offsets)


def _offset_loop(points: np.ndarray, distance: float, *, miter_limit: float) -> np.ndarray:
    """Offset a closed polyline given without a repeated last point.

    The loop is extended on both sides so the vertex at ``points[0]`` gets a
    proper join too, then the extension is sliced away again.
    """
    if len(points) < 3:
        raise ValueError("a closed centerline needs at least three points")
    extended = np.vstack((points[-1], points, points[0], points[1]))
    return _offset_side(extended, distance, miter_limit=miter_limit)[1 : len(points) + 1]


def _half_circle(center: np.ndarray, normal: np.ndarray, tangent: np.ndarray, radius: float, samples: int) -> np.ndarray:
    """The cap arc from ``center + radius * normal`` to ``center - radius * normal``.

    ``tangent`` is the outward direction, so the arc bulges past the centerline end.
    """
    angles = np.linspace(0.0, np.pi, int(samples) + 1)
    return (
        center
        + radius * np.cos(angles)[:, None] * normal[None, :]
        + radius * np.sin(angles)[:, None] * tangent[None, :]
    )


@dataclass(frozen=True, slots=True)
class PieceOutline:
    """The closed polygon(s) the paint of one piece covers.

    ``outer`` is closed and counter-clockwise; ``holes`` are closed and clockwise
    (an uncut closed centerline is an annulus, i.e. it has one hole). Both are
    ``(N, 2)`` float arrays whose first point is repeated as the last point.
    """

    piece_id: str
    outer: np.ndarray
    holes: tuple[np.ndarray, ...] = ()
    cap_style: str = "butt"
    half_width: float = 0.0

    @property
    def area(self) -> float:
        """Painted area: the exterior minus the holes."""
        total = abs(_shoelace(self.outer))
        for hole in self.holes:
            total -= abs(_shoelace(hole))
        return total


def stroke_piece_outline(
    piece: Any,
    half_width: float,
    *,
    cap_style: CapStyle = "butt",
    samples: int = 8,
    miter_limit: float = DEFAULT_MITER_LIMIT,
) -> PieceOutline:
    """The closed paint outline of one visible stroke piece.

    ``half_width`` is the ribbon half-width (the engine's ``offset``), so the
    outline is ``2 * half_width`` wide. Butt caps stop exactly at the centerline
    ends, square caps extend half a width past them, and round caps add a sampled
    half-disc. A piece whose centerline is closed (an uncut closed path) has no
    ends: its outline is an annulus and the hole ring is reported in ``holes``
    instead of being silently filled.

    Raises ``ValueError`` for a non-positive/non-finite ``half_width``, an unknown
    ``cap_style``, an unusable ``samples``, or a closed centerline whose inner
    offset collapses (the outline would be a self-intersecting ring, which this
    helper refuses to invent around).
    """
    if not np.isfinite(half_width) or half_width <= 0:
        raise ValueError(f"half_width must be positive and finite; got {half_width!r}")
    if cap_style not in ("butt", "round", "square"):
        raise ValueError(f"cap_style must be 'butt', 'round' or 'square'; got {cap_style!r}")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ValueError(f"samples must be a positive integer; got {samples!r}")
    piece_id = str(getattr(piece, "piece_id", "piece"))
    points = _dedupe(np.asarray(piece.points, dtype=float))
    if len(points) < 2:
        raise ValueError(f"piece {piece_id} needs at least two distinct points")

    closed_centerline = bool(getattr(piece, "closed", False)) and bool(
        np.allclose(points[0], points[-1], atol=1e-9)
    )
    if closed_centerline:
        loop = points[:-1]
        loop_area = _shoelace(_close(loop))
        left = _offset_loop(loop, half_width, miter_limit=miter_limit)
        right = _offset_loop(loop, -half_width, miter_limit=miter_limit)
        outer, inner = (right, left) if loop_area > 0 else (left, right)
        inner_area = _shoelace(_close(inner))
        if inner_area == 0.0 or (inner_area > 0) is not (loop_area > 0):
            # The inward offset folded through itself: the ring would be a self-crossing
            # polygon, which this helper refuses to invent around.
            raise ValueError(
                f"the inner offset of {piece_id} collapsed: half_width {half_width!r} is too large "
                "for this closed centerline"
            )
        hole = _orient(inner, counter_clockwise=False)
        return PieceOutline(
            piece_id=piece_id,
            outer=_orient(outer, counter_clockwise=True),
            holes=(hole,),
            cap_style=cap_style,
            half_width=float(half_width),
        )

    core = points
    if cap_style == "square":
        start_direction = (core[1] - core[0]) / np.linalg.norm(core[1] - core[0])
        end_direction = (core[-1] - core[-2]) / np.linalg.norm(core[-1] - core[-2])
        core = np.vstack(
            (core[0] - half_width * start_direction, core, core[-1] + half_width * end_direction)
        )
    left = _offset_side(core, half_width, miter_limit=miter_limit)
    right = _offset_side(core, -half_width, miter_limit=miter_limit)
    ring = [*left]
    if cap_style == "round":
        end_direction = (core[-1] - core[-2]) / np.linalg.norm(core[-1] - core[-2])
        end_normal = np.array([-end_direction[1], end_direction[0]])
        ring.extend(_half_circle(core[-1], end_normal, end_direction, half_width, samples)[1:-1])
    ring.extend(right[::-1])
    if cap_style == "round":
        start_direction = (core[1] - core[0]) / np.linalg.norm(core[1] - core[0])
        start_normal = np.array([-start_direction[1], start_direction[0]])
        # Travelled right-to-left, so the same arc is walked in reverse; walking it
        # forwards would cross the ring and cancel area against itself.
        ring.extend(_half_circle(core[0], start_normal, -start_direction, half_width, samples)[::-1][1:-1])
    return PieceOutline(
        piece_id=piece_id,
        outer=_orient(np.asarray(ring), counter_clockwise=True),
        cap_style=cap_style,
        half_width=float(half_width),
    )


@dataclass(frozen=True, slots=True)
class CapTreatment:
    """A named cut-end treatment: cap shape, cover allowance and arc sampling."""

    style: CapStyle = "butt"
    cover_allowance: float = 0.0
    samples: int = 8

    def __post_init__(self) -> None:
        if self.style not in ("butt", "round", "square"):
            raise ValueError(f"style must be 'butt', 'round' or 'square'; got {self.style!r}")
        if not np.isfinite(self.cover_allowance) or self.cover_allowance < 0:
            raise ValueError(
                f"cover_allowance must be finite and non-negative; got {self.cover_allowance!r}"
            )
        if not isinstance(self.samples, int) or isinstance(self.samples, bool) or self.samples < 1:
            raise ValueError(f"samples must be a positive integer; got {self.samples!r}")

    def validated_allowance(self, *, overshoot: float) -> float:
        """The cover allowance after the ``overshoot`` contract check."""
        return validate_cover_allowance(self.cover_allowance, overshoot)

    def outline(self, piece: Any, half_width: float, *, miter_limit: float = DEFAULT_MITER_LIMIT) -> PieceOutline:
        """The outline of ``piece`` under this treatment."""
        return stroke_piece_outline(
            piece,
            half_width,
            cap_style=self.style,
            samples=self.samples,
            miter_limit=miter_limit,
        )
