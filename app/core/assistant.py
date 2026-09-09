from __future__ import annotations

from app.ai.intent_parser import IntentParser
from app.ai.llm_client import LLMError, LLMProvider, OpenAILLMProvider
from app.core.actions import SafeActions
from app.core.command_router import CommandRouter
from app.core.logging import ActivityLogger
from app.core.models import ActionRequest, ActionResult, StructuredCommand, TaskStatus
from app.core.permissions import PermissionManager
from app.core.state import AssistantState
from app.voice.text_to_speech import AsyncTextToSpeech


class Assistant:
    def __init__(self, logger: ActivityLogger, tts: AsyncTextToSpeech | None = None, llm: LLMProvider | None = None) -> None:
        self.state = AssistantState()
        self.parser = IntentParser()
        self.llm = llm if llm is not None else OpenAILLMProvider.from_environment()
        self.permissions = PermissionManager()
        self.router = CommandRouter()
        self.logger = logger
        self.tts = tts or AsyncTextToSpeech()
        actions = SafeActions(self.state.cancel_event)
        for intent in ("open_website", "browser_search", "open_application", "close_application",
                   "type_text", "press_key", "hotkey"):
            self.router.register(intent, getattr(actions, intent))

    def start_listening(self) -> bool:
        return self.state.start_listening()

    def finish_listening(self) -> None:
        self.state.finish_listening()

    def handle_voice_transcript(self, transcript: str) -> ActionResult:
        return self.handle(transcript, reset_cancellation=False)

    def record_voice_event(self, event: str, message: str) -> None:
        self.logger.record_voice_event(event, message)

    def handle(self, command: str, confirmed: bool = False, reset_cancellation: bool = True) -> ActionResult:
        if reset_cancellation:
            self.state.reset_task()
        request = self.parser.parse(command)
        if request and request.intent == "cancel":
            self.state.cancel()
            self.tts.stop()
            return ActionResult(TaskStatus.CANCELLED, "Current task cancelled.", request)
        structured = self._understand(command)
        if structured is not None:
            if self.state.cancel_event.is_set():
                return ActionResult(TaskStatus.CANCELLED, "Current task cancelled.")
            return self._execute_steps(structured.steps, confirmed)
        if request is None:
            result = ActionResult(TaskStatus.FAILED, "I couldn't safely interpret that yet. Try asking me to open an approved app or search the web.")
            self.tts.speak(result.message)
            return result
        if self.permissions.requires_confirmation(request) and not confirmed:
            result = ActionResult(TaskStatus.NEEDS_CONFIRMATION, f"This is a {self.permissions.risk_for(request).value}-risk action. Confirm before I continue.", request)
            self.tts.speak(result.message)
            return result
        result = ActionResult(TaskStatus.CANCELLED, "Current task cancelled.", request) if self.state.cancel_event.is_set() else self.router.execute(request)
        self.logger.record(request, result, confirmed)
        if result.status is not TaskStatus.CANCELLED:
            self.tts.speak(result.message)
        return result

    def cancel(self) -> None:
        self.state.cancel()
        self.tts.stop()

    def _understand(self, command: str) -> StructuredCommand | None:
        if self.llm is None:
            return None
        try:
            return self.llm.understand_command(command, self.state.cancel_event)
        except LLMError as exc:
            self.logger.record_ai_event("failed", "AI command understanding was unavailable.")
            return None

    def _execute_steps(self, steps: tuple[ActionRequest, ...], confirmed: bool) -> ActionResult:
        if not steps:
            return ActionResult(TaskStatus.FAILED, "I couldn't map that safely to a supported AURA action.")
        results: list[ActionResult] = []
        for request in steps:
            if self.state.cancel_event.is_set():
                return ActionResult(TaskStatus.CANCELLED, "Current task cancelled.", request)
            if self.permissions.requires_confirmation(request) and not confirmed:
                result = ActionResult(TaskStatus.NEEDS_CONFIRMATION, f"This is a {self.permissions.risk_for(request).value}-risk action. Confirm before I continue.", request)
                self.tts.speak(result.message)
                return result
            result = self.router.execute(request)
            self.logger.record(request, result, confirmed)
            results.append(result)
            if result.status is not TaskStatus.COMPLETED:
                self.tts.speak(result.message)
                return result
        final = results[-1]
        self.tts.speak(" ".join(result.message for result in results))
        return ActionResult(final.status, " ".join(result.message for result in results), final.action,
                            {"steps": len(results)})