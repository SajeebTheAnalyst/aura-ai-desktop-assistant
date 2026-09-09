from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(str, Enum):
    READY = "ready"
    NEEDS_CONFIRMATION = "needs_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ActionRequest:
    intent: str
    parameters: dict[str, Any] = field(default_factory=dict)
    original_text: str = ""


@dataclass(frozen=True)
class ActionResult:
    status: TaskStatus
    message: str
    action: ActionRequest | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredCommand:
    steps: tuple[ActionRequest, ...]
    response_language: str = "en"
    explanation: str = ""
