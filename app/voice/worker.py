from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from app.voice.errors import SpeechToTextCancelled, SpeechToTextError
from app.voice.speech_to_text import SpeechToTextProvider


class VoiceCaptureWorker(QObject):
    """Runs blocking microphone/STT work outside the Qt UI thread."""

    status_changed = Signal(str)
    transcript_ready = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, provider: SpeechToTextProvider, cancel_event: Event) -> None:
        super().__init__()
        self.provider = provider
        self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        try:
            if self.cancel_event.is_set():
                raise SpeechToTextCancelled("Listening cancelled.")
            self.status_changed.emit("Listening…")
            transcript = self.provider.listen_once(self.cancel_event)
            if self.cancel_event.is_set():
                raise SpeechToTextCancelled("Listening cancelled.")
            self.status_changed.emit("Transcription complete.")
            self.transcript_ready.emit(transcript)
        except SpeechToTextCancelled:
            self.cancelled.emit()
        except SpeechToTextError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # defensive boundary for third-party drivers/providers
            self.failed.emit(f"Voice input failed: {exc}")
        finally:
            self.finished.emit()
