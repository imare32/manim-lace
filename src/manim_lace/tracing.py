"""Bounded trace payloads shared by the pipeline stages.

A trace has to stay finite for any input size, but a shortened list must never
look like a complete one. :class:`BoundedRecords` counts every record exactly,
keeps a bounded prefix, and says whether it had to drop the rest, so a consumer can
tell "there were 12" from "there were at least 12". :meth:`BoundedRecords.as_payload`
emits the same three keys everywhere (``<key>``, ``<key>_count``,
``<key>_truncated``), which keeps the sampling, region and topology payloads
consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["DEFAULT_TRACE_RECORD_LIMIT", "BoundedRecords"]

#: How many records of one kind a single trace event keeps by default.
DEFAULT_TRACE_RECORD_LIMIT = 64


@dataclass(slots=True)
class BoundedRecords:
    """An exact record count with a bounded, order-preserving list of records."""

    limit: int = DEFAULT_TRACE_RECORD_LIMIT
    _entries: list[dict[str, Any]] = field(default_factory=list, init=False)
    _total: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 0:
            raise ValueError(f"limit must be a non-negative integer; got {self.limit!r}")

    def add(self, record: dict[str, Any]) -> bool:
        """Count ``record``; keep it when the limit is not reached yet."""
        self._total += 1
        if len(self._entries) < self.limit:
            self._entries.append(dict(record))
            return True
        return False

    def extend(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            self.add(record)

    @property
    def total(self) -> int:
        """How many records were offered, kept or not."""
        return self._total

    @property
    def entries(self) -> list[dict[str, Any]]:
        """The records that were kept, in insertion order."""
        return list(self._entries)

    @property
    def truncated(self) -> bool:
        """Whether at least one record was dropped."""
        return self._total > len(self._entries)

    def as_payload(self, key: str) -> dict[str, Any]:
        """``{key: [...], key_count: N, key_truncated: bool}`` for a trace event."""
        return {
            key: self.entries,
            f"{key}_count": self._total,
            f"{key}_truncated": self.truncated,
        }
