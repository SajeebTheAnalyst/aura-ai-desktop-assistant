"""Non-blocking text-to-speech on a dedicated engine thread.

pyttsx3 engines must be created and driven from the same thread, so this
service owns exactly one worker thread and a queue. ``speak()`` only enqueues
text and returns immediately; the worker initializes the engine lazily and
speaks each utterance in order. ``warmup()`` pre-initializes the engine right
after app start so the very first spoken reply is instant.

If an utterance fails (dead COM object, crashed audio driver, device change),
the error is caught silently, the engine is re-initialized and the utterance is
retried - callers never see audio failures, so the assistant never says things
like "I cannot produce sound".
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any

_WARMUP = object()  # sentinel: initialize the engine without speaking
_STOP = object()    # sentinel: shut the worker down


class TTSService:
    def __init__(self, rate: int = 175) -> None:
        self._rate = rate
        self._queue: queue.Queue[Any] = queue.Queue()
        self._idle = threading.Event()
        self._idle.set()
        self._stop_event = threading.Event()
        self.last_error = ""
        self._thread = threading.Thread(target=self._loop, name="aura-tts", daemon=True)
        self._thread.start()

    def _make_engine(self):
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", self._rate)
        return engine

    def _loop(self) -> None:
        engine = None
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is _STOP:
                break
            if item is _WARMUP:
                if engine is None:
                    try:
                        engine = self._make_engine()
                    except Exception as exc:
                        self.last_error = str(exc)
                continue
            # A real utterance. If the audio engine fails (dead COM object,
            # crashed driver, device change), catch it SILENTLY, re-initialize
            # the engine and retry - the LLM/voice loop never sees the failure
            # and never says anything like "I cannot produce sound".
            text = item
            for attempt in range(3):
                try:
                    if engine is None:
                        engine = self._make_engine()
                    engine.say(text)
                    engine.runAndWait()
                    break
                except Exception as exc:
                    self.last_error = str(exc)
                    if engine is not None:
                        try:
                            engine.stop()
                        except Exception:
                            pass
                    engine = None  # force a fresh engine on the next attempt
                    time.sleep(0.25 * (attempt + 1))
            self._idle.set()  # finished (spoken, or retries exhausted - silently)

    def warmup(self) -> None:
        """Pre-initialize the engine in the background (never blocks)."""
        self._queue.put(_WARMUP)

    def speak(self, text: str) -> None:
        """Start speaking *text* on the worker thread and return immediately."""
        text = (text or "").strip()
        if not text:
            return
        self._idle.clear()
        self._queue.put(text)

    def is_speaking(self) -> bool:
        return not self._idle.is_set()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until the current utterance finishes (or ``timeout`` passes)."""
        return self._idle.wait(timeout)

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(_STOP)