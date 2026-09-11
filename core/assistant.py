"""AURA coordinator: fast intent planning, OS control, and non-blocking speech.

The voice loop is deliberately fault-tolerant:
- if intent parsing / generation fails, the raw request is treated as plain
  CHAT text and spoken directly (no canned "could not process" block);
- ``speak()`` is non-blocking, so the worker never stalls on TTS;
- ``_execute`` never raises, so a backend error can not crash the loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event

from services.llm_service import CommandPlan, Intent, LLMService
from services.stt_service import STTService
from services.system_control import execute_system_command
from services.tts_service import TTSService


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    plan: CommandPlan


class Assistant:
    def __init__(self) -> None:
        self.llm = LLMService()
        self.tts = TTSService()
        self.stt = STTService()
        self._cancel_event = Event()
        self.tts.warmup()
        self.llm.warmup()  # pre-build the Gemini client off the voice thread

    def listen(self) -> str:
        self._cancel_event.clear()
        return self.stt.listen_once(self._cancel_event)

    def process(self, message: str) -> AssistantResponse:
        text = (message or "").strip()
        try:
            plan = self.llm.plan(text)
        except Exception:
            # JSON / network failure -> speak the raw request as plain CHAT.
            plan = CommandPlan.chat(text)
        return AssistantResponse(self._execute(plan), plan)

    def _execute(self, plan: CommandPlan) -> str:
        try:
            match plan.intent:
                case Intent.CHAT:
                    return plan.response
                case Intent.OPEN_APP | Intent.SYSTEM_ACTION | Intent.WEB_SEARCH:
                    return execute_system_command(
                        {"intent": plan.intent.value, "target": plan.target, "response": plan.response}
                    )
            return plan.response
        except Exception as exc:  # last resort - never throw out of the loop
            return plan.response or f"I hit a snag, but I am still here. {exc}"

    def speak(self, text: str) -> None:
        """Non-blocking: hands the reply to the background TTS thread."""
        self.tts.speak(text)

    def wait_for_speech(self, timeout: float | None = 45.0) -> None:
        """Block until the current utterance finishes (STT stays paused meanwhile)."""
        self.tts.wait_until_idle(timeout)

    def stop(self) -> None:
        self._cancel_event.set()
        self.tts.stop()