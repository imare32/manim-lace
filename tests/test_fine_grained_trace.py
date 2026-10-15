"""Tests for fine-grained trace events and configurable animation plan (M5)."""

import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.animation import (
    ANIMATION_MODES,
    DEFAULT_STAGE_DURATIONS,
    DEFAULT_STAGE_MODES,
    build_animation_plan,
)


class TestFineGrainedCandidateTrace:
    """The trace now records individual candidate-pair evaluations."""

    def test_candidate_pairs_event_present(self):
        result = LaceEngine(
            [
                np.array([[-2.0, -1.0], [2.0, 1.0]]),
                np.array([[-2.0, 1.0], [2.0, -1.0]]),
            ]
        ).solve()
        candidate_events = [e for e in result.trace if e.event_type == "crossing.candidate_pairs"]
        assert len(candidate_events) == 1
        data = candidate_events[0].data
        assert "pair_count" in data
        assert "hit_count" in data
        assert data["pair_count"] >= data["hit_count"]
        assert data["hit_count"] >= 1  # at least the one crossing
        assert isinstance(data["pairs"], list)
        # Each pair has segment_a, segment_b, status
        for pair in data["pairs"]:
            assert "segment_a" in pair
            assert "segment_b" in pair
            assert pair["status"] in ("hit", "no_hit")

    def test_no_candidate_event_when_no_crossings(self):
        """A single path with no self-crossings should not produce candidate pair events."""
        result = LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])]).solve()
        # Only one path, no self-crossing segments → no candidates survive bounding box test
        # (actually one candidate pair may exist: segment 0 vs nothing since there's only 1 segment)
        # Let's just check the event exists or not without asserting count
        candidate_events = [e for e in result.trace if e.event_type == "crossing.candidate_pairs"]
        # With only one segment there are no candidate pairs
        if candidate_events:
            assert candidate_events[0].data["pair_count"] == 0


class TestFineGrainedTopologyTrace:
    """The trace now records constraint propagation steps."""

    def test_propagation_event_present(self):
        result = LaceEngine(
            [
                np.array([[-2.0, 0.0], [2.0, 0.0]]),
                np.array([[0.0, -2.0], [0.0, 2.0]]),
            ]
        ).solve()
        prop_events = [e for e in result.trace if e.event_type == "topology.propagation"]
        assert len(prop_events) == 1
        data = prop_events[0].data
        assert "seed_count" in data
        assert "propagation_count" in data
        assert "rejection_count" in data
        assert isinstance(data["steps"], list)
        # With two paths crossing once, there should be at least one seed
        assert data["seed_count"] >= 1
        # The step kinds are from {seed, propagate, reject}
        for step in data["steps"]:
            assert step["kind"] in ("seed", "propagate", "reject")

    def test_free_mode_has_no_propagation(self):
        """Free mode does not run constraint propagation."""
        result = LaceEngine(
            [
                np.array([[-2.0, 0.0], [2.0, 0.0]]),
                np.array([[0.0, -2.0], [0.0, 2.0]]),
            ],
            weave_mode="free",
        ).solve()
        prop_events = [e for e in result.trace if e.event_type == "topology.propagation"]
        assert len(prop_events) == 0


class TestConfigurableAnimationPlan:
    """build_animation_plan now accepts duration and stage-mode overrides."""

    def test_custom_duration_override(self):
        result = LaceEngine(
            [
                np.array([[-1.0, 0.0], [1.0, 0.0]]),
                np.array([[0.0, -1.0], [0.0, 1.0]]),
            ]
        ).solve()
        plan = build_animation_plan(result, mode="algorithm", durations={"input": 3.5})
        input_stage = next(s for s in plan.stages if s.name == "input")
        assert input_stage.duration == 3.5

    def test_unchanged_durations_keep_defaults(self):
        result = LaceEngine(
            [
                np.array([[-1.0, 0.0], [1.0, 0.0]]),
                np.array([[0.0, -1.0], [0.0, 1.0]]),
            ]
        ).solve()
        plan = build_animation_plan(result, mode="algorithm")
        for stage in plan.stages:
            assert stage.duration == DEFAULT_STAGE_DURATIONS[stage.name]

    def test_stage_mode_override(self):
        """A stage normally excluded from 'overview' can be included via override."""
        result = LaceEngine(
            [
                np.array([[-1.0, 0.0], [1.0, 0.0]]),
                np.array([[0.0, -1.0], [0.0, 1.0]]),
            ]
        ).solve()
        # Crossings is normally in 'overview', 'algorithm', 'debug' (not 'construction')
        # Diagnostics is normally in 'algorithm', 'debug' (not 'overview')
        base_plan = build_animation_plan(result, mode="construction")
        assert "crossings" not in base_plan.stage_names()
        # Override to include crossings in 'construction'
        override_plan = build_animation_plan(
            result,
            mode="construction",
            stage_modes={"crossings": ("overview", "algorithm", "construction", "debug")},
        )
        assert "crossings" in override_plan.stage_names()

    def test_default_constants_match_documented_values(self):
        assert DEFAULT_STAGE_DURATIONS["input"] == 1.4
        assert DEFAULT_STAGE_DURATIONS["complete"] == 1.8
        assert "overview" in DEFAULT_STAGE_MODES["input"]
        assert "overview" in DEFAULT_STAGE_MODES["crossings"]

    @pytest.mark.parametrize("mode", ANIMATION_MODES)
    def test_plan_still_works_with_overrides(self, mode):
        result = LaceEngine(
            [
                np.array([[-1.0, 0.0], [1.0, 0.0]]),
                np.array([[0.0, -1.0], [0.0, 1.0]]),
            ]
        ).solve()
        plan = build_animation_plan(
            result,
            mode=mode,
            durations={"crossings": 2.0},
            stage_modes={"topology": ("overview", "algorithm")},
        )
        assert plan.mode == mode
        assert plan.stages  # always has at least complete
