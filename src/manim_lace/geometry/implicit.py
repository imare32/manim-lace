"""Isocontour extraction for implicit curves: ``F(x, y) = level`` (SPEC FR-008).

Manim's ``ImplicitFunction`` can already be handed to the adapter as a vector object;
this module is the *independent* extractor the spec also allows, so an implicit curve can
enter the engine as a factory call with no Manim in the loop (like ``sample_parametric``
and ``sample_graph``).

What it does, and the decisions that are explicit rather than hidden:

* **Marching squares on a uniform grid.** Each cell's four corners are classified against
  ``level``; the contour crosses an edge exactly where the corner values straddle it, and
  the crossing is placed by linear interpolation of ``F`` along that edge.
* **Exact stitching, no proximity heuristic.** A crossing is identified by the *grid edge*
  it lies on, not by its coordinates, so two neighbouring cells that share an edge produce
  the same key and the segments join exactly. No tolerance is involved, so a contour can
  never be split by a rounding difference or welded across a gap it does not have.
* **Ambiguous saddles are decided by the bilinear centre.** When all four corners
  alternate inside/outside, two pairings are possible; the value of ``F`` at the cell
  centre picks the one that keeps the inside region connected (the derivation is written
  out at the decision). The count of such cells is reported.
* **Error control is measured, not assumed.** After each pass the residual is estimated as
  ``|F(mid) - level| / |∇F(mid)|`` — the first-order distance from the interpolated chord
  to the true contour, in world units. If it exceeds ``max_error`` the grid is refined
  (resolution doubled, up to ``max_resolution`` and ``max_refine_passes``) and the residual
  is measured again. The per-pass residuals are reported, so "this contour is accurate to
  X world units" is a measurement, not a claim.
* **Branches are separate paths with their provenance.** Every connected piece of the
  contour becomes its own :class:`~manim_lace.model.PolylinePath` and its
  ``source.metadata`` records the level, the grid, the branch index, whether it is closed,
  the orientation rule that was applied and the residual of the pass that produced it.
* **Orientation follows a stable rule.** ``orientation="gradient"`` (the default) orients
  every branch so that the ``F < level`` side is on its left, decided by the numerical
  gradient with a majority vote per branch — the equation alone does not determine a
  direction, so a rule has to, and it is reported. ``"ccw"`` forces counter-clockwise
  closed rings, ``"none"`` keeps the deterministic grid order.

**The one assumption, and what it costs when violated.** Marching squares assumes ``F`` is
continuous on the box. Where it is not — a pole, a jump — the corner values straddle the
level without the field ever being zero, and linear interpolation invents a curve *that is
not a contour of F*. This is not detectable from the local linear model (the pole's own
error estimate shrinks as the grid refines), so it is reported through the number the
sampler already controls: on ``F = 1/(x² + y² - 0.25)`` at level 0 — whose only feature is the
pole at ``r = 0.25`` — no pass reaches ``max_error``, ``GEOM-IMPLICIT-ERROR-TARGET-MISSED``
is raised, and the branches that missed are listed by index with their own residuals. A
caller must read that warning as "do not trust these contours", not as cosmetics.

**A level set that touches itself keeps its branches apart.** Where the contour passes
through a point twice — ``x·y = 0`` and ``x² - y² = 0`` are crosses — the extracted
branches come near each other and never meet, so the touch point is *not* represented as a
crossing. Measured with refinement off, the closest approach of the two branches of
``x·y = 0`` is exactly ``0.707 × h`` at 24, 48, 96, 192 and 384 nodes (``h`` the cell size):
it shrinks with the grid and never reaches zero. Cell-level special cases would not fix it
either, since ``x² - y² = 0`` produces no ambiguous cell at all (0 saddles measured, against
1 for ``x·y = 0``). The genuinely disjoint hyperbolas ``x·y = 0.2`` and ``x² - y² = 0.5``
behave the same way but *are* correct.

**At a degenerate saddle the local topology is not resolution-stable.** In the single
ambiguous cell of ``x·y = 0`` the bilinear centre value equals the level, so the choice
between the two pairings is decided by the sign of a zero. Measured with refinement off,
the branch owning the ``+x`` ray owns the ``-y`` ray at 24, 96 and 192 nodes and the
``-x`` ray at 48 and 384: the pairing alternates with the grid. The rule is deterministic
*for a given grid* and the cell is counted in the summary, but a caller who needs a stable
touch point has to merge endpoints (FR-009/FR-010 with FR-025's snap tolerance) rather than
have this module guess.

The gap is also whatever the refinement cap leaves behind, since both branches stop where
the grid stops. The lemniscate ``(x² + y²)² = x² - y²`` comes back as one closed branch of
2109 points whose two arms pass within 0.0082 of each other at the origin (closest approach
0.0026 to the origin), so a weave of it reports **0 crossings** where the true figure-eight
has a node.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..model import PathSource, PolylinePath
from ..tracing import BoundedRecords

#: Scalar field of two variables. Called with arrays when it supports them, elementwise
#: otherwise, so both ``lambda x, y: x*x + y*y - 1`` and a ``math``-based function work.
ScalarField = Callable[..., Any]

#: Orientation rules a caller may ask for.
ORIENTATION_RULES = ("gradient", "ccw", "none")

#: Relative floor for a gradient magnitude used as a divisor, scaled by the field's own
#: magnitude, so a flat field reports "undetermined" instead of dividing by ~0.
_GRADIENT_FLOOR = 1e-12


def _as_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if int(value) < 1:
        raise ValueError(f"{name} must be positive, got {value!r}")
    return int(value)


def _as_non_negative_int(value: Any, name: str) -> int:
    """A count that may legitimately be zero (``max_refine_passes=0`` is one single pass).

    Rejecting zero would force a caller who wants no refinement to fake it by inflating
    ``max_error``, which would also silently change what the residual means.
    """
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if int(value) < 0:
        raise ValueError(f"{name} must not be negative, got {value!r}")
    return int(value)


def _as_range(value: Any, name: str) -> tuple[float, float]:
    try:
        low, high = (float(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a (low, high) pair, got {value!r}") from exc
    if not (np.isfinite(low) and np.isfinite(high)):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if not high > low:
        raise ValueError(f"{name} must be increasing, got {value!r}")
    return low, high


def _supports_arrays(func: ScalarField) -> bool:
    """Whether the field can be called with coordinate arrays in one go.

    Probed once on a 2x2 block: a vectorised field (the common ``x*x + y*y - 1``) gets a
    fast path, a scalar/``math``-based one is evaluated elementwise. Anything that raises
    or returns the wrong shape takes the elementwise path, so the slow lane is correct for
    every callable rather than only for the ones that advertise being vectorised.
    """
    try:
        probe = func(np.zeros((2, 2)), np.zeros((2, 2)))
    except Exception:
        return False
    try:
        return np.asarray(probe, dtype=float).shape == (2, 2)
    except (TypeError, ValueError):
        return False


class _Field:
    """The scalar field plus the evaluation lane it supports."""

    def __init__(self, func: ScalarField) -> None:
        self.func = func
        self.vectorized = _supports_arrays(func)

    def grid(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """``F`` on the meshgrid of ``xs``/``ys``, as ``values[iy, ix]``.

        The coordinate arrays are expanded to the full grid *before* the call. Handing out
        a ``(1, nx)`` and an ``(ny, 1)`` array and letting the field broadcast them looks
        equivalent but is not: a field that ignores one coordinate — a straight contour
        ``np.tanh(50 * (x - 0.3))``, say — then returns a ``(1, nx)`` array and the reshape
        blows up. A field whose vectorised lane does not return the grid shape is simply
        evaluated elementwise, which is correct for every callable.
        """
        if self.vectorized:
            x_grid, y_grid = np.meshgrid(xs, ys)
            with np.errstate(all="ignore"):
                try:
                    values = np.asarray(self.func(x_grid, y_grid), dtype=float)
                except Exception:
                    values = np.empty(0)
            if values.shape == (len(ys), len(xs)):
                return values
            self.vectorized = False
        out = np.empty((len(ys), len(xs)), dtype=float)
        for iy, y in enumerate(ys):
            for ix, x in enumerate(xs):
                try:
                    out[iy, ix] = float(self.func(float(x), float(y)))
                except (ArithmeticError, ValueError, OverflowError, TypeError):
                    # A pole or a domain error is a genuine hole in the field, not a
                    # reason to abort the whole extraction.
                    out[iy, ix] = np.nan
        return out

    def points(self, coordinates: np.ndarray) -> np.ndarray:
        """``F`` at ``coordinates[:, 0], coordinates[:, 1]``."""
        if len(coordinates) == 0:
            return np.empty(0)
        if self.vectorized:
            with np.errstate(all="ignore"):
                try:
                    values = np.asarray(
                        self.func(coordinates[:, 0], coordinates[:, 1]), dtype=float
                    )
                except Exception:
                    values = np.full(len(coordinates), np.nan)
            return values.reshape(-1)
        out = np.empty(len(coordinates), dtype=float)
        for index, (x, y) in enumerate(coordinates):
            try:
                out[index] = float(self.func(float(x), float(y)))
            except (ArithmeticError, ValueError, OverflowError, TypeError):
                out[index] = np.nan
        return out


@dataclass(slots=True)
class _Contour:
    """One stitched contour branch: its points and whether it closes on itself."""

    points: np.ndarray
    closed: bool
    seed_key: tuple[str, int, int]
    junction_keys: tuple[tuple[str, int, int], ...] = ()


@dataclass(slots=True)
class _PassResult:
    """What one marching-squares pass produced, before it becomes paths."""

    resolution: tuple[int, int]
    contours: list[_Contour] = field(default_factory=list)
    residual: float = 0.0
    #: Per-branch residual of this pass, aligned with :attr:`contours`.
    branch_residuals: list[float] = field(default_factory=list)
    residual_undetermined: int = 0
    segment_count: int = 0
    dropped_chains: int = 0
    duplicate_points: int = 0
    ambiguous_cells: int = 0
    degenerate_edges: int = 0
    nonfinite_cells: int = 0
    junction_keys: int = 0


def _grid_axis(low: float, high: float, count: int) -> np.ndarray:
    return np.linspace(low, high, count, dtype=float)


def _crossing(
    start: np.ndarray,
    end: np.ndarray,
    value_start: float,
    value_end: float,
    level: float,
    degenerate_edges: list[int],
) -> np.ndarray:
    """Linear interpolation of the contour crossing along one grid edge.

    When both nodes sit exactly on the level the whole edge lies on the contour and linear
    interpolation has nothing to solve; the midpoint is taken and the edge is counted, so
    a contour that runs along grid lines is visible in the report instead of being a
    silent coin flip.
    """
    delta = value_end - value_start
    if delta == 0.0 or not np.isfinite(delta):
        degenerate_edges.append(1)
        fraction = 0.5
    else:
        fraction = (level - value_start) / delta
        if not np.isfinite(fraction):
            degenerate_edges.append(1)
            fraction = 0.5
        else:
            fraction = float(min(1.0, max(0.0, fraction)))
    return start + fraction * (end - start)


def _cell_segments(
    values: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    ix: int,
    iy: int,
    level: float,
) -> tuple[list[tuple[tuple[str, int, int], tuple[str, int, int]]], str]:
    """The contour segments inside one cell, as pairs of grid-edge keys, and its status.

    The status is a word rather than a count, because "one" used to mean two different
    things here (an ambiguous saddle and a non-finite corner), so the caller counted every
    cell with a NaN corner as a saddle — 9025 of 9025 cells on a field that was NaN
    everywhere — while the non-finite counter could never fire at all.

    Marching squares is implemented by *deriving* the connection from the corner signs
    rather than by looking up a memorised 16-case table, so the rule can be read here:

    * collect the crossings on the four edges (there are 0, 2 or 4 of them);
    * with two, connect them — the contour separates the inside corners from the outside
      ones, and there is exactly one way to do that;
    * with four (all corners alternate), both pairings keep two crossings each, and the
      bilinear centre decides: if the centre is inside, the two *outside* corners are
      separated, so each is paired with its two flanking crossings.
    """
    v00 = float(values[iy, ix])
    v10 = float(values[iy, ix + 1])
    v01 = float(values[iy + 1, ix])
    v11 = float(values[iy + 1, ix + 1])
    if not np.isfinite([v00, v10, v01, v11]).all():
        return [], "nonfinite"

    inside = (v00 >= level, v10 >= level, v11 >= level, v01 >= level)
    keys = {
        "bottom": ("h", iy, ix),
        "right": ("v", iy, ix + 1),
        "top": ("h", iy + 1, ix),
        "left": ("v", iy, ix),
    }
    corners = {
        "bottom": (np.array([xs[ix], ys[iy]]), np.array([xs[ix + 1], ys[iy]]), v00, v10),
        "right": (np.array([xs[ix + 1], ys[iy]]), np.array([xs[ix + 1], ys[iy + 1]]), v10, v11),
        "top": (np.array([xs[ix], ys[iy + 1]]), np.array([xs[ix + 1], ys[iy + 1]]), v01, v11),
        "left": (np.array([xs[ix], ys[iy]]), np.array([xs[ix], ys[iy + 1]]), v00, v01),
    }
    crossings: dict[str, tuple[tuple[str, int, int], np.ndarray]] = {}
    for name, (start, end, a, b) in corners.items():
        if (a >= level) == (b >= level):
            continue
        crossings[name] = (keys[name], _crossing(start, end, a, b, level, []))

    if not crossings:
        return [], "ok"
    if len(crossings) == 2:
        (key_a, _pa), (key_b, _pb) = crossings.values()
        return [(key_a, key_b)], "ok"
    if len(crossings) != 4:
        # Only reachable if a corner sits exactly on the level in a way the sign test above
        # does not classify symmetrically; nothing to connect, and the pass reports it.
        return [], "ok"

    centre = 0.25 * (v00 + v10 + v01 + v11)
    centre_inside = centre >= level
    pairs: list[tuple[str, str]]
    if centre_inside == inside[0]:
        # Centre agrees with corner 00 (bottom-left): 00 and 11 are one connected inside
        # region, so the outside corners 10 (bottom-right) and 01 (top-left) are each
        # bounded by their flanking crossings.
        pairs = [("bottom", "right"), ("top", "left")]
    else:
        pairs = [("bottom", "left"), ("right", "top")]
    return [(crossings[a][0], crossings[b][0]) for a, b in pairs], "ambiguous"


def _stitch(
    segments: list[tuple[tuple[str, int, int], tuple[str, int, int]]],
    key_points: dict[tuple[str, int, int], np.ndarray],
) -> tuple[list[_Contour], int, int, int]:
    """Chain segments that share a grid-edge key into contour branches.

    Two things here are easy to get subtly wrong and are therefore explicit:

    * **Open ends first.** A chain has to be traced from one of its ends, so the keys with
      exactly one incident segment are consumed first, and each one is walked end to end.
      Starting from an arbitrary segment instead split every chain whose first segment
      happened to be in its middle: measured on ``F = x*y`` (level 0) at a 96x96 grid, that
      turned 190 segments into 50 branches with a median length of one segment, instead of
      the 4 branches the contour actually has.
    * **Both directions.** A chain picked up mid-way (which can still happen at a junction)
      is extended backwards as well, so no piece is left behind as a stub.

    Junction keys (more than two segments meeting, which a shared grid node can produce)
    are resolved by continuing in the direction that is straightest, then by segment
    index, so the result is deterministic and the count is reported instead of hidden.
    """
    incident: dict[tuple[str, int, int], list[int]] = {}
    for index, (key_a, key_b) in enumerate(segments):
        incident.setdefault(key_a, []).append(index)
        incident.setdefault(key_b, []).append(index)
    junction_keys = sum(1 for indices in incident.values() if len(indices) > 2)

    used = [False] * len(segments)
    contours: list[_Contour] = []
    dropped = 0
    duplicates = 0

    def take(tail: tuple[str, int, int], chain: list[tuple[str, int, int]], reverse: bool):
        """Consume the next unused segment at ``tail`` (or at the head when reversed)."""
        candidates = [i for i in incident.get(tail, ()) if not used[i]]
        if not candidates:
            return False
        context = chain[::-1] if reverse else chain
        nxt = _pick_next(candidates, segments, context, key_points, tail)
        used[nxt] = True
        key_a, key_b = segments[nxt]
        other = key_b if key_a == tail else key_a
        if reverse:
            chain.insert(0, other)
        else:
            chain.append(other)
        return True

    def trace(start_key: tuple[str, int, int]) -> list[tuple[str, int, int]]:
        candidates = [i for i in incident.get(start_key, ()) if not used[i]]
        nxt = candidates[0]
        used[nxt] = True
        key_a, key_b = segments[nxt]
        chain = [start_key, key_b if key_a == start_key else key_a]
        while take(chain[-1], chain, reverse=False):
            pass
        while take(chain[0], chain, reverse=True):
            pass
        return chain

    free_ends = sorted(key for key, indices in incident.items() if len(indices) == 1)
    for key in free_ends:
        if any(not used[index] for index in incident[key]):
            chain = trace(key)
            contour, removed = _contour_from_chain(chain, key, key_points, incident)
            duplicates += removed
            if contour is None:
                dropped += 1
            else:
                contours.append(contour)
    for start_index in range(len(segments)):
        if used[start_index]:
            continue
        key_a, _key_b = segments[start_index]
        chain = trace(key_a)
        contour, removed = _contour_from_chain(chain, key_a, key_points, incident)
        duplicates += removed
        if contour is None:
            dropped += 1
        else:
            contours.append(contour)
    return contours, dropped, junction_keys, duplicates


def _contour_from_chain(
    chain: list[tuple[str, int, int]],
    seed_key: tuple[str, int, int],
    key_points: dict[tuple[str, int, int], np.ndarray],
    incident: dict[tuple[str, int, int], list[int]],
) -> tuple[_Contour | None, int]:
    """Turn a key chain into a contour, dropping zero-length pieces honestly.

    Consecutive identical points (a degenerate zero-size cell can produce them) are
    removed rather than emitted as a zero-length edge; the count is returned so the report
    can say how many were removed.
    """
    closed = len(chain) > 2 and chain[0] == chain[-1]
    keys = chain[:-1] if closed else chain
    junction_hits = [key for key in keys if len(incident.get(key, ())) > 2]
    points: list[np.ndarray] = []
    removed = 0
    for key in keys:
        point = key_points[key]
        if points and np.array_equal(point, points[-1]):
            removed += 1
            continue
        points.append(point)
    if closed and len(points) > 1 and np.array_equal(points[0], points[-1]):
        points.pop()
        removed += 1
    if len(points) < 2 or (closed and len(points) < 3):
        return None, removed
    array = np.asarray(points, dtype=float)
    if closed:
        array = np.vstack((array, array[0]))
    return (
        _Contour(points=array, closed=closed, seed_key=seed_key,
                 junction_keys=tuple(junction_hits)),
        removed,
    )


def _pick_next(
    candidates: list[int],
    segments: list[tuple[tuple[str, int, int], tuple[str, int, int]]],
    chain: list[tuple[str, int, int]],
    key_points: dict[tuple[str, int, int], np.ndarray],
    tail: tuple[str, int, int],
) -> int:
    """The next unused segment at a junction: straightest first, then lowest index."""
    if len(candidates) == 1:
        return candidates[0]
    previous = key_points[chain[-2]] if len(chain) >= 2 else None
    here = key_points[tail]
    incoming = here - previous if previous is not None else None
    best = candidates[0]
    best_score = -np.inf
    for index in candidates:
        a, b = segments[index]
        other = key_points[b if a == tail else a]
        direction = other - here
        norm = float(np.linalg.norm(direction))
        if norm <= 0.0 or incoming is None:
            score = 0.0
        else:
            incoming_norm = float(np.linalg.norm(incoming))
            score = float(direction @ incoming) / (norm * max(incoming_norm, 1e-300))
        if score > best_score + 1e-12:
            best_score = score
            best = index
    return best


def _orient(contour: _Contour, field: _Field, rule: str) -> tuple[np.ndarray, str]:
    """Apply the orientation rule; returns the points and what actually happened.

    ``gradient``: the crossing direction has the ``F < level`` side on its left when
    ``n · (-∇F) > 0`` for the left normal ``n``. The rule is local, so it works for open
    branches too; each vertex votes and the majority decides, with the vote count reported
    so a branch whose field is flat there says "undetermined" rather than pretending.
    """
    points = contour.points
    if rule == "none":
        return points, "kept"
    if rule == "ccw":
        if not contour.closed:
            return points, "kept"
        signed = 0.5 * float(np.sum(
            points[:-1, 0] * points[1:, 1] - points[1:, 0] * points[:-1, 1]
        ))
        if signed < 0.0:
            return points[::-1], "reversed"
        return points, "kept"
    # gradient rule (also the default)
    votes_for = 0
    votes_against = 0
    for index in range(len(points) - 1):
        start, end = points[index], points[index + 1]
        direction = end - start
        norm = float(np.linalg.norm(direction))
        if norm <= 0.0:
            continue
        direction = direction / norm
        left_normal = np.array([-direction[1], direction[0]])
        gradient = _gradient(field, start)
        magnitude = float(np.linalg.norm(gradient))
        if not np.isfinite(magnitude) or magnitude <= _GRADIENT_FLOOR:
            continue
        if float(left_normal @ (-gradient)) > 0.0:
            votes_for += 1
        else:
            votes_against += 1
    if votes_for == 0 and votes_against == 0:
        return points, "undetermined"
    if votes_against > votes_for:
        return points[::-1], "reversed"
    return points, "kept"


def _gradient(field: _Field, point: np.ndarray, *, scale: float = 1e-6) -> np.ndarray:
    """Central-difference gradient of the field at a point."""
    step = scale
    offsets = np.array([
        [step, 0.0], [-step, 0.0], [0.0, step], [0.0, -step],
    ])
    values = field.points(point[None, :] + offsets)
    if not np.isfinite(values).all():
        return np.array([np.nan, np.nan])
    return np.array([
        (values[0] - values[1]) / (2.0 * step),
        (values[2] - values[3]) / (2.0 * step),
    ])


#: Cap on the recorded per-pass decisions; the counters stay exact when it truncates.
_DECISION_LIMIT = 64


def sample_implicit(
    func: ScalarField,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    *,
    level: float = 0.0,
    resolution: tuple[int, int] = (96, 96),
    max_error: float = 1e-3,
    max_refine_passes: int = 4,
    max_resolution: tuple[int, int] = (768, 768),
    path_id: str = "P0000",
    orientation: str = "gradient",
    object_label: str | None = None,
    subdivision_tracer: Callable[[dict[str, Any]], None] | None = None,
) -> list[PolylinePath]:
    """Extract ``F(x, y) = level`` into one path per connected branch.

    Parameters
    ----------
    func:
        The scalar field. May be vectorised over coordinate arrays or scalar-only; both
        are supported (the slower lane is chosen automatically when the fast one fails).
    x_range, y_range:
        The box the contour is searched in, in world coordinates.
    level:
        The contour value; ``F(x, y) = level``. Defaults to 0 (the ``F(x,y)=0`` of the
        spec's wording).
    resolution:
        Starting grid as ``(nx, ny)`` cells. The grid is doubled per refinement pass.
    max_error:
        Target geometric error in world units, estimated as ``|F - level| / |∇F|`` at the
        midpoint of every emitted chord. Refinement stops once the estimate is within it,
        or when ``max_refine_passes`` / ``max_resolution`` is reached.
    max_refine_passes, max_resolution:
        The caps that keep a pathological field from refining forever. Both are reported.
    path_id:
        Base id; branches become ``path_id``, ``path_id.01``, ...
    orientation:
        ``"gradient"`` (default), ``"ccw"`` or ``"none"``; see the module docstring for
        what each promises. The rule that was actually applied per branch is reported.
    subdivision_tracer:
        Called once with the honest summary: grid and residuals per pass, branch and
        segment counts, ambiguous saddles, degenerate edges, non-finite cells, dropped
        chains, junctions, orientation outcome, and a ``diagnostics`` list the engine
        turns into structured diagnostics.

    Returns
    -------
    list[PolylinePath]
        One path per branch, in deterministic grid order. An empty list means the level
        was not crossed inside the box, which is reported — not silently an empty draw.
    """
    x_low, x_high = _as_range(x_range, "x_range")
    y_low, y_high = _as_range(y_range, "y_range")
    try:
        nx, ny = (int(part) for part in resolution)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"resolution must be an (nx, ny) pair, got {resolution!r}") from exc
    nx, ny = _as_positive_int(nx, "resolution nx"), _as_positive_int(ny, "resolution ny")
    if nx < 2 or ny < 2:
        raise ValueError("resolution needs at least 2 nodes per axis to form a cell")
    max_nx, max_ny = (int(part) for part in max_resolution)
    passes_cap = _as_non_negative_int(max_refine_passes, "max_refine_passes")
    if not np.isfinite(level):
        raise ValueError(f"level must be finite, got {level!r}")
    if not np.isfinite(max_error) or max_error <= 0:
        raise ValueError(f"max_error must be positive and finite, got {max_error!r}")
    if orientation not in ORIENTATION_RULES:
        raise ValueError(
            f"orientation must be one of {ORIENTATION_RULES}, got {orientation!r}"
        )
    if not callable(func):
        raise ValueError("func must be callable as func(x, y)")

    field = _Field(func)
    decisions = BoundedRecords(limit=_DECISION_LIMIT)
    diagnostics: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    label = object_label or "implicit_curve"
    best: _PassResult | None = None
    total_evaluations = 0

    for attempt in range(passes_cap + 1):
        xs = _grid_axis(x_low, x_high, nx)
        ys = _grid_axis(y_low, y_high, ny)
        values = field.grid(xs, ys)
        total_evaluations += nx * ny
        result = _marching_squares(values, xs, ys, level)
        residual, per_branch, undetermined = _residual(result, field, level, xs, ys)
        result.residual = residual
        result.branch_residuals = per_branch
        result.residual_undetermined = undetermined
        passes.append({
            "pass": attempt,
            "resolution": [nx, ny],
            "cells": (nx - 1) * (ny - 1),
            "segments": result.segment_count,
            "branches": len(result.contours),
            "residual": float(residual),
            "residual_undetermined_segments": undetermined,
            "ambiguous_saddles": result.ambiguous_cells,
            "degenerate_edges": result.degenerate_edges,
            "nonfinite_cells": result.nonfinite_cells,
        })
        decisions.add({
            "kind": "pass" if attempt else "start",
            "reason": "measured" if residual <= max_error else "residual_above_target",
            "resolution": [nx, ny],
            "residual": float(residual),
            "target": float(max_error),
        })
        if best is None or residual < best.residual:
            best = result
        within_target = residual <= max_error
        exhausted = attempt >= passes_cap or (nx >= max_nx and ny >= max_ny)
        if within_target or exhausted:
            break
        nx, ny = min(nx * 2, max_nx), min(ny * 2, max_ny)

    assert best is not None  # the loop always runs at least one pass
    # Indices of the branches whose own error exceeds the target, computed once so the
    # diagnostic and the summary name the same branches in the same way.
    over = [
        index for index, value in enumerate(best.branch_residuals) if value > max_error
    ]
    if best.residual > max_error:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-ERROR-TARGET-MISSED",
            "severity": "warning",
            "message": (
                "隐式曲线在给定的分辨率上限内没有达到目标几何误差："
                f"{len(over)}/{len(best.branch_residuals)} 条分支超标，"
                f"最差 {best.residual:.3e}，目标 {max_error:.3e}。"
                "**这些分支不可按该容差信任**：等值线提取假定 F 在盒子内连续，"
                "极点或跳变会让格点插值在 F 没有零点的地方造出一条曲线。"
            ),
            "details": {
                "residual": float(best.residual),
                "target": float(max_error),
                "resolution": list(best.resolution),
                "branches_over_error_target": over,
                "branch_residuals": [float(value) for value in best.branch_residuals],
            },
            "hints": (
                "提高 max_resolution / max_refine_passes 或放宽 max_error。"
                "若提高分辨率后残差仍不下降（每次减半只按比例减小、不收敛到目标），"
                "通常说明盒子内真的有极点或不连续，应改范围而不是继续加密。",
                "等值线自触（如 x·y = 0 的四条射线交于一点）会让两条分支停在同一格两侧、"
                "相差约一个格距而不相接；加密只能把间隙缩小，不能消除。",
            ),
        })
    if not best.contours:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-NO-CONTOUR",
            "severity": "warning",
            "message": (
                f"在给定范围内没有找到 F = {level} 的等值线："
                "该水平要么不在场值域内，要么整条落在盒子之外。"
            ),
            "details": {"level": float(level), "resolution": list(best.resolution)},
            "hints": ("检查 level 是否落在 x/y 范围内的场值域内，或扩大范围。",),
        })
    if best.ambiguous_cells:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-AMBIGUOUS-SADDLE",
            "severity": "info",
            "message": (
                f"{best.ambiguous_cells} 个格子四角交替进出，鞍点用双线性中心值裁决"
                "（保证同一侧区域连通）。"
            ),
            "details": {"cells": int(best.ambiguous_cells),
                        "resolution": list(best.resolution)},
            "hints": ("这是确定性规则而非猜测；如需更细的拓扑可提高分辨率。",),
        })
    if best.degenerate_edges:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-DEGENERATE-EDGE",
            "severity": "info",
            "message": (
                f"{best.degenerate_edges} 条网格边的两个端点都恰好落在该水平上，"
                "线性插值无解，按中点取值。"
            ),
            "details": {"edges": int(best.degenerate_edges)},
            "hints": ("把 level 平移一个极小量即可消除；引擎不会自动平移。",),
        })
    if best.nonfinite_cells:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-NONFINITE",
            "severity": "info",
            "message": (
                f"{best.nonfinite_cells} 个格子的角点上有非有限值（极点或定义域外），"
                "这些格子被跳过，等值线在那里断开而不是硬连过去。"
            ),
            "details": {"cells": int(best.nonfinite_cells)},
            "hints": ("极点附近的等值线不可靠；把搜索范围避开极点。",),
        })
    if best.dropped_chains:
        diagnostics.append({
            "code": "GEOM-IMPLICIT-DROPPED-BRANCH",
            "severity": "info",
            "message": (
                f"{best.dropped_chains} 条不足两点的碎片链被丢弃（分辨率不足或鞍点附近）。"
            ),
            "details": {"chains": int(best.dropped_chains)},
            "hints": ("提高分辨率，或降低 max_error 让网格更细。",),
        })
    for contour in best.contours:
        if contour.junction_keys:
            diagnostics.append({
                "code": "GEOM-IMPLICIT-JUNCTION",
                "severity": "info",
                "message": (
                    f"分支在 {len(contour.junction_keys)} 个网格节点上是多于两条链的交汇，"
                    "按“最直续接优先、其次下标最小”确定性接续。"
                ),
                "details": {"junctions": int(len(contour.junction_keys))},
                "hints": ("交汇通常来自同一点上的多个分支；提高分辨率可分开它们。",),
            })

    paths: list[PolylinePath] = []
    orientation_summary: dict[str, int] = {}
    for index, contour in enumerate(best.contours):
        points, outcome = _orient(contour, field, orientation)
        orientation_summary[outcome] = orientation_summary.get(outcome, 0) + 1
        if len(points) < 2:
            continue
        # This branch's own measured error, not the pass maximum: a single untrustworthy
        # branch must not be able to borrow the credibility of the others.
        branch_residual = (
            best.branch_residuals[index] if index < len(best.branch_residuals)
            else best.residual
        )
        paths.append(PolylinePath(
            points=points,
            path_id=f"{path_id}.{index:02d}" if index else path_id,
            closed=bool(contour.closed),
            source=PathSource(
                object_type="implicit_curve",
                object_label=label,
                subpath_index=index,
                parameter_name=None,
                metadata={
                    # The provenance the spec asks for: which branch, of which level, from
                    # which grid, and how it was oriented.
                    "level": float(level),
                    "branch_index": index,
                    "closed": bool(contour.closed),
                    "resolution": list(best.resolution),
                    "residual": float(branch_residual),
                    "within_error_target": bool(branch_residual <= max_error),
                    "orientation_rule": orientation,
                    "orientation_outcome": outcome,
                    "seed_edge": list(contour.seed_key),
                },
            ),
            sampling_error=float(branch_residual),
            # No 1-D source parameter exists for an implicit curve, so FR-036 refinement
            # has no probe to use and the crossing keeps its polyline estimate (reported
            # per crossing by ``CrossingEvent.refined``).
            curve=None,
        ))

    if subdivision_tracer is not None:
        subdivision_tracer({
            "path_id": path_id,
            "sampler": "implicit_isocontour",
            "level": float(level),
            "x_range": [x_low, x_high],
            "y_range": [y_low, y_high],
            "orientation_rule": orientation,
            "resolution": list(best.resolution),
            "passes": passes,
            "pass_count": len(passes),
            "refinement_exhausted": bool(best.residual > max_error),
            "branch_residuals": [float(value) for value in best.branch_residuals],
            "branches_over_error_target": over,
            "final_residual": float(best.residual),
            "residual_undetermined_segments": int(best.residual_undetermined),
            "branch_count": len(paths),
            "closed_branch_count": sum(1 for path in paths if path.closed),
            "segment_count": int(best.segment_count),
            "ambiguous_saddles": int(best.ambiguous_cells),
            "degenerate_edges": int(best.degenerate_edges),
            "nonfinite_cells": int(best.nonfinite_cells),
            "dropped_chains": int(best.dropped_chains),
            "junction_keys": int(best.junction_keys),
            "orientation": orientation_summary,
            "field_evaluations": int(total_evaluations),
            "sample_count": int(sum(len(path.points) for path in paths)),
            "interval_count": int(best.segment_count),
            "node_count": int(best.segment_count),
            "split_count": int(sum(p["cells"] for p in passes)),
            "accepted_count": len(paths),
            "budget_capped_count": 0 if best.residual <= max_error else 1,
            "singular_count": int(best.nonfinite_cells),
            "max_depth_reached": len(passes) - 1,
            "diagnostics": diagnostics,
            **decisions.as_payload("decisions"),
        })
    return paths


def _marching_squares(
    values: np.ndarray, xs: np.ndarray, ys: np.ndarray, level: float
) -> _PassResult:
    """One grid's worth of cells: emitted segments, stitched into branches."""
    rows, cols = values.shape
    result = _PassResult(resolution=(cols, rows))
    segments: list[tuple[tuple[str, int, int], tuple[str, int, int]]] = []
    key_points: dict[tuple[str, int, int], np.ndarray] = {}
    degenerate: list[int] = []
    for iy in range(rows - 1):
        for ix in range(cols - 1):
            cell, status = _cell_segments(values, xs, ys, ix, iy, level)
            if status == "nonfinite":
                result.nonfinite_cells += 1
                continue
            if status == "ambiguous":
                result.ambiguous_cells += 1
            for key_a, key_b in cell:
                if key_a not in key_points:
                    key_points[key_a] = _edge_crossing_point(
                        key_a, values, xs, ys, level, degenerate
                    )
                if key_b not in key_points:
                    key_points[key_b] = _edge_crossing_point(
                        key_b, values, xs, ys, level, degenerate
                    )
                segments.append((key_a, key_b))
    result.degenerate_edges = len(degenerate)
    result.segment_count = len(segments)
    contours, dropped, junctions, duplicates = _stitch(segments, key_points)
    result.contours = contours
    result.dropped_chains = dropped
    result.junction_keys = junctions
    result.duplicate_points = duplicates
    return result


def _edge_crossing_point(
    key: tuple[str, int, int],
    values: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    level: float,
    degenerate: list[int],
) -> np.ndarray:
    """The crossing on one grid edge, computed from the edge's own two node values.

    The edge key convention lives here because this is the only place that turns a key back
    into geometry: ``("h", row, col)`` is the horizontal edge from node ``(col, row)`` to
    ``(col + 1, row)``, and ``("v", row, col)`` the vertical edge from ``(col, row)`` to
    ``(col, row + 1)``. Two cells meeting along an edge name it with the same
    ``(row, col)``, so they read the same two node values and interpolate the same point —
    which is what makes the stitching exact with no tolerance involved.
    """
    kind, row, col = key
    if kind == "h":
        start, end = np.array([xs[col], ys[row]]), np.array([xs[col + 1], ys[row]])
        a, b = float(values[row, col]), float(values[row, col + 1])
    else:
        start, end = np.array([xs[col], ys[row]]), np.array([xs[col], ys[row + 1]])
        a, b = float(values[row, col]), float(values[row + 1, col])
    return _crossing(start, end, a, b, level, degenerate)


def _residual(
    result: _PassResult,
    field: _Field,
    level: float,
    xs: np.ndarray,
    ys: np.ndarray,
) -> tuple[float, list[float], int]:
    """Measured geometric error of the pass: ``|F - level| / |∇F|`` at chord midpoints.

    This is the distance from the emitted chord to the true contour to first order, in
    world units — the same quantity the sampler is asked to control, so "accurate to X" is
    a measurement rather than a claim. Where the gradient is numerically zero the estimate
    does not exist; those chords are counted and excluded rather than being reported as
    zero error.

    The residual is also kept **per branch**, because one bad branch must not be able to
    hide behind a global maximum: when the target is missed, the diagnostic can then name
    the branches that are not trustworthy.
    """
    per_branch: list[float] = []
    undetermined = 0
    scale = max(float(np.max(np.abs(xs))), float(np.max(np.abs(ys))), 1.0) * 1e-9
    for contour in result.contours:
        points = contour.points
        midpoints = [(points[i] + points[i + 1]) / 2.0 for i in range(len(points) - 1)]
        worst = 0.0
        if midpoints:
            coordinates = np.asarray(midpoints, dtype=float)
            values = field.points(coordinates)
            for point, value in zip(coordinates, values):
                if not np.isfinite(value):
                    undetermined += 1
                    continue
                gradient = _gradient(field, point, scale=scale)
                magnitude = float(np.linalg.norm(gradient))
                if not np.isfinite(magnitude) or magnitude <= _GRADIENT_FLOOR:
                    undetermined += 1
                    continue
                worst = max(worst, abs(float(value) - level) / magnitude)
        per_branch.append(worst)
    return (max(per_branch) if per_branch else 0.0), per_branch, undetermined