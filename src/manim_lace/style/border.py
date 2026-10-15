"""Border design: the frame drawn around a finished pattern (SPEC §9).

The border is derived from the solved geometry's bounding box, not from the
paths, so it always frames what is actually visible (including pieces that were
cut or dropped). The output is a tuple of closed, counter-clockwise centerline
rings plus the stroke thickness to draw them with: the Manim adapter strokes
them, and a region-based renderer could offset them into an annulus.

Nothing here touches crossings, assignments or pieces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "CORNER_STYLES",
    "BorderGeometry",
    "BorderSpec",
    "build_border",
    "pattern_bounds",
]

#: How a frame corner is drawn: a right angle, a quarter arc, or a flat cut.
CORNER_STYLES = ("square", "round", "bevel")


def _shoelace(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _close_counter_clockwise(points: np.ndarray) -> np.ndarray:
    """Close a ring and orient it counter-clockwise."""
    array = np.asarray(points, dtype=float)
    if not np.allclose(array[0], array[-1]):
        array = np.vstack((array, array[0]))
    if _shoelace(array) < 0:
        array = np.vstack((array[::-1][:-1], array[0]))
    return array


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-15:
        raise ValueError("degenerate frame corner: the two edges meet at the same point")
    return vector / norm


def _piece_points(piece: Any) -> np.ndarray | None:
    points = getattr(piece, "points", None)
    if points is not None:
        return np.asarray(points, dtype=float)[:, :2]
    exterior = getattr(piece, "exterior", None)
    if exterior is not None:
        return np.asarray(exterior.points, dtype=float)[:, :2]
    return None


def pattern_bounds(result: Any) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of the visible geometry.

    Uses the pieces/regions when there are any (so a fully cut or dropped piece
    does not enlarge the frame) and falls back to the normalized paths otherwise.
    Raises ``ValueError`` when the result holds no drawable geometry at all.
    """
    chunks: list[np.ndarray] = []
    for piece in getattr(result, "pieces", []) or []:
        points = _piece_points(piece)
        if points is not None and len(points):
            chunks.append(points)
    if not chunks:
        for path in getattr(result, "paths", []) or []:
            points = np.asarray(path.points, dtype=float)[:, :2]
            if len(points):
                chunks.append(points)
    if not chunks:
        raise ValueError("cannot frame a result with no visible geometry")
    stacked = np.vstack(chunks)
    minimum = stacked.min(axis=0)
    maximum = stacked.max(axis=0)
    return float(minimum[0]), float(minimum[1]), float(maximum[0]), float(maximum[1])


def _rectangle(
    bounds: tuple[float, float, float, float],
    *,
    corner: str,
    radius: float,
    samples: int,
) -> np.ndarray:
    """One frame centerline: a closed counter-clockwise rectangle.

    Corners are visited counter-clockwise: bottom-right, top-right, top-left,
    bottom-left. A rounded corner is the quarter arc between the two points where
    the frame leaves the edges, so consecutive arcs are joined by straight edges.
    """
    min_x, min_y, max_x, max_y = bounds
    if corner == "square":
        return _close_counter_clockwise(
            np.array([[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]])
        )
    corners = (
        ((max_x, min_y), (max_x - radius, min_y), (max_x, min_y + radius)),
        ((max_x, max_y), (max_x, max_y - radius), (max_x - radius, max_y)),
        ((min_x, max_y), (min_x + radius, max_y), (min_x, max_y - radius)),
        ((min_x, min_y), (min_x, min_y + radius), (min_x + radius, min_y)),
    )
    pieces: list[np.ndarray] = []
    for corner_point, entry, exit_point in corners:
        apex = np.asarray(corner_point, dtype=float)
        start_point = np.asarray(entry, dtype=float)
        stop_point = np.asarray(exit_point, dtype=float)
        if corner == "bevel":
            pieces.extend((start_point, stop_point))
            continue
        # Both edge directions point into the rectangle, so their sum points at the
        # corner's inner diagonal: the arc center is one radius away from both edges.
        inward = _unit(start_point - apex) + _unit(stop_point - apex)
        center = apex + radius * inward
        start = float(np.arctan2(start_point[1] - center[1], start_point[0] - center[0]))
        stop = float(np.arctan2(stop_point[1] - center[1], stop_point[0] - center[0]))
        while stop - start > np.pi:
            stop -= 2.0 * np.pi
        while start - stop > np.pi:
            stop += 2.0 * np.pi
        angles = np.linspace(start, stop, int(samples) + 1)
        pieces.append(center + radius * np.column_stack((np.cos(angles), np.sin(angles))))
    return _close_counter_clockwise(np.vstack(pieces))


@dataclass(frozen=True, slots=True)
class BorderSpec:
    """How to frame the pattern.

    Parameters
    ----------
    margin:
        Distance from the pattern's bounding box to the innermost frame centerline.
    thickness:
        Stroke thickness of the frame (a visible width, in world units).
    corner:
        ``square``, ``round`` or ``bevel`` (see :data:`CORNER_STYLES`).
    radius:
        Corner radius / bevel cut length; ``None`` picks
        ``min(2 * thickness, 25% of the shorter pattern side)``.
    inset:
        Move the frame *inwards* again (towards the pattern) by this much; a frame
        may not end up inside the pattern.
    bands:
        How many concentric frames to draw (``2`` = a double frame).
    gap:
        Spacing between consecutive frames, centerline to centerline.
    color_index:
        Which palette colour the frame takes (cycling). The default ``0`` picks
        the palette's deepest colour, because the palettes end with their
        paper-like colour — a frame in that one would not be visible on the
        palette's own paper.
    samples:
        Arc segments per rounded corner.
    """

    margin: float = 0.25
    thickness: float = 0.04
    corner: str = "square"
    radius: float | None = None
    inset: float = 0.0
    bands: int = 1
    gap: float = 0.08
    color_index: int = 0
    samples: int = 8

    def __post_init__(self) -> None:
        for name in ("margin", "inset", "gap"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative; got {value!r}")
        if not np.isfinite(self.thickness) or self.thickness <= 0:
            raise ValueError(f"thickness must be positive and finite; got {self.thickness!r}")
        if self.corner not in CORNER_STYLES:
            raise ValueError(f"corner must be one of {list(CORNER_STYLES)}; got {self.corner!r}")
        if self.radius is not None and (not np.isfinite(self.radius) or self.radius <= 0):
            raise ValueError(f"radius must be positive and finite or None; got {self.radius!r}")
        if not isinstance(self.bands, int) or isinstance(self.bands, bool) or self.bands < 1:
            raise ValueError(f"bands must be a positive integer; got {self.bands!r}")
        if not isinstance(self.samples, int) or isinstance(self.samples, bool) or self.samples < 1:
            raise ValueError(f"samples must be a positive integer; got {self.samples!r}")
        if not isinstance(self.color_index, int) or isinstance(self.color_index, bool):
            raise ValueError(f"color_index must be an integer; got {self.color_index!r}")

    def expansion(self, band: int = 0) -> float:
        """How far band ``band`` sits outside the pattern's bounding box."""
        if not isinstance(band, int) or isinstance(band, bool) or not 0 <= band < self.bands:
            raise ValueError(f"band must be an integer within [0, {self.bands}); got {band!r}")
        expansion = self.margin + band * (self.thickness + self.gap) - self.inset
        if expansion < 0:
            raise ValueError(
                f"inset {self.inset!r} pushes band {band} {abs(expansion)!r} inside the pattern; "
                "reduce inset or raise margin"
            )
        return float(expansion)


@dataclass(frozen=True, slots=True)
class BorderGeometry:
    """A framed pattern: closed frame centerlines plus the bounds they came from."""

    spec: BorderSpec
    centerlines: tuple[np.ndarray, ...]
    frame_bounds: tuple[float, float, float, float]
    pattern_bounds: tuple[float, float, float, float]

    @property
    def color_index(self) -> int:
        """The palette index the frame asks for."""
        return self.spec.color_index

    def color(self, palette: Any) -> str:
        """The frame colour taken from a palette (any object with ``color(index)``)."""
        return palette.color(self.color_index)

    @property
    def band_bounds(self) -> tuple[tuple[float, float, float, float], ...]:
        """The bounding box of every frame centerline, innermost band first."""
        return tuple(
            (
                float(ring[:-1, 0].min()),
                float(ring[:-1, 1].min()),
                float(ring[:-1, 0].max()),
                float(ring[:-1, 1].max()),
            )
            for ring in self.centerlines
        )


def build_border(result: Any, spec: BorderSpec) -> BorderGeometry:
    """Build the frame for a solved ``result``.

    The innermost band sits ``spec.margin`` outside the visible geometry and each
    further band steps out by ``thickness + gap``. Every returned centerline is a
    closed, counter-clockwise ring, so a renderer can stroke it directly.

    Raises ``ValueError`` when the result has no drawable geometry, when the spec
    would place a frame inside the pattern, or when the requested corner radius
    does not fit into the shorter side of the frame.
    """
    if not isinstance(spec, BorderSpec):
        raise ValueError(f"spec must be a BorderSpec; got {type(spec).__name__}")
    bounds = pattern_bounds(result)
    min_x, min_y, max_x, max_y = bounds
    shorter = min(max_x - min_x, max_y - min_y)
    if spec.corner == "square":
        radius = 0.0
    else:
        radius = spec.radius if spec.radius is not None else min(
            2.0 * spec.thickness, 0.25 * max(shorter, 1e-9)
        )
        if radius <= 0 or (1.0 - 1e-9) * shorter < 2.0 * radius:
            raise ValueError(
                f"corner radius {radius!r} does not fit the shorter pattern side {shorter!r}; "
                "reduce radius or use corner='square'"
            )
    rings = tuple(
        _rectangle(
            (
                min_x - spec.expansion(band),
                min_y - spec.expansion(band),
                max_x + spec.expansion(band),
                max_y + spec.expansion(band),
            ),
            corner=spec.corner,
            radius=float(radius),
            samples=spec.samples,
        )
        for band in range(spec.bands)
    )
    outermost = max(rings, key=lambda ring: abs(_shoelace(ring)))
    frame_bounds = (
        float(outermost[:, 0].min()),
        float(outermost[:, 1].min()),
        float(outermost[:, 0].max()),
        float(outermost[:, 1].max()),
    )
    return BorderGeometry(
        spec=spec,
        centerlines=rings,
        frame_bounds=frame_bounds,
        pattern_bounds=bounds,
    )
