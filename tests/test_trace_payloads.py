"""Fine-grained traces for sampling subdivision and face walks (M5).

The two traces added here describe work that used to be invisible: the adaptive
subdivision decisions taken while a curve is sampled, and the traversal that turns
ribbon boundaries into regions. Both are checked the same way: the counters must
add up exactly, the bounded record lists must never look complete when they are
not, and the events must carry real coordinates/IDs rather than a retold story.
"""

import json

import numpy as np
import pytest

from manim_lace import LaceEngine, sample_graph, sample_parametric
from manim_lace.animation import build_animation_plan
from manim_lace.animation.trace import trace_to_jsonable
from manim_lace.tracing import DEFAULT_TRACE_RECORD_LIMIT, BoundedRecords

CROSSING = [np.array([[-1.0, 0.0], [1.0, 0.0]]), np.array([[0.0, -1.0], [0.0, 1.0]])]


class TestBoundedRecords:
    def test_every_record_is_counted_while_the_list_stays_bounded(self):
        records = BoundedRecords(limit=2)
        for index in range(5):
            records.add({"index": index})
        assert records.total == 5
        assert [record["index"] for record in records.entries] == [0, 1]
        assert records.truncated
        payload = records.as_payload("steps")
        assert payload["steps_count"] == 5
        assert payload["steps_truncated"] is True
        assert payload["steps"] == records.entries

    def test_a_list_under_the_limit_is_not_marked_truncated(self):
        records = BoundedRecords(limit=3)
        records.extend([{"index": 0}, {"index": 1}])
        assert records.total == 2
        assert not records.truncated
        assert records.as_payload("decisions")["decisions_truncated"] is False

    @pytest.mark.parametrize("limit", [-1, 1.5, True])
    def test_the_limit_is_validated(self, limit):
        with pytest.raises(ValueError, match="limit"):
            BoundedRecords(limit=limit)


class TestSubdivisionTrace:
    def test_the_summary_counters_describe_the_real_recursion(self):
        summaries: list[dict] = []
        paths = sample_parametric(
            lambda t: (np.cos(t), np.sin(t)), (0.0, 2.0 * np.pi),
            max_error=1e-5, max_step=0.1, closed=True,
            subdivision_tracer=summaries.append,
        )
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary["path_id"] == "P0000"
        assert summary["closed"] is True
        assert summary["max_error"] == pytest.approx(1e-5)
        assert summary["split_count"] > 0
        # Every recursion node ends in exactly one of these four outcomes.
        assert summary["node_count"] == (
            summary["split_count"] + summary["accepted_count"]
            + summary["budget_capped_count"] + summary["singular_count"]
        )
        assert summary["accepted_count"] >= summary["interval_count"]
        assert summary["interval_count"] == 63  # ceil(2*pi / 0.1)
        assert summary["max_depth_reached"] >= 1
        assert summary["part_count"] == len(paths)
        assert summary["sample_count"] == sum(len(path.points) for path in paths)
        assert summary["max_step"] == pytest.approx(0.1)
        assert summary["max_depth"] == 18

    def test_small_traces_keep_every_decision_with_its_own_numbers(self):
        summaries: list[dict] = []
        sample_parametric(
            lambda t: (np.cos(t), np.sin(t)), (0.0, 1.0),
            max_error=0.05, max_step=0.5, subdivision_tracer=summaries.append,
        )
        summary = summaries[0]
        assert summary["decisions_truncated"] is False
        assert summary["decisions_count"] == summary["node_count"] == len(summary["decisions"])
        assert {record["kind"] for record in summary["decisions"]} == {"accept"}
        for record in summary["decisions"]:
            assert set(record) == {"kind", "reason", "t0", "t1", "depth", "error"}
            assert record["t1"] > record["t0"]
            assert record["reason"] == "converged"
            assert record["error"] <= summary["max_error"]

    def test_a_long_recursion_stays_bounded_but_the_counters_do_not(self):
        summaries: list[dict] = []
        sample_parametric(
            lambda t: (t, t * t), (0.0, 1.0),
            max_error=1.0, max_step=1e-3, subdivision_tracer=summaries.append,
        )
        summary = summaries[0]
        assert summary["node_count"] > DEFAULT_TRACE_RECORD_LIMIT
        assert summary["decisions_truncated"] is True
        assert summary["decisions_count"] == summary["node_count"]
        assert len(summary["decisions"]) == DEFAULT_TRACE_RECORD_LIMIT
        # Loose error tolerance: only the parameter-space step bound forced the splits.
        assert {record["reason"] for record in summary["decisions"] if record["kind"] == "split"} == {
            "max_step"
        }

    def test_the_depth_cap_is_recorded_as_a_budget_decision(self):
        summaries: list[dict] = []
        sample_parametric(
            lambda t: (t, t * t), (0.0, 1.0),
            max_error=1e-12, max_step=1.0, max_depth=1, subdivision_tracer=summaries.append,
        )
        summary = summaries[0]
        assert summary["budget_capped_count"] == 2
        assert summary["max_depth_reached"] == 1
        budget = [record for record in summary["decisions"] if record["kind"] == "budget"]
        assert len(budget) == 2
        assert all(record["reason"].startswith("depth_cap+flatness") for record in budget)
        assert all(record["depth"] == 1 for record in budget)

    def test_a_non_finite_midpoint_is_recorded_as_a_drop(self):
        summaries: list[dict] = []
        sample_parametric(
            lambda t: (t, 1.0 / (t - 2.0)), (1.5, 2.5),
            max_step=1.0, subdivision_tracer=summaries.append,
        )
        summary = summaries[0]
        assert summary["interval_count"] == 1
        assert summary["singular_count"] == 1
        assert summary["sample_count"] == 0
        assert ("drop", "not_finite") in {(r["kind"], r["reason"]) for r in summary["decisions"]}

    def test_a_breakpoint_interval_is_reported_as_dropped(self):
        summaries: list[dict] = []
        paths = sample_parametric(
            lambda t: (t, 1.0 / t), (-1.0, 1.0),
            max_step=0.5, breakpoints=[0.0], subdivision_tracer=summaries.append,
        )
        assert paths  # the finite branches survive
        assert summaries[0]["dropped_interval_count"] == 2  # the two intervals that meet at 0

    def test_tracing_does_not_change_the_samples(self):
        kwargs = {"max_error": 0.01, "max_step": 0.05}
        without = sample_parametric(lambda t: (np.cos(t), np.sin(t)), (0.0, 1.0), **kwargs)
        with_tracer = sample_parametric(
            lambda t: (np.cos(t), np.sin(t)), (0.0, 1.0),
            subdivision_tracer=lambda summary: None, **kwargs,
        )
        assert [path.points.tolist() for path in without] == [
            path.points.tolist() for path in with_tracer
        ]

    def test_sample_graph_reports_its_extra_jump_split(self):
        summaries: list[dict] = []
        paths = sample_graph(
            lambda x: 0.0 if x < 0.5 else 1.0, (0.0, 1.0),
            max_step=0.05, max_error=0.5, jump_threshold=0.5,
            subdivision_tracer=summaries.append,
        )
        summary = summaries[0]
        assert summary["part_count"] == 1  # the sampler produced one part
        assert summary["jump_split_path_count"] == len(paths) == 2


class TestSubdivisionEventInTheTrace:
    def _result(self):
        return LaceEngine.from_parametric(
            lambda t: (np.cos(t), np.sin(t)), (0.0, 2.0 * np.pi),
            offset=0.1, max_error=1e-4, max_step=0.2,
        ).solve()

    def test_from_parametric_traces_the_subdivision_it_actually_did(self):
        result = self._result()
        events = [event for event in result.trace if event.event_type == "sampling.subdivision"]
        assert len(events) == 1
        event = events[0]
        assert event.stage == "input"
        assert event.object_ids == ("P0000",)
        assert event.data["split_count"] > 0
        assert event.data["node_count"] == (
            event.data["split_count"] + event.data["accepted_count"]
            + event.data["budget_capped_count"] + event.data["singular_count"]
        )
        # Sampling precedes normalization, which precedes detection.
        assert result.trace[0] is event
        assert result.trace[1].event_type == "path.normalized"
        assert result.trace[1].object_ids == event.object_ids
        assert event.data["sample_count"] == result.trace[1].data["point_count"]

    def test_the_subdivision_event_lands_in_the_input_stage(self):
        result = self._result()
        plan = build_animation_plan(result, "overview")
        input_stage = next(stage for stage in plan.stages if stage.name == "input")
        assert "sampling.subdivision" in [event.event_type for event in input_stage.events]
        custom = build_animation_plan(result, "custom")
        assert "input" in custom.stage_names()

    def test_a_whole_trace_with_subdivision_is_json_serializable(self):
        result = self._result()
        dumped = json.dumps(trace_to_jsonable(result.trace))
        assert "sampling.subdivision" in dumped
        assert "decisions" in dumped

    def test_paths_given_as_coordinates_get_no_subdivision_event(self):
        result = LaceEngine(CROSSING).solve()
        assert not [
            event for event in result.trace if event.event_type == "sampling.subdivision"
        ]

    def test_a_sampling_trace_handed_over_by_the_caller_is_emitted_verbatim(self):
        summary = {
            "path_id": "P0000",
            "interval_count": 2,
            "node_count": 2,
            "split_count": 0,
            "accepted_count": 2,
            "budget_capped_count": 0,
            "singular_count": 0,
            "max_depth_reached": 0,
            "sample_count": 3,
        }
        result = LaceEngine(
            [np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]])], sampling_trace=[summary],
        ).solve()
        event = next(e for e in result.trace if e.event_type == "sampling.subdivision")
        assert event.data == summary
        assert event.object_ids == ("P0000",)

    def test_a_malformed_sampling_trace_is_rejected(self):
        with pytest.raises(ValueError, match="sampling_trace"):
            LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])], sampling_trace=["P0000"])

    def test_generated_ids_match_the_paths_the_sampler_produced(self):
        engine = LaceEngine.from_parametric(
            lambda t: (t, 1.0 / t), (-1.0, 1.0), breakpoints=[0.0], max_step=0.25,
        )
        summeries = engine.sampling_trace
        assert len(summeries) == 1
        ids = engine.trace_sampled_path_ids(summeries[0])
        assert len(ids) == len(engine.paths) == 2
        assert ids[0] == "P0000" and ids[1].startswith("P0000.")


class TestFaceWalkTrace:
    @pytest.mark.parametrize("backend", ["boolean", "arrangement"])
    def test_both_backends_trace_the_walk_that_built_the_regions(self, backend):
        pytest.importorskip("shapely")
        result = LaceEngine(
            CROSSING, offset=0.2, render_mode="ribbon", ribbon_backend=backend,
        ).solve()
        events = [event for event in result.trace if event.event_type == "region.face_walk"]
        assert len(events) == 1
        event = events[0]
        assert event.stage == "construction"
        walk = event.data
        assert walk["backend"] == backend
        assert walk["crossing_count"] == 1
        assert walk["node_count"] == 2
        assert walk["owner_count"] == 2
        assert walk["band_count"] == 2
        assert walk["section_count"] == 0
        assert walk["congested"] is False
        assert walk["removed_area"] == pytest.approx(0.16, rel=1e-6)
        assert walk["steps_count"] == len(walk["steps"])
        assert walk["steps_truncated"] is False
        # The walk is emitted before the polygons it produced.
        polygon_index = min(
            index for index, item in enumerate(result.trace) if item.event_type == "region.polygon"
        )
        assert result.trace.index(event) < polygon_index

    def test_the_boolean_walk_reports_which_strand_lost_which_area(self):
        pytest.importorskip("shapely")
        result = LaceEngine(CROSSING, offset=0.2, render_mode="ribbon").solve()
        walk = next(e for e in result.trace if e.event_type == "region.face_walk").data
        assert walk["node_kind"] == "band"
        assert walk["cut_count"] == 1
        assert walk["section_cut_count"] == 0
        assert walk["missing_assignment_count"] == 0
        assert walk["region_polygon_count"] == len(result.pieces) == 3
        step = walk["steps"][0]
        assert step["kind"] == "weave"
        assert step["target"] == "band"
        assert step["under"] != step["over"]
        assert step["lens_area"] == pytest.approx(0.16, rel=1e-6)
        assert step["removed_area"] == pytest.approx(walk["removed_area"], rel=1e-9)

    def test_the_arrangement_walk_reports_face_ownership_decisions(self):
        pytest.importorskip("shapely")
        result = LaceEngine(
            CROSSING, offset=0.2, render_mode="ribbon", ribbon_backend="arrangement",
        ).solve()
        walk = next(e for e in result.trace if e.event_type == "region.face_walk").data
        assert walk["node_kind"] == "face"
        assert walk["raw_face_count"] == 5
        assert walk["face_count"] == 5
        assert walk["single_owner_count"] == 4
        assert walk["lens_decided_count"] == 1
        assert walk["conflicting_count"] == 0
        assert walk["off_crossing_count"] == 0
        assert walk["uncovered_count"] == 0
        assert walk["sliver_count"] == 0
        assert {step["decision"] for step in walk["steps"]} == {"single", "lens"}
        assert all(step["area"] > 0 for step in walk["steps"])
        assert all(step["owner"] for step in walk["steps"])

    def test_a_missing_assignment_becomes_a_skip_step(self):
        pytest.importorskip("shapely")
        result = LaceEngine(
            CROSSING, offset=0.2, render_mode="ribbon", weave_mode="manual",
        ).solve()
        walk = next(e for e in result.trace if e.event_type == "region.face_walk").data
        assert walk["missing_assignment_count"] == 1
        assert [(step["kind"], step["reason"]) for step in walk["steps"]] == [
            ("skip", "missing_assignment")
        ]
        assert "REGION-MISSING-ASSIGNMENT" in [d.code for d in result.diagnostics]

    def test_the_two_backends_agree_on_the_shared_counters(self):
        pytest.importorskip("shapely")
        walks = {}
        for backend in ("boolean", "arrangement"):
            result = LaceEngine(
                CROSSING, offset=0.2, render_mode="ribbon", ribbon_backend=backend,
            ).solve()
            walks[backend] = next(
                e for e in result.trace if e.event_type == "region.face_walk"
            ).data
        shared = ("node_count", "band_count", "section_count", "crossing_count", "owner_count", "congested")
        assert {key: walks["boolean"][key] for key in shared} == {
            key: walks["arrangement"][key] for key in shared
        }
        assert walks["boolean"]["removed_area"] == pytest.approx(
            walks["arrangement"]["removed_area"], rel=1e-6
        )

    def test_a_ribbon_trace_is_json_serializable(self):
        pytest.importorskip("shapely")
        result = LaceEngine(CROSSING, offset=0.2, render_mode="ribbon").solve()
        dumped = json.dumps(trace_to_jsonable(result.trace))
        assert "region.face_walk" in dumped

    def test_the_stroke_backend_has_no_face_walk(self):
        result = LaceEngine(CROSSING, offset=0.2).solve()
        assert not [event for event in result.trace if event.event_type == "region.face_walk"]
