from __future__ import annotations

from threading import Event

from app.automation.application import ApplicationAdapter
from app.automation.browser import BrowserAdapter
from app.automation.keyboard import KeyboardAdapter, WindowsKeyboardAdapter
from app.core.models import ActionRequest, ActionResult, TaskStatus


class SafeActions:
    def __init__(self, cancel_event: Event | None = None, applications: ApplicationAdapter | None = None,
                 browser: BrowserAdapter | None = None, keyboard: KeyboardAdapter | None = None) -> None:
        self.cancel_event = cancel_event
        self.applications = applications or ApplicationAdapter()
        self.browser = browser or BrowserAdapter()
        self.keyboard = keyboard or WindowsKeyboardAdapter()

    def _cancelled(self, request: ActionRequest) -> ActionResult | None:
        if self.cancel_event and self.cancel_event.is_set():
            return ActionResult(TaskStatus.CANCELLED, "Current task cancelled.", request)
        return None

    def open_website(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        outcome = self.browser.open_website(str(request.parameters.get("url", "")), self.cancel_event)
        return self._result(request, outcome.success, outcome.message, outcome.verified)

    def browser_search(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        outcome = self.browser.search(str(request.parameters.get("query", "")), self.cancel_event)
        return self._result(request, outcome.success, outcome.message, outcome.verified)

    def open_application(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        outcome = self.applications.open(str(request.parameters.get("application", "")), self.cancel_event)
        return self._result(request, outcome.success, outcome.message, outcome.verified)

    def close_application(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        outcome = self.applications.close(str(request.parameters.get("application", "")), self.cancel_event)
        return self._result(request, outcome.success, outcome.message, outcome.verified)

    def type_text(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        text = str(request.parameters.get("text", ""))
        if not text:
            return ActionResult(TaskStatus.FAILED, "I need text before I can type it.", request)
        try:
            self.keyboard.type_text(text, self.cancel_event)
        except InterruptedError:
            return ActionResult(TaskStatus.CANCELLED, "Typing cancelled.", request)
        except (OSError, RuntimeError, ValueError) as exc:
            return ActionResult(TaskStatus.FAILED, f"I could not type that text: {exc}", request)
        return self._result(request, True, "Text entered.", True)

    def press_key(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        try:
            self.keyboard.press_key(str(request.parameters.get("key", "")), self.cancel_event)
        except InterruptedError:
            return ActionResult(TaskStatus.CANCELLED, "Key press cancelled.", request)
        except (OSError, RuntimeError, ValueError) as exc:
            return ActionResult(TaskStatus.FAILED, f"I could not press that key: {exc}", request)
        return self._result(request, True, f"Pressed {request.parameters.get('key')}", True)

    def hotkey(self, request: ActionRequest) -> ActionResult:
        cancelled = self._cancelled(request)
        if cancelled:
            return cancelled
        keys = tuple(str(key) for key in request.parameters.get("keys", []))
        try:
            self.keyboard.hotkey(keys, self.cancel_event)
        except InterruptedError:
            return ActionResult(TaskStatus.CANCELLED, "Hotkey cancelled.", request)
        except (OSError, RuntimeError, ValueError) as exc:
            return ActionResult(TaskStatus.FAILED, f"I could not press that hotkey: {exc}", request)
        return self._result(request, True, f"Pressed {'+'.join(keys)}.", True)

    @staticmethod
    def _result(request: ActionRequest, success: bool, message: str, verified: bool) -> ActionResult:
        return ActionResult(TaskStatus.COMPLETED if success else TaskStatus.FAILED, message, request,
                            {"verified": verified})
