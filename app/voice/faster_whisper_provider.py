from __future__ import annotations

from queue import Empty, Queue
from threading import Event
from time import monotonic
from typing import Any

from app.voice.errors import MicrophoneUnavailableError, SpeechToTextCancelled, TranscriptionError
from app.voice.speech_to_text import SpeechToTextProvider


class FasterWhisperProvider(SpeechToTextProvider):
    """Local multilingual microphone transcription using Faster-Whisper.

    Imports are delayed so the desktop application can still explain a missing
    optional voice dependency instead of failing during startup.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        sample_rate: int = 16_000,
        max_seconds: float = 8.0,
        silence_seconds: float = 1.2,
        speech_threshold: float = 0.015,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.sample_rate = sample_rate
        self.max_seconds = max_seconds
        self.silence_seconds = silence_seconds
        self.speech_threshold = speech_threshold
        self._model: Any | None = None

    @staticmethod
    def microphone_available() -> tuple[bool, str]:
        try:
            import sounddevice as sd

            device = sd.query_devices(kind="input")
            return True, str(device["name"])
        except Exception as exc:  # sounddevice exposes platform-specific errors
            return False, str(exc)

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError("Faster-Whisper is not installed. Run pip install -r requirements.txt.") from exc
        try:
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        except Exception as exc:
            raise TranscriptionError(f"Unable to load the speech model: {exc}") from exc
        return self._model

    def listen_once(self, cancel_event: Event) -> str:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise MicrophoneUnavailableError("Microphone dependencies are not installed.") from exc

        available, detail = self.microphone_available()
        if not available:
            raise MicrophoneUnavailableError(f"No usable microphone was found: {detail}")

        blocks: Queue[Any] = Queue()

        def on_audio(indata: Any, _frames: int, _time: Any, status: Any) -> None:
            if status:
                return
            blocks.put(indata.copy())

        chunks: list[Any] = []
        started_speaking = False
        last_speech_at = monotonic()
        started_at = monotonic()
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32", callback=on_audio):
                while monotonic() - started_at < self.max_seconds:
                    if cancel_event.is_set():
                        raise SpeechToTextCancelled("Listening cancelled.")
                    try:
                        chunk = blocks.get(timeout=0.05)
                    except Empty:
                        continue
                    chunks.append(chunk)
                    rms = float(np.sqrt(np.mean(np.square(chunk))))
                    now = monotonic()
                    if rms >= self.speech_threshold:
                        started_speaking = True
                        last_speech_at = now
                    elif started_speaking and now - last_speech_at >= self.silence_seconds:
                        break
        except SpeechToTextCancelled:
            raise
        except Exception as exc:
            raise MicrophoneUnavailableError(f"Could not capture microphone audio: {exc}") from exc

        if cancel_event.is_set():
            raise SpeechToTextCancelled("Listening cancelled.")
        if not started_speaking or not chunks:
            raise TranscriptionError("I did not detect speech. Check your microphone and try again.")

        audio = np.concatenate(chunks, axis=0).reshape(-1)
        try:
            segments, _info = self._load_model().transcribe(audio, language=None, vad_filter=True, beam_size=5)
            transcript = "".join(segment.text for segment in segments).strip()
        except SpeechToTextError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Speech recognition failed: {exc}") from exc
        if cancel_event.is_set():
            raise SpeechToTextCancelled("Listening cancelled.")
        if not transcript:
            raise TranscriptionError("I could not understand that audio. Please try again.")
        return transcript
