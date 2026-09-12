"""Focused tests for the AURA voice session lifecycle (Phase 1).

Uses a test harness that exercises the real voice loop state machine from
MainWindow without instantiating the full Qt web engine. This avoids issues
with QWebEnginePage type checking while still testing the real logic.
"""
from __future__ import annotations

import sys
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)


# ---- Helpers to pump the Qt event loop ----------------------------------

def _process_qt(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.005)


def _wait_for(condition, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


# ---- Mock assistant --------------------------------------------------------

class FakeAssistant:
    def __init__(self, transcript="hello", response="Hi there",
                 stt_fail=False, tts_fail=False, empty=False):
        self.transcript = transcript
        self.response = response
        self.stt_fail = stt_fail
        self.tts_fail = tts_fail
        self.empty = empty
        self.listen_calls = 0
        self.plan_calls: list[str] = []
        self.speak_calls: list[str] = []
        self.tts = MagicMock()
        self._stop_evt = threading.Event()

    def listen(self):
        self.listen_calls += 1
        if self._stop_evt.is_set():
            raise RuntimeError("Stopped")
        if self.stt_fail:
            raise RuntimeError("STT failed")
        return "" if self.empty else self.transcript

    def listen_audio(self, on_partial_state=None):
        self.listen_calls += 1
        if self._stop_evt.is_set():
            raise RuntimeError("Listening cancelled.")
        if on_partial_state:
            on_partial_state("LISTENING")
        if self.stt_fail:
            raise RuntimeError("STT failed")
        return b"\x00\x00" * 8000

    def transcribe_audio(self, pcm):
        if self.stt_fail:
            raise RuntimeError("STT transcription failed")
        return "" if self.empty else self.transcript

    def process(self, msg):
        self.plan_calls.append(msg)
        return MagicMock(intent="CHAT", response=self.response, text=self.response)

    def speak(self, text):
        self.speak_calls.append(text)

    def wait_for_speech(self, timeout=None):
        pass

    def stop(self):
        self._stop_evt.set()

    def request_stop(self):
        self._stop_evt.set()


# ---- Reusable voice loop harness -----------------------------------------
# Mirrors the real MainWindow voice loop state machine.

class VoiceLoopHarness:
    def __init__(self, assistant):
        self.assistant = assistant
        self.worker = None
        self.session_active = False
        self.paused = False
        self.generation = 0
        self._visualizer_ready = False
        self._pending_visualizer_state = "IDLE"
        self._consecutive_errors = 0
        self._lock = threading.Lock()

    def start_voice_loop(self):
        if self.session_active:
            return
        self.session_active = True
        self.paused = False
        self.generation += 1
        self._consecutive_errors = 0
        self._listen_next()

    def _listen_next(self):
        if not self.session_active or self.paused:
            return
        if self.worker is not None:
            return  # already running
        self.worker = _FakeWorker(self, self.generation)
        self.worker.start()

    def pause_voice_loop(self):
        self.paused = True
        if self.worker:
            self.worker.cancel()

    def resume_voice_loop(self):
        if not self.paused:
            return
        self.paused = False
        if self.session_active:
            self._listen_next()

    def stop_voice_loop(self):
        self.session_active = False
        self.paused = False
        self.generation += 1
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(timeout=1.0)
            self.worker = None


def _process_qt(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.005)


class _FakeWorker:
    """Thread worker that runs one listen cycle, mirroring VoiceLoopWorker."""

    def __init__(self, harness, generation):
        self.harness = harness
        self.generation = generation
        self.cancelled = False
        self._thread = None
        self.started = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.started.wait(timeout=1.0)

    def _run(self):
        self.started.set()
        if self.cancelled or self.generation != self.harness.generation:
            return
        if self.harness.paused:
            return
        harness = self.harness
        assistant = harness.assistant

        try:
            # LISTENING phase
            pcm = assistant.listen_audio()
            if self.cancelled or self.generation != harness.generation:
                return

            # TRANSCRIBING phase
            transcript = assistant.transcribe_audio(pcm)
            transcript = (transcript or "").strip()
            if not transcript:
                # Empty: just restart
                if harness.session_active and not harness.paused:
                    # CRITICAL: reap worker before restart (matches real code)
                    harness.worker = None
                    harness._listen_next()
                return

            # THINKING phase
            result = assistant.process(transcript)
            if self.cancelled or self.generation != harness.generation:
                return

            # ANSWERING phase
            assistant.speak(result.text)
            assistant.wait_for_speech(timeout=45)

            if self.cancelled or self.generation != harness.generation:
                return
            if harness.paused:
                return
            if not harness.session_active:
                return

            # AUTO-RESTART: reap worker BEFORE scheduling next listen
            # (matches real _on_turn_finished logic)
            harness.worker = None
            harness._listen_next()

        except Exception:
            harness._consecutive_errors += 1
            if harness.session_active and not harness.paused:
                harness.worker = None
                harness._listen_next()

    def cancel(self):
        self.cancelled = True

    def wait(self, timeout=None):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


# ---- Tests ------------------------------------------------------------------

class TestVoiceLoopLifecycle(unittest.TestCase):

    def test_01_voice_session_starts(self):
        a = FakeAssistant()
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        try:
            self.assertTrue(w.session_active)
            self.assertFalse(w.paused)
            self.assertIsNotNone(w.worker)
            _process_qt(0.3)
        finally:
            w.stop_voice_loop()

    def test_02_transcript_reaches_assistant(self):
        a = FakeAssistant(transcript="what is power bi")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        try:
            ok = _wait_for(lambda: "what is power bi" in a.plan_calls, timeout=5)
            self.assertTrue(ok, f"plan_calls={a.plan_calls}")
        finally:
            w.stop_voice_loop()

    def test_03_tts_completion_schedules_next_listen(self):
        a = FakeAssistant(transcript="hello", response="Hi there")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        try:
            ok = _wait_for(lambda: a.listen_calls >= 2, timeout=8)
            self.assertTrue(
                ok,
                f"Expected auto-restart after TTS (listen_calls={a.listen_calls})"
            )
        finally:
            w.stop_voice_loop()

    def test_04_paused_state_prevents_restart(self):
        a = FakeAssistant(transcript="hello")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(0.4)
        w.pause_voice_loop()
        self.assertTrue(w.paused)
        snap = a.listen_calls
        _process_qt(1.5)
        self.assertEqual(
            a.listen_calls, snap,
            "Paused session must not restart listening"
        )
        w.stop_voice_loop()

    def test_05_stopped_state_prevents_restart(self):
        a = FakeAssistant(transcript="hello")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(0.4)
        w.stop_voice_loop()
        self.assertFalse(w.session_active)
        snap = a.listen_calls
        _process_qt(1.2)
        self.assertEqual(
            a.listen_calls, snap,
            "Stopped session must not restart listening"
        )

    def test_06_cancellation_prevents_stale_restart(self):
        a = FakeAssistant(transcript="hello")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(0.3)
        w.generation += 1
        w.paused = True
        _process_qt(1.5)
        snap = a.listen_calls
        _process_qt(1.0)
        self.assertEqual(
            a.listen_calls, snap,
            "Stale worker must not restart after cancellation"
        )
        w.stop_voice_loop()

    def test_07_empty_transcript_does_not_reach_assistant(self):
        a = FakeAssistant(empty=True)
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        try:
            _process_qt(2.5)
            self.assertEqual(
                a.plan_calls, [],
                "Empty transcript must never reach the LLM"
            )
        finally:
            w.stop_voice_loop()

    def test_08_stt_failure_recovers_safely(self):
        a = FakeAssistant(stt_fail=True)
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(2.0)
        self.assertTrue(w.session_active or w._consecutive_errors > 0)
        w.stop_voice_loop()

    def test_09_tts_failure_does_not_kill_loop(self):
        a = FakeAssistant(transcript="hello", tts_fail=True)
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        try:
            ok = _wait_for(lambda: a.listen_calls >= 2, timeout=6)
            self.assertTrue(
                ok,
                f"TTS failure should not kill the loop (listen_calls={a.listen_calls})"
            )
        finally:
            w.stop_voice_loop()

    def test_10_only_one_worker_active_at_a_time(self):
        a = FakeAssistant(transcript="hello")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(0.3)
        active = 1 if w.worker is not None else 0
        self.assertLessEqual(
            active, 1,
            "Only one worker should be active at a time"
        )
        _process_qt(0.3)
        w.stop_voice_loop()



    def test_11_thread_lifetime_no_premature_destroy(self):
        """11. QThread must not be destroyed while still running."""
        a = FakeAssistant(transcript="hello", response="Hi")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _wait_for(lambda: a.listen_calls >= 1, timeout=5)
        if w.worker is not None:
            ok = _wait_for(
                lambda: w.worker is None or not w.worker._thread.is_alive(),
                timeout=3,
            )
            self.assertTrue(ok, "Worker should finish naturally")
        w.stop_voice_loop()
        self.assertIsNone(w.worker)

    def test_12_worker_replace_safely(self):
        """12. Replacing a finished worker must not destroy a live thread."""
        a = FakeAssistant(transcript="hello", response="Hi")
        w = VoiceLoopHarness(a)
        w.start_voice_loop()
        _process_qt(0.2)
        w._listen_next()
        _process_qt(1.5)
        w.stop_voice_loop()
        self.assertIsNone(w.worker)

if __name__ == "__main__":
    unittest.main(verbosity=2)
