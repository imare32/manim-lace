import numpy as np

from manim_lace import LaceEngine
from manim_lace.animation import build_animation_plan, trace_to_jsonable


def test_algorithm_plan_includes_construction_and_complete():
    result = LaceEngine([
        np.array([[-1.0, 0.0], [1.0, 0.0]]),
        np.array([[0.0, -1.0], [0.0, 1.0]]),
    ]).solve()
    plan = build_animation_plan(result, mode="algorithm")
    assert "crossings" in plan.stage_names()
    assert "topology" in plan.stage_names()
    assert "construction" in plan.stage_names()
    assert "complete" in plan.stage_names()
    assert plan.source_trace_count == len(result.trace)


def test_trace_is_json_serializable():
    import json
    result = LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])]).solve()
    encoded = json.dumps(trace_to_jsonable(result.trace), ensure_ascii=False)
    assert '"result.complete"' in encoded
