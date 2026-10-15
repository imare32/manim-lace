"""Deterministic, structured records emitted by real algorithm stages."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..model import TraceEvent


class TraceRecorder:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def emit(
        self,
        stage: str,
        event_type: str,
        message: str,
        *,
        object_ids: tuple[str, ...] = (),
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            sequence=len(self._events),
            stage=stage,
            event_type=event_type,
            message=message,
            object_ids=object_ids,
            data=data or {},
        )
        self._events.append(event)
        return event


def trace_to_jsonable(events: list[TraceEvent]) -> list[dict[str, Any]]:
    """Return JSON-serializable trace data without losing stable sequence IDs."""
    return [asdict(event) for event in events]
