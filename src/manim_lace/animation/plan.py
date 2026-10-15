"""Renderer-neutral animation stages derived from the algorithm trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..model import LaceResult, TraceEvent

AnimationMode = Literal["overview", "algorithm", "construction", "debug", "custom"]

#: Every accepted plan mode; ``custom`` keeps all stages that have events.
ANIMATION_MODES = ("overview", "algorithm", "construction", "debug", "custom")

#: Default duration (seconds) for each stage.
DEFAULT_STAGE_DURATIONS: dict[str, float] = {
    "input": 1.4,
    "crossings": 1.4,
    "topology": 1.4,
    "construction": 1.4,
    "diagnostics": 1.0,
    "complete": 1.8,
}

#: Default mode membership for each stage.
DEFAULT_STAGE_MODES: dict[str, tuple[str, ...]] = {
    "input": ("overview", "algorithm", "construction", "debug"),
    "crossings": ("overview", "algorithm", "debug"),
    "topology": ("overview", "algorithm", "debug"),
    "construction": ("overview", "algorithm", "construction", "debug"),
    "diagnostics": ("algorithm", "debug"),
    "complete": ("overview", "algorithm", "construction", "debug"),
}


@dataclass(slots=True)
class AnimationStage:
    name: str
    title: str
    events: list[TraceEvent] = field(default_factory=list)
    duration: float = 1.0
    include_in_modes: tuple[str, ...] = ("overview", "algorithm", "construction", "debug")


@dataclass(slots=True)
class AnimationPlan:
    """A deterministic plan. It is not a Manim Animation until adapted."""

    mode: str
    stages: list[AnimationStage]
    source_trace_count: int

    def stage_names(self) -> list[str]:
        return [stage.name for stage in self.stages]

    def for_mode(self, mode: str) -> AnimationPlan:
        return AnimationPlan(
            mode=mode,
            stages=[s for s in self.stages if mode in s.include_in_modes],
            source_trace_count=self.source_trace_count,
        )


def build_animation_plan(
    result: LaceResult,
    mode: AnimationMode = "overview",
    *,
    durations: dict[str, float] | None = None,
    stage_modes: dict[str, tuple[str, ...]] | None = None,
) -> AnimationPlan:
    """Group actual trace events into pedagogically meaningful phases.

    An unknown mode raises instead of silently returning an empty plan.

    Parameters
    ----------
    result:
        The solved :class:`LaceResult` whose trace events are grouped.
    mode:
        One of :data:`ANIMATION_MODES`. ``custom`` keeps every stage with events.
    durations:
        Override one or more stage durations (seconds). Unspecified stages use
        :data:`DEFAULT_STAGE_DURATIONS`.
    stage_modes:
        Override which modes a stage appears in. Unspecified stages use
        :data:`DEFAULT_STAGE_MODES`. Only used when ``mode`` is not ``custom``.
    """
    if mode not in ANIMATION_MODES:
        raise ValueError(f"mode must be one of {ANIMATION_MODES}, got {mode!r}")
    merged_durations = {**DEFAULT_STAGE_DURATIONS, **(durations or {})}
    merged_modes = {**DEFAULT_STAGE_MODES, **(stage_modes or {})}
    stage_definitions = [
        ("input", "输入路径与规范化"),
        ("crossings", "识别交叉事件"),
        ("topology", "求解过压与欠压关系"),
        ("construction", "构造切口与可见片段"),
        ("diagnostics", "检查退化与冲突"),
        ("complete", "最终编织图案"),
    ]
    stages = [
        AnimationStage(
            name=name,
            title=title,
            events=[e for e in result.trace if e.stage == name],
            duration=merged_durations.get(name, 1.0),
            include_in_modes=merged_modes.get(name, DEFAULT_STAGE_MODES.get(name, ())),
        )
        for name, title in stage_definitions
    ]
    stages = [stage for stage in stages if stage.events or stage.name == "complete"]
    if mode != "custom":
        stages = [stage for stage in stages if mode in stage.include_in_modes]
    return AnimationPlan(mode=mode, stages=stages, source_trace_count=len(result.trace))
