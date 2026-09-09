from __future__ import annotations

from collections.abc import Callable

from app.core.models import ActionRequest, ActionResult, TaskStatus

ActionHandler = Callable[[ActionRequest], ActionResult]


class CommandRouter:
    """Allowlist-only bridge between plans and device actions."""
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, intent: str, handler: ActionHandler) -> None:
        self._handlers[intent] = handler

    def execute(self, request: ActionRequest) -> ActionResult:
        handler = self._handlers.get(request.intent)
        if handler is None:
            return ActionResult(TaskStatus.FAILED, f"'{request.intent}' is not an approved AURA action.", request)
        return handler(request)
