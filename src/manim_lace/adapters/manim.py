"""Optional Manim VMobject -> normalized PolylinePath adapter.

Manim is imported lazily so the numeric/topology core remains usable without a
Manim installation. The adapter understands cubic VMobject point groups and
uses De Casteljau subdivision based on chord error.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

import numpy as np

from ..model import PathSource, PolylinePath


def _distance_to_chord(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    chord = b - a
    denom = float(chord @ chord)
    if denom <= 1e-30:
        return float(np.linalg.norm(p - a))
    t = float(np.clip(((p - a) @ chord) / denom, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * chord)))


def _split_cubic(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p0, p1, p2, p3 = points
    p01 = (p0 + p1) / 2
    p12 = (p1 + p2) / 2
    p23 = (p2 + p3) / 2
    p012 = (p01 + p12) / 2
    p123 = (p12 + p23) / 2
    mid = (p012 + p123) / 2
    return np.array([p0, p01, p012, mid]), np.array([mid, p123, p23, p3])


def _sample_cubic(
    points: np.ndarray, max_error: float, depth: int = 0, max_depth: int = 18,
    t0: float = 0.0, t1: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    p0, p1, p2, p3 = points
    flatness = max(_distance_to_chord(p1, p0, p3), _distance_to_chord(p2, p0, p3))
    if flatness <= max_error or depth >= max_depth:
        return np.vstack((p0, p3)), np.array([t0, t1])
    left, right = _split_cubic(points)
    tm = (t0 + t1) / 2
    left_points, left_t = _sample_cubic(left, max_error, depth + 1, max_depth, t0, tm)
    right_points, right_t = _sample_cubic(right, max_error, depth + 1, max_depth, tm, t1)
    return np.vstack((left_points, right_points[1:])), np.concatenate((left_t, right_t[1:]))


def _get_family_with_points(mobject: object) -> list[object]:
    method = getattr(mobject, "family_members_with_points", None)
    if callable(method):
        return list(method())
    return [mobject] if getattr(mobject, "points", None) is not None else []


def extract_paths(
    mobject: object,
    *,
    max_error: float = 1e-3,
    z_tol: float = 1e-6,
    project_nonplanar: bool = False,
    deduplicate: bool = True,
) -> list[PolylinePath]:
    """Extract drawable subpaths from a Manim VMobject or VGroup-like object.

    Paths that are not XY-planar are rejected by default. Set
    ``project_nonplanar=True`` only when discarding Z is intentional.
    Unknown point layouts are retained as an approximate polyline with explicit
    metadata and a warning; callers can inspect ``source.metadata``.
    """
    if max_error <= 0:
        raise ValueError("max_error must be positive")
    members = _get_family_with_points(mobject)
    if not members:
        raise ValueError("source object has no vector points; expected a Manim VMobject")
    paths: list[PolylinePath] = []
    signatures: set[tuple[tuple[float, float], ...]] = set()
    next_id = 0
    for member_index, member in enumerate(members):
        get_subpaths = getattr(member, "get_subpaths", None)
        if callable(get_subpaths):
            subpaths = list(get_subpaths())
        else:
            points = np.asarray(getattr(member, "points", []), dtype=float)
            subpaths = [points] if len(points) else []
        n_per_curve = int(getattr(member, "n_points_per_cubic_curve", 4))
        type_name = type(member).__name__
        for subpath_index, subpath in enumerate(subpaths):
            points_3d = np.asarray(subpath, dtype=float)
            if points_3d.ndim != 2 or points_3d.shape[1] not in (2, 3) or len(points_3d) < 2:
                continue
            if points_3d.shape[1] == 3:
                z_span = float(np.ptp(points_3d[:, 2]))
                if z_span > z_tol and not project_nonplanar:
                    raise ValueError(
                        f"{type_name} subpath {subpath_index} is not in an XY plane (z-span={z_span:g}); "
                        "set project_nonplanar=True to explicitly project it."
                    )
            xy = points_3d[:, :2]
            metadata: dict[str, object] = {"member_index": member_index}
            parameters: np.ndarray | None = None
            if n_per_curve == 4 and len(points_3d) >= 4 and len(points_3d) % 4 == 0:
                cubics = points_3d.reshape((-1, 4, points_3d.shape[1]))
                sampled_parts: list[np.ndarray] = []
                parameter_parts: list[np.ndarray] = []
                for curve_index, curve in enumerate(cubics):
                    sampled, local_t = _sample_cubic(curve[:, :2], max_error)
                    global_t = curve_index + local_t
                    if sampled_parts and np.allclose(sampled_parts[-1][-1], sampled[0]):
                        sampled_parts.append(sampled[1:])
                        parameter_parts.append(global_t[1:])
                    else:
                        sampled_parts.append(sampled)
                        parameter_parts.append(global_t)
                xy = np.vstack(sampled_parts) if sampled_parts else xy
                parameters = np.concatenate(parameter_parts) if parameter_parts else None
            else:
                metadata["adapter_warning"] = "unknown_point_layout_treated_as_polyline"
                warnings.warn(
                    f"{type_name} point layout is not standard cubic VMobject data; "
                    "treating its points as a polyline. Inspect PathSource.metadata.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            if len(xy) < 2:
                continue
            # Consecutive duplicate points are removed here, not nonconsecutive ones.
            keep = np.ones(len(xy), dtype=bool)
            keep[1:] = np.linalg.norm(np.diff(xy, axis=0), axis=1) > 1e-10
            xy = xy[keep]
            if parameters is not None and len(parameters) == len(keep):
                parameters = parameters[keep]
            if len(xy) < 2:
                continue
            signature = tuple(map(tuple, np.round(xy, decimals=9)))
            if deduplicate and signature in signatures:
                continue
            signatures.add(signature)
            closed = bool(np.allclose(xy[0], xy[-1], atol=1e-7))
            if closed and not np.allclose(xy[0], xy[-1]):
                xy = np.vstack((xy, xy[0]))
            paths.append(PolylinePath(
                points=xy,
                path_id=f"P{next_id:04d}",
                closed=closed,
                source=PathSource(
                    object_type=type_name,
                    object_label=getattr(member, "name", None),
                    subpath_index=subpath_index,
                    parameter_name="bezier_segment_parameter" if parameters is not None else None,
                    metadata=metadata,
                ),
                parameters=parameters if parameters is not None and len(parameters) == len(xy) else None,
                sampling_error=max_error,
            ))
            next_id += 1
    if not paths:
        raise ValueError("no valid subpaths could be extracted from source object")
    return paths
