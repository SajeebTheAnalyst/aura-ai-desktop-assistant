from __future__ import annotations


class SpeechToTextError(RuntimeError):
    """Base error for microphone capture and transcription failures."""


class MicrophoneUnavailableError(SpeechToTextError):
    """Raised when no usable input device can be opened."""


class TranscriptionError(SpeechToTextError):
    """Raised when audio cannot be converted into a transcript."""


class SpeechToTextCancelled(SpeechToTextError):
    """Raised when the user stops an active listening session."""
