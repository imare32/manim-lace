"""Reproducible input set for crossing-detection benchmarks (SPEC §10.2).

The scenarios cover the four classes the spec asks for, and every one of them is
built from fixed constants only — no random sampling, no clock, no environment
input — so two runs always produce byte-identical geometry. ``event_digest``
turns a detection result into a short, stable string that benchmarks and tests
can compare across runs and (deliberately) across code changes.

The module is geometry-only and does not import Manim; run the timing script with
``python benchmarks/bench_crossings.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import numpy as np

from .model import PolylinePath


def piece_digest(pieces) -> str:
    """Short stable digest of the stroke pieces, including their draw order.

    The crossing digest above freezes the geometry stage; this one freezes what the
    stroke renderer emits (arc intervals, point counts and painter order), which is the
    closest a headless repository gets to a visual regression baseline.
    """
    payload = [
        (
            piece.piece_id,
            piece.path_id,
            piece.closed,
            piece.draw_index,
            len(piece.points),
            round(float(piece.arc_start), 12),
            round(float(piece.arc_end), 12),
            [round(float(value), 9) for value in np.asarray(piece.points).reshape(-1)],
        )
        for piece in sorted(pieces, key=lambda item: (item.draw_index, item.piece_id))
    ]
    return hashlib.sha1(repr(payload).encode("utf-8")).hexdigest()

#: The four input classes required by SPEC §10.2.
SCENARIO_CLASSES = ("simple", "dense_smooth", "self_intersecting", "path_network")


def _simple_shapes() -> list[PolylinePath]:
    """Class ``simple``: a handful of straight crossings and one closed square."""
    return [
        PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="simple-h"),
        PolylinePath(np.array([[0.0, -2.0], [0.0, 2.0]]), path_id="simple-v"),
        PolylinePath(np.array([[-2.0, -2.0], [2.0, 2.0]]), path_id="simple-d"),
        PolylinePath(
            np.array([[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]]),
            path_id="simple-box",
            closed=True,
        ),
    ]


def _dense_smooth_curves() -> list[PolylinePath]:
    """Class ``dense_smooth``: a finely sampled closed curve and an open wave."""
    theta = np.linspace(0.0, 2 * np.pi, 1201)
    circle = np.column_stack((2.0 * np.cos(theta), 2.0 * np.sin(theta)))
    x = np.linspace(-2.5, 2.5, 601)
    wave = np.column_stack((x, 1.2 * np.sin(3.0 * x)))
    return [
        PolylinePath(circle, path_id="dense-circle", closed=True),
        PolylinePath(wave, path_id="dense-wave"),
    ]


def _self_intersecting_curve() -> list[PolylinePath]:
    """Class ``self_intersecting``: one path that revisits itself many times."""
    t = np.linspace(0.0, 2 * np.pi, 1501)
    curve = np.column_stack((np.sin(5.0 * t + np.pi / 4.0), np.sin(4.0 * t)))
    return [PolylinePath(curve, path_id="self-lissajous")]


def _path_network() -> list[PolylinePath]:
    """Class ``path_network``: many short paths whose crossings interleave."""
    paths: list[PolylinePath] = []
    for index in range(12):
        coordinate = -1.5 + index * (3.0 / 11.0)
        paths.append(PolylinePath(
            np.array([[coordinate, -1.6], [coordinate, 1.6]]), path_id=f"net-v{index:02d}"
        ))
        paths.append(PolylinePath(
            np.array([[-1.6, coordinate], [1.6, coordinate]]), path_id=f"net-h{index:02d}"
        ))
    for index, centre in enumerate(((-0.6, -0.6), (0.6, 0.6), (0.0, 0.0))):
        theta = np.linspace(0.0, 2 * np.pi, 101)
        paths.append(PolylinePath(
            np.column_stack((0.55 * np.cos(theta) + centre[0], 0.55 * np.sin(theta) + centre[1])),
            path_id=f"net-c{index}",
            closed=True,
        ))
    return paths


_SCENARIOS: dict[str, Callable[[], list[PolylinePath]]] = {
    "simple": _simple_shapes,
    "dense_smooth": _dense_smooth_curves,
    "self_intersecting": _self_intersecting_curve,
    "path_network": _path_network,
}


def scenario_names() -> list[str]:
    """Scenario names in a stable, reproducible order."""
    return list(SCENARIO_CLASSES)


def scenarios() -> dict[str, list[PolylinePath]]:
    """Build every scenario fresh; identical output on every call."""
    return {name: _SCENARIOS[name]() for name in scenario_names()}


def event_digest(crossings) -> str:
    """Short stable digest of the reported crossing events."""
    payload = [
        (
            event.crossing_id,
            event.kind,
            round(float(event.point[0]), 12),
            round(float(event.point[1]), 12),
            round(float(event.s_a), 12),
            round(float(event.s_b), 12),
            round(float(event.sin_angle), 12),
        )
        for event in crossings
    ]
    return hashlib.sha1(repr(payload).encode("utf-8")).hexdigest()
