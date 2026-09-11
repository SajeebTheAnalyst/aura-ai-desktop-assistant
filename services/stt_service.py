"""Bounded, PyAudio-free microphone capture plus English/Bangla recognition using sounddevice."""
from __future__ import annotations

import queue
from threading import Event
from typing import Any
import numpy as np
import speech_recognition as sr
import sounddevice as sd


class SoundDeviceStream:
    def __init__(self, device: str | int | None, sample_rate: int, cancel_event: Event | None = None) -> None:
        self.queue: queue.Queue[bytes] = queue.Queue()
        self.buffer = b""
        self.cancel_event = cancel_event
        self.stream = sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            callback=self._callback
        )
        self.stream.start()

    def _callback(self, indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
        self.queue.put(indata.tobytes())

    def read(self, chunk_size: int) -> bytes:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return b""
        needed_bytes = chunk_size * 2
        while len(self.buffer) < needed_bytes:
            if self.cancel_event is not None and self.cancel_event.is_set():
                return b""
            try:
                chunk = self.queue.get(timeout=0.05)
                self.buffer += chunk
            except queue.Empty:
                break
        result = self.buffer[:needed_bytes]
        self.buffer = self.buffer[needed_bytes:]
        return result

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


class SoundDeviceMicrophone(sr.AudioSource):
    def __init__(self, device: str | int | None = None, sample_rate: int = 16000, chunk_size: int = 1024, cancel_event: Event | None = None) -> None:
        self.device = device
        self.SAMPLE_RATE = sample_rate
        self.CHUNK = chunk_size
        self.SAMPLE_WIDTH = 2  # 16-bit mono
        self.cancel_event = cancel_event
        self.stream: SoundDeviceStream | None = None

    def __enter__(self) -> SoundDeviceMicrophone:
        if self.stream is not None:
            raise RuntimeError("Already entered")
        self.stream = SoundDeviceStream(self.device, self.SAMPLE_RATE, self.cancel_event)
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class STTService:
    SAMPLE_RATE = 16_000

    @staticmethod
    def microphone_available() -> tuple[bool, str]:
        try:
            device = sd.query_devices(kind="input")
            return True, str(device["name"])
        except Exception as exc:
            return False, str(exc)

    def listen_once(self, cancel_event: Event | None = None) -> str:
        available, detail = self.microphone_available()
        if not available:
            raise RuntimeError(f"Microphone unavailable: {detail}")

        recognizer = sr.Recognizer()
        # Trigger the instant the user stops talking (0.8s of silence) instead
        # of waiting the default ~5s effective silence budget.
        recognizer.pause_threshold = 0.8
        recognizer.phrase_time_limit = 6
        with SoundDeviceMicrophone(sample_rate=self.SAMPLE_RATE, cancel_event=cancel_event) as source:
            try:
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=6)
            except sr.WaitTimeoutError as exc:
                raise RuntimeError("No speech detected within 4 seconds.") from exc

        for language in ("en-US", "bn-BD"):
            try:
                return recognizer.recognize_google(audio, language=language)
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                raise RuntimeError(f"Speech recognition service unavailable: {exc}") from exc
        raise RuntimeError("I could not understand the audio in English or Bangla.")
