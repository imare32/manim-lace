"""Algorithm traces and deterministic animation planning."""

from .plan import AnimationPlan, AnimationStage, build_animation_plan
from .trace import TraceRecorder, trace_to_jsonable

__all__ = ["AnimationPlan", "AnimationStage", "TraceRecorder", "build_animation_plan", "trace_to_jsonable"]
