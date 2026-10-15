import numpy as np
import pytest

from manim_lace import LaceEngine
from manim_lace.animation import ANIMATION_MODES, build_animation_plan, trace_to_jsonable


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


@pytest.mark.parametrize("mode", ANIMATION_MODES)
def test_every_declared_mode_builds_a_plan(mode):
    result = LaceEngine([
        np.array([[-1.0, 0.0], [1.0, 0.0]]),
        np.array([[0.0, -1.0], [0.0, 1.0]]),
    ]).solve()
    plan = build_animation_plan(result, mode=mode)
    assert plan.mode == mode
    assert plan.stages  # every mode keeps at least the completion stage


def test_unknown_mode_raises_instead_of_returning_an_empty_plan():
    result = LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])]).solve()
    with pytest.raises(ValueError, match="mode must be one of"):
        build_animation_plan(result, mode="storyboard")  # type: ignore[arg-type]


def test_trace_is_json_serializable():
    import json
    result = LaceEngine([np.array([[0.0, 0.0], [1.0, 0.0]])]).solve()
    encoded = json.dumps(trace_to_jsonable(result.trace), ensure_ascii=False)
    assert '"result.complete"' in encoded
