"""Tests for the animation/geometry coordinate and ID consistency check (M5)."""

import numpy as np

from manim_lace import LaceEngine
from manim_lace.animation import verify_coordinate_consistency


class TestVerifyCoordinateConsistency:
    def test_consistent_on_simple_crossing(self):
        result = LaceEngine(
            [
                np.array([[-2.0, -1.0], [2.0, 1.0]]),
                np.array([[-2.0, 1.0], [2.0, -1.0]]),
            ]
        ).solve()
        report = verify_coordinate_consistency(result)
        assert report.consistent
        assert report.mismatches == []
        assert len(report.crossing_ids_in_result) == 1
        assert report.crossing_ids_in_trace == report.crossing_ids_in_result

    def test_consistent_on_no_crossings(self):
        result = LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])]).solve()
        report = verify_coordinate_consistency(result)
        assert report.consistent
        assert report.crossing_ids_in_result == ()
        assert report.crossing_ids_in_trace == ()

    def test_consistent_with_multiple_crossings(self):
        result = LaceEngine(
            [
                np.array([[-2.0, 0.0], [2.0, 0.0]]),
                np.array([[0.0, -2.0], [0.0, 2.0]]),
                np.array([[-1.5, -1.5], [1.5, 1.5]]),
            ],
            weave_mode="free",
        ).solve()
        report = verify_coordinate_consistency(result)
        assert report.consistent
        assert len(report.crossing_ids_in_result) == len(result.crossings)

    def test_point_matches_within_tolerance(self):
        result = LaceEngine(
            [
                np.array([[-1.0, 0.0], [1.0, 0.0]]),
                np.array([[0.0, -1.0], [0.0, 1.0]]),
            ]
        ).solve()
        report = verify_coordinate_consistency(result, tol=1e-6)
        assert report.consistent
        # The traced point should be essentially identical to the canonical point
        assert report.mismatches == []

    def test_all_crossing_ids_in_trace_match_result(self):
        result = LaceEngine(
            [
                np.array([[-3.0, 0.0], [3.0, 0.0]]),
                np.array([[-1.0, -2.0], [1.0, 2.0]]),
            ],
            weave_mode="free",
        ).solve()
        report = verify_coordinate_consistency(result)
        # Every crossing ID in result.crossings must appear in the trace
        for crossing in result.crossings:
            assert crossing.crossing_id in report.crossing_ids_in_trace
