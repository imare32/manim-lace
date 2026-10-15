"""Candidate pruning must never change the reported weave geometry (SPEC FR-035)."""

import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.geometry.index import SegmentCandidateIndex, neighbourhood_clusters
from manim_lace.geometry.intersections import detect_crossings
from manim_lace.model import PolylinePath

TOL = 1e-7


def _event_signature(result):
    return [
        (
            event.crossing_id,
            event.kind,
            event.point,
            event.s_a,
            event.s_b,
            event.segment_a,
            event.segment_b,
            event.u_a,
            event.u_b,
            event.sin_angle,
        )
        for event in result.crossings
    ]


def _diagnostic_signature(result):
    return [(d.code, d.path_ids, d.crossing_id) for d in result.diagnostics]


def _random_paths(rng, *, count, points, step=0.35, spread=2.0):
    paths = []
    for index in range(count):
        walk = np.cumsum(rng.normal(scale=step, size=(points, 2)), axis=0)
        walk += rng.normal(scale=spread, size=2)
        paths.append(PolylinePath(walk, path_id=f"R{index:03d}"))
    return paths


def _scenarios():
    rng = np.random.default_rng(20261015)
    theta = np.linspace(0, 2 * np.pi, 361)
    circle = PolylinePath(
        np.column_stack((np.cos(theta), np.sin(theta))), path_id="circle", closed=True
    )
    lissajous_theta = np.linspace(0, 2 * np.pi, 481)
    lissajous = PolylinePath(
        np.column_stack((np.sin(3 * lissajous_theta), np.sin(2 * lissajous_theta))),
        path_id="lissajous",
    )
    crossing_lines = [
        PolylinePath(np.array([[-2.0, 0.0], [2.0, 0.0]]), path_id="h"),
        PolylinePath(np.array([[0.0, -2.0], [0.0, 2.0]]), path_id="v"),
        PolylinePath(np.array([[-2.0, -2.0], [2.0, 2.0]]), path_id="d"),
    ]
    return {
        "circle_and_lines": [
            circle,
            PolylinePath(np.array([[-1.5, -0.4], [1.5, 0.4]]), path_id="diag"),
        ],
        # Many crossings share one point, so clustering has to stay bounded.
        "concurrent_fan": [
            *[
                PolylinePath(
                    np.array(
                        [
                            [-1.4 * np.cos(angle), -1.4 * np.sin(angle)],
                            [1.4 * np.cos(angle), 1.4 * np.sin(angle)],
                        ]
                    ),
                    path_id=f"fan{index:02d}",
                )
                for index, angle in enumerate(np.linspace(0.0, np.pi, 12, endpoint=False))
            ],
            circle,
        ],
        "self_intersecting": [lissajous],
        "crossing_lines": crossing_lines,
        # Long thin segments make the grid coarse; correctness must survive anyway.
        "parallel_lines": [
            PolylinePath(np.array([[-4.0, index * 0.5 - 1.0], [4.0, index * 0.5 - 1.0]]),
                         path_id=f"L{index}")
            for index in range(8)
        ],
        "random_walks_6": _random_paths(rng, count=6, points=24),
        "random_walks_12": _random_paths(rng, count=12, points=16, step=0.6),
        "repeated_points_zigzag": [
            PolylinePath(
                np.array([[-1.0, 0.0], [0.0, 0.0], [0.0, 0.0], [1.0, 0.0]]), path_id="flat"
            ),
            PolylinePath(
                np.array([[-1.0, -1.0], [0.0, 0.0], [1.0, 0.0], [0.0, 0.0], [1.0, 1.0]]),
                path_id="zig",
            ),
        ],
        "mixed_scale": [
            PolylinePath(np.array([[-3.0, 0.0], [3.0, 0.0]]), path_id="long"),
            PolylinePath(
                np.column_stack((0.01 * np.cos(theta) + 1.0, 0.01 * np.sin(theta))),
                path_id="tiny_circle",
                closed=True,
            ),
        ],
    }


@pytest.mark.parametrize("scenario", sorted(_scenarios()))
def test_grid_and_brute_force_report_identical_events(scenario):
    paths = _scenarios()[scenario]
    gridded = detect_crossings(paths, position_tol=TOL, candidate_strategy="grid")
    reference = detect_crossings(paths, position_tol=TOL, candidate_strategy="brute_force")
    assert _event_signature(gridded) == _event_signature(reference)
    # Pair enumeration order is preserved, so diagnostics and trace stay identical.
    assert _diagnostic_signature(gridded) == _diagnostic_signature(reference)
    assert gridded.stats is not None and reference.stats is not None
    assert gridded.stats.segment_count == reference.stats.segment_count
    assert reference.stats.candidate_pairs == reference.stats.all_pairs


@pytest.mark.parametrize("scenario", sorted(_scenarios()))
def test_grid_never_increases_narrow_phase_work(scenario):
    paths = _scenarios()[scenario]
    stats = detect_crossings(paths, position_tol=TOL).stats
    assert stats is not None
    assert 0 < stats.candidate_pairs <= stats.all_pairs
    assert 0 <= stats.pair_checks <= stats.candidate_pairs


def test_parallel_lines_are_pruned_by_the_narrow_phase():
    paths = _scenarios()["parallel_lines"]
    result = detect_crossings(paths)
    assert result.crossings == []
    stats = result.stats
    assert stats is not None
    # The coarse grid cannot separate long thin boxes, so every pair is a
    # candidate; the cheap bounding-box test still rejects all of them.
    assert stats.all_pairs == 28
    assert stats.pair_checks == 0


def test_grid_prunes_candidates_for_dense_separated_curves():
    theta = np.linspace(0, 2 * np.pi, 361)
    paths = [
        PolylinePath(
            np.column_stack((np.cos(theta) - 2.0, np.sin(theta))), path_id="left", closed=True
        ),
        PolylinePath(
            np.column_stack((np.cos(theta) + 2.0, np.sin(theta))), path_id="right", closed=True
        ),
    ]
    result = detect_crossings(paths)
    assert result.crossings == []
    stats = result.stats
    assert stats is not None
    assert stats.all_pairs == 720 * 719 // 2
    assert stats.candidate_pairs < stats.all_pairs // 4, stats
    assert stats.grid_cells > 0


def test_grid_candidates_superset_randomized():
    rng = np.random.default_rng(7)
    for _ in range(40):
        boxes = np.sort(rng.normal(scale=3.0, size=(24, 2, 2)), axis=1)
        boxes_min, boxes_max = boxes[:, 0, :], boxes[:, 1, :]
        expected = set()
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                # Same predicate the brute-force narrow phase applies.
                if (boxes_max[second] < boxes_min[first] - TOL).any() or (
                    boxes_min[second] > boxes_max[first] + TOL
                ).any():
                    continue
                expected.add((first, second))
        found = set(SegmentCandidateIndex.build(boxes_min, boxes_max, expansion=TOL).candidates().pairs)
        assert expected <= found, sorted(expected - found)


def test_candidate_pairs_are_sorted_and_deterministic():
    paths = _scenarios()["random_walks_12"]
    first = detect_crossings(paths)
    second = detect_crossings(paths)
    assert first.stats == second.stats
    assert _event_signature(first) == _event_signature(second)
    assert first.stats is not None
    assert first.stats.strategy == "grid"


def test_invalid_candidate_strategy_is_rejected():
    paths = [np.array([[0.0, 0.0], [1.0, 0.0]])]
    with pytest.raises(ValueError):
        LaceEngine(paths, candidate_strategy="quadtree")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        detect_crossings(
            [PolylinePath(np.array([[0.0, 0.0], [1.0, 0.0]]))],
            candidate_strategy="quadtree",  # type: ignore[arg-type]
        )


def test_grid_handles_tolerance_sized_slack_between_boxes():
    # Two boxes separated by exactly the positional tolerance must still be
    # candidates; otherwise the grid would silently drop a possible contact.
    boxes_min = np.array([[0.0, 0.0], [1.0 + TOL, 1.0]])
    boxes_max = np.array([[1.0, 1.0], [2.0, 2.0]])
    index = SegmentCandidateIndex.build(boxes_min, boxes_max, expansion=TOL)
    assert index.candidates().pairs == [(0, 1)]


def test_engine_exposes_detection_stats_and_identical_geometry():
    theta = np.linspace(0, 2 * np.pi, 257)
    paths = [
        np.column_stack((np.cos(theta), np.sin(theta))),
        np.array([[-1.5, 0.0], [1.5, 0.0]]),
    ]
    gridded = LaceEngine(paths, offset=0.1, weave_mode="free").solve()
    reference = LaceEngine(
        paths, offset=0.1, weave_mode="free", candidate_strategy="brute_force"
    ).solve()
    assert gridded.detection_stats is not None
    assert gridded.detection_stats.strategy == "grid"
    assert gridded.detection_stats.grid_cells > 0
    assert gridded.detection_stats.candidate_pairs < gridded.detection_stats.all_pairs
    assert reference.detection_stats is not None
    assert reference.detection_stats.strategy == "brute_force"
    assert reference.detection_stats.grid_cells == 0
    assert _event_signature(gridded) == _event_signature(reference)
    assert [(p.piece_id, p.arc_start, p.arc_end) for p in gridded.pieces] == [
        (p.piece_id, p.arc_start, p.arc_end) for p in reference.pieces
    ]
    assert all(
        np.array_equal(a.points, b.points)
        for a, b in zip(gridded.pieces, reference.pieces, strict=True)
    )


def _reference_clusters(points, radius):
    """The O(n^2) formulation the bucketed clustering must reproduce exactly."""
    visited = set()
    clusters = []
    for root in range(len(points)):
        if root in visited:
            continue
        cluster = [root]
        root_point = np.asarray(points[root], dtype=float)
        for candidate in range(root + 1, len(points)):
            if candidate in visited:
                continue
            if np.linalg.norm(root_point - np.asarray(points[candidate], dtype=float)) <= radius:
                cluster.append(candidate)
        visited.update(cluster)
        clusters.append(cluster)
    return clusters


def test_neighbourhood_clusters_match_the_reference_scan():
    rng = np.random.default_rng(4242)
    for trial in range(30):
        count = int(rng.integers(1, 120))
        points = rng.normal(scale=1.5, size=(count, 2))
        if trial % 3 == 0:
            points = np.round(points, 1)  # force duplicate and clumped points
        radius = float(rng.choice([1e-7, 1e-3, 0.2, 1.0]))
        assert neighbourhood_clusters(points, radius) == _reference_clusters(points, radius), (
            trial,
            radius,
        )


def test_neighbourhood_clusters_handle_fully_coincident_points():
    points = np.zeros((40, 2))
    clusters = neighbourhood_clusters(points, 1e-6)
    assert len(clusters) == 1
    assert clusters[0] == list(range(40))
    assert neighbourhood_clusters(np.zeros((0, 2)), 1e-6) == []


def test_multiway_clustering_is_unchanged_by_the_candidate_strategy():
    paths = _scenarios()["concurrent_fan"]
    gridded = detect_crossings(paths, candidate_strategy="grid")
    reference = detect_crossings(paths, candidate_strategy="brute_force")
    multiway = [c.crossing_id for c in gridded.crossings if c.kind == "multiway"]
    assert multiway
    assert multiway == [c.crossing_id for c in reference.crossings if c.kind == "multiway"]
    assert _diagnostic_signature(gridded) == _diagnostic_signature(reference)
    assert any(d.code == "GEOM-MULTIWAY-CROSSING" for d in gridded.diagnostics)


def test_candidate_stage_is_recorded_in_the_trace():
    paths = [
        np.column_stack((
            np.cos(np.linspace(0, 2 * np.pi, 129)),
            np.sin(np.linspace(0, 2 * np.pi, 129)),
        )),
        np.array([[-1.5, 0.0], [1.5, 0.0]]),
    ]
    result = LaceEngine(paths, offset=0.1, weave_mode="free").solve()
    candidates = [e for e in result.trace if e.event_type == "crossing.candidates"]
    assert len(candidates) == 1
    assert candidates[0].stage == "crossings"
    assert candidates[0].data["strategy"] == "grid"
    assert candidates[0].data["candidate_pairs"] <= candidates[0].data["all_pairs"]
