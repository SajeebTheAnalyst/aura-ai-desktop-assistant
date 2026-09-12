"""Non-blocking local Windows TTS with reliable per-utterance SAPI sessions."""
from __future__ import annotations

import queue
import threading
import time
from typing import Any

_WARMUP = object()
_STOP_CURRENT = object()
_SHUTDOWN = object()


class TTSService:
    """Every reply is spoken by a fresh SAPI5 engine on one dedicated thread.

    Some Windows SAPI/pyttsx3 installations accept the first ``runAndWait``
    call but silently stop rendering later calls on a reused engine. Creating
    the engine per utterance avoids that stale-engine state while preserving a
    single non-blocking AURA speech queue.
    """

    def __init__(self, rate: int = 175, volume: float = 1.0) -> None:
        self._rate = rate
        self._volume = volume
        self._queue: queue.Queue[Any] = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._shutdown_event = threading.Event()
        self.last_error = ""
        self.last_status = "idle"
        self._current_engine = None
        self._thread = threading.Thread(target=self._loop, name="aura-tts", daemon=True)
        self._thread.start()

    def _make_engine(self):
        import pyttsx3
        engine = pyttsx3.init(driverName="sapi5")
        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)
        return engine

    def _release_engine(self, engine) -> None:
        try:
            engine.stop()
        except Exception:
            pass
        if self._current_engine is engine:
            self._current_engine = None

    def _loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is _SHUTDOWN:
                break
            if item is _WARMUP:
                print("[TTS] Ready: Windows SAPI5 speech worker online")
                self.last_status = "ready"
                continue
            if item is _STOP_CURRENT:
                print("[TTS] Stop requested")
                engine = self._current_engine
                if engine is not None:
                    self._release_engine(engine)
                self.last_status = "stopped"
                self._idle.set()
                continue

            text = str(item).strip()
            if not text:
                self._idle.set()
                continue
            engine = None
            try:
                self.last_status = "speaking"
                print(f"[TTS] Speaking ({len(text)} chars): {text[:80]!r}")
                engine = self._make_engine()
                self._current_engine = engine
                engine.say(text)
                engine.runAndWait()
                self.last_status = "idle"
                print("[TTS] Playback completed")
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.last_status = "error"
                print(f"[TTS] Playback failed: {self.last_error}")
            finally:
                if engine is not None:
                    self._release_engine(engine)
                self._idle.set()

    @property
    def available(self) -> bool:
        return self._thread.is_alive()

    def warmup(self) -> None:
        if self._thread.is_alive():
            self._queue.put(_WARMUP)

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not self._thread.is_alive():
            self.last_error = "TTS worker is not running."
            self.last_status = "error"
            print(f"[TTS] Playback failed: {self.last_error}")
            return
        self._idle.clear()
        self._queue.put(text)

    def is_speaking(self) -> bool:
        return not self._idle.is_set()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    def stop(self) -> None:
        """Stop current/queued speech without disabling future replies."""
        if not self._thread.is_alive():
            return
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(_STOP_CURRENT)

    def shutdown(self) -> None:
        self._shutdown_event.set()
        self._queue.put(_SHUTDOWN)