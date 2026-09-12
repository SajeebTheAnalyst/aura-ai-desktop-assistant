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
        self._stop_event = Event()
        self.tts.warmup()
        self.llm.warmup()  # pre-build the Gemini client off the voice thread

    def listen(self) -> str:
        return self.stt.listen_once(self._stop_event)

    def listen_audio(self, on_partial_state=None, cancel_event: Event | None = None) -> bytes:
        """Capture one full utterance (VAD-segmented PCM) without transcribing.

        Raises RuntimeError for cancellation, silence timeouts, and fragments.
        """
        return self.stt.listen_segmented(cancel_event or self._stop_event, on_state=on_partial_state)

    def transcribe_audio(self, pcm: bytes) -> str:
        return self.stt.transcribe(pcm)

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
                case Intent.OPEN_APP | Intent.SYSTEM_ACTION | Intent.WEB_SEARCH | Intent.PLAY_MUSIC:
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
        self._stop_event.set()
        self.tts.stop()

    def ping(self) -> None:
        """ASGI lifespan hook compatibility: clear the stop flag so a restarted
        engine in the same process (tests, reloads) starts a fresh session."""
        if self._stop_event.is_set():
            self._stop_event.clear()

    def request_stop(self) -> None:
        """Signal cancellation; the current voice turn ends at the next checkpoint."""
        self._stop_event.set()