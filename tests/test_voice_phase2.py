import tempfile
import unittest
from pathlib import Path
from threading import Event

from app.core.assistant import Assistant
from app.core.logging import ActivityLogger
from app.core.models import ActionResult, TaskStatus
from app.voice.errors import SpeechToTextCancelled, TranscriptionError
from app.voice.speech_to_text import SpeechToTextProvider
from app.voice.worker import VoiceCaptureWorker


class FakeSpeechProvider(SpeechToTextProvider):
    def __init__(self, transcript: str = "Open Excel", error: Exception | None = None) -> None:
        self.transcript = transcript
        self.error = error

    def listen_once(self, cancel_event: Event) -> str:
        if self.error:
            raise self.error
        if cancel_event.is_set():
            raise SpeechToTextCancelled("Listening cancelled.")
        return self.transcript


class VoicePhase2Tests(unittest.TestCase):
    def make_assistant(self) -> Assistant:
        self.temp_dir = tempfile.TemporaryDirectory()
        return Assistant(ActivityLogger(Path(self.temp_dir.name) / "activity.jsonl"))

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def test_transcript_reaches_existing_assistant_pipeline(self) -> None:
        assistant = self.make_assistant()
        calls: list[str] = []

        def open_excel(request):
            calls.append(request.intent)
            return ActionResult(TaskStatus.COMPLETED, "Opened safely.", request)

        assistant.router.register("open_application", open_excel)
        self.assertTrue(assistant.start_listening())
        transcript = FakeSpeechProvider().listen_once(assistant.state.cancel_event)
        result = assistant.handle_voice_transcript(transcript)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(calls, ["open_application"])

    def test_cancellation_prevents_voice_action_routing(self) -> None:
        assistant = self.make_assistant()
        calls: list[str] = []
        assistant.router.register("open_application", lambda request: calls.append(request.intent))
        assistant.start_listening()
        assistant.cancel()
        result = assistant.handle_voice_transcript("Open Excel")
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(calls, [])

    def test_pause_prevents_listening_session(self) -> None:
        assistant = self.make_assistant()
        assistant.state.paused = True
        self.assertFalse(assistant.start_listening())

    def test_worker_reports_transcription_failure(self) -> None:
        errors: list[str] = []
        worker = VoiceCaptureWorker(FakeSpeechProvider(error=TranscriptionError("No speech")), Event())
        worker.failed.connect(errors.append)
        worker.run()
        self.assertEqual(errors, ["No speech"])

    def test_worker_reports_cancellation(self) -> None:
        cancelled: list[bool] = []
        event = Event(); event.set()
        worker = VoiceCaptureWorker(FakeSpeechProvider(), event)
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.run()
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
