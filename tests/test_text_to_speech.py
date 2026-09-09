import tempfile
import time
import unittest
from pathlib import Path

from app.core.assistant import Assistant
from app.core.logging import ActivityLogger
from app.core.models import ActionResult, TaskStatus
from app.voice.text_to_speech import AsyncTextToSpeech, Pyttsx3TextToSpeechProvider, TextToSpeechProvider


class FakeBackend(TextToSpeechProvider):
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.stops = 0
        self.error = error

    def speak(self, text: str) -> None:
        self.calls.append(text)
        if self.error:
            raise self.error

    def stop(self) -> None:
        self.stops += 1

    def is_available(self) -> bool:
        return True


class TextToSpeechTests(unittest.TestCase):
    def wait_for(self, condition) -> None:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not condition():
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_provider_initializes_with_mock_engine(self) -> None:
        class Engine:
            def getProperty(self, name):
                return []
            def setProperty(self, name, value):
                pass
            def stop(self):
                pass

        provider = Pyttsx3TextToSpeechProvider(engine=Engine())
        self.assertTrue(provider.is_available())

    def test_speak_reaches_backend(self) -> None:
        backend = FakeBackend()
        tts = AsyncTextToSpeech(backend)
        self.assertTrue(tts.speak("Hello"))
        self.wait_for(lambda: backend.calls == ["Hello"])
        tts.close()

    def test_disabled_tts_does_not_speak(self) -> None:
        backend = FakeBackend()
        tts = AsyncTextToSpeech(backend, enabled=False)
        self.assertFalse(tts.speak("Hello"))
        time.sleep(0.05)
        self.assertEqual(backend.calls, [])
        tts.close()

    def test_failure_is_reported_without_raising(self) -> None:
        errors: list[str] = []
        tts = AsyncTextToSpeech(FakeBackend(RuntimeError("backend failed")), on_error=errors.append)
        self.assertTrue(tts.speak("Hello"))
        self.wait_for(lambda: errors == ["TTS failed: backend failed"])
        tts.close()

    def test_stop_calls_backend_stop(self) -> None:
        backend = FakeBackend()
        tts = AsyncTextToSpeech(backend)
        tts.stop()
        self.assertGreaterEqual(backend.stops, 1)
        tts.close()

    def test_assistant_response_reaches_tts(self) -> None:
        backend = FakeBackend()
        tts = AsyncTextToSpeech(backend)
        with tempfile.TemporaryDirectory() as directory:
            assistant = Assistant(ActivityLogger(Path(directory) / "activity.jsonl"), tts)
            assistant.router.register("open_application", lambda request: ActionResult(TaskStatus.COMPLETED, "Opened safely.", request))
            result = assistant.handle("Open Excel")
            self.assertEqual(result.status, TaskStatus.COMPLETED)
            self.wait_for(lambda: backend.calls == ["Opened safely."])
        tts.close()

    def test_tts_failure_does_not_change_command_result(self) -> None:
        tts = AsyncTextToSpeech(FakeBackend(RuntimeError("backend failed")))
        with tempfile.TemporaryDirectory() as directory:
            assistant = Assistant(ActivityLogger(Path(directory) / "activity.jsonl"), tts)
            assistant.router.register("open_application", lambda request: ActionResult(TaskStatus.COMPLETED, "Command completed.", request))
            result = assistant.handle("Open Excel")
            self.assertEqual(result.message, "Command completed.")
        tts.close()


if __name__ == "__main__":
    unittest.main()