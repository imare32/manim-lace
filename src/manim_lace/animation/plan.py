"""Renderer-neutral animation stages derived from the algorithm trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..model import LaceResult, TraceEvent

AnimationMode = Literal["overview", "algorithm", "construction", "debug", "custom"]


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

    def for_mode(self, mode: str) -> "AnimationPlan":
        return AnimationPlan(
            mode=mode,
            stages=[s for s in self.stages if mode in s.include_in_modes],
            source_trace_count=self.source_trace_count,
        )


def build_animation_plan(result: LaceResult, mode: AnimationMode = "overview") -> AnimationPlan:
    """Group actual trace events into pedagogically meaningful phases."""
    stage_definitions = [
        ("input", "输入路径与规范化", 1.4, ("overview", "algorithm", "construction", "debug")),
        ("crossings", "识别交叉事件", 1.4, ("overview", "algorithm", "debug")),
        ("topology", "求解过压与欠压关系", 1.4, ("overview", "algorithm", "debug")),
        ("construction", "构造切口与可见片段", 1.4, ("overview", "algorithm", "construction", "debug")),
        ("diagnostics", "检查退化与冲突", 1.0, ("algorithm", "debug")),
        ("complete", "最终编织图案", 1.8, ("overview", "algorithm", "construction", "debug")),
    ]
    stages = [
        AnimationStage(
            name=name,
            title=title,
            events=[e for e in result.trace if e.stage == name],
            duration=duration,
            include_in_modes=modes,
        )
        for name, title, duration, modes in stage_definitions
    ]
    stages = [stage for stage in stages if stage.events or stage.name == "complete"]
    if mode != "custom":
        stages = [stage for stage in stages if mode in stage.include_in_modes]
    return AnimationPlan(mode=mode, stages=stages, source_trace_count=len(result.trace))
