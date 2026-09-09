from __future__ import annotations

import os
import queue
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class TextToSpeechError(RuntimeError):
    pass


class TextToSpeechProvider(ABC):
    @abstractmethod
    def speak(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError


class Pyttsx3TextToSpeechProvider(TextToSpeechProvider):
    def __init__(self, engine: Any | None = None) -> None:
        try:
            import pyttsx3
            self.engine = engine or pyttsx3.init()
        except Exception as exc:
            raise TextToSpeechError(f"Local TTS is unavailable: {exc}") from exc
        try:
            self._configure()
        except Exception as exc:
            raise TextToSpeechError(f"Invalid TTS configuration: {exc}") from exc

    def _configure(self) -> None:
        voice_id = os.getenv("AURA_TTS_VOICE", "").strip()
        if voice_id:
            available = {voice.id for voice in self.list_voices()}
            if voice_id in available:
                self.engine.setProperty("voice", voice_id)
        rate = os.getenv("AURA_TTS_RATE", "").strip()
        volume = os.getenv("AURA_TTS_VOLUME", "").strip()
        if rate:
            self.engine.setProperty("rate", int(rate))
        if volume:
            self.engine.setProperty("volume", float(volume))

    def speak(self, text: str) -> None:
        if text.strip():
            self.engine.say(text)
            self.engine.runAndWait()

    def stop(self) -> None:
        self.engine.stop()

    def is_available(self) -> bool:
        return self.engine is not None

    def list_voices(self) -> list[Any]:
        return list(self.engine.getProperty("voices") or [])


@dataclass
class _SpeechRequest:
    text: str


class AsyncTextToSpeech:
    def __init__(
        self,
        provider: TextToSpeechProvider | None = None,
        enabled: bool | None = None,
        on_status: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.enabled = self._env_enabled() if enabled is None else enabled
        self.on_status = on_status
        self.on_error = on_error
        self._provider_error: str | None = None
        try:
            self.provider = provider
        except TextToSpeechError as exc:
            self.provider = None
            self._provider_error = str(exc)
        self._queue: queue.Queue[_SpeechRequest | None] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="aura-tts", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    @staticmethod
    def _env_enabled() -> bool:
        return os.getenv("AURA_TTS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}

    def is_available(self) -> bool:
        return bool(self.provider and self.provider.is_available())

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.stop()

    def speak(self, text: str) -> bool:
        if not self.enabled or not text.strip() or not self.is_available():
            return False
        self.stop()
        request = _SpeechRequest(text)
        try:
            self._queue.put_nowait(request)
        except queue.Full:
            return False
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self.provider:
            try:
                self.provider.stop()
            except Exception as exc:
                self._report_error(f"TTS stop failed: {exc}")
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._stop_event.clear()

    def close(self) -> None:
        self.stop()
        self._queue.put(None)
        self._thread.join(timeout=1)

    def _run(self) -> None:
        if self.provider is None:
            try:
                self.provider = Pyttsx3TextToSpeechProvider()
            except TextToSpeechError as exc:
                self._provider_error = str(exc)
                self._report_error(str(exc))
        self._ready.set()
        while True:
            request = self._queue.get()
            if request is None:
                return
            if self._stop_event.is_set() or not self.enabled or not self.provider:
                continue
            self._report_status("Speaking")
            try:
                self.provider.speak(request.text)
            except Exception as exc:
                self._report_error(f"TTS failed: {exc}")
            finally:
                self._report_status("Idle")

    def _report_status(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)

    def _report_error(self, message: str) -> None:
        if self.on_error:
            self.on_error(message)
