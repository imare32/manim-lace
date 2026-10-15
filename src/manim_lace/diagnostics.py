"""Structured diagnostics emitted by the geometry and topology pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable, machine-readable diagnostic; messages are for humans only."""

    code: str
    severity: Severity
    message: str
    path_ids: tuple[str, ...] = ()
    crossing_id: str | None = None
    point: tuple[float, float] | None = None
    hints: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


class LaceError(RuntimeError):
    """Base exception for errors with domain-specific meaning."""


class InputPathError(LaceError, ValueError):
    """Raised when input cannot be represented as a valid 2D path."""


class WeaveConflictError(LaceError):
    """Raised when the requested weave constraints cannot be satisfied."""
