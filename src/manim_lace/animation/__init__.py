"""Algorithm traces and deterministic animation planning."""

from .plan import (
    ANIMATION_MODES,
    DEFAULT_STAGE_DURATIONS,
    DEFAULT_STAGE_MODES,
    AnimationPlan,
    AnimationStage,
    build_animation_plan,
)
from .trace import TraceRecorder, trace_to_jsonable
from .verify import CoordConsistency, verify_coordinate_consistency

__all__ = [
    "ANIMATION_MODES",
    "AnimationPlan",
    "AnimationStage",
    "CoordConsistency",
    "DEFAULT_STAGE_DURATIONS",
    "DEFAULT_STAGE_MODES",
    "TraceRecorder",
    "build_animation_plan",
    "trace_to_jsonable",
    "verify_coordinate_consistency",
]
