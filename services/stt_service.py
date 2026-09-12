"""Reliable default-device audio capture and English/Bangla transcription."""
from __future__ import annotations

import queue
import time
from threading import Event
from typing import Any, Callable

import numpy as np
import sounddevice as sd
import speech_recognition as sr


CHUNK_SECONDS = 0.05
CALIBRATE_SECONDS = 0.6
INITIAL_SILENCE_SECONDS = 5.0
MIN_CAPTURE_SECONDS = 2.0
MIN_SPEECH_SECONDS = 0.35
TRAILING_SILENCE_SECONDS = 1.35
MAX_UTTERANCE_SECONDS = 20.0
ENERGY_HEADROOM = 1.8
ENERGY_FLOOR = 90.0


def _frame_energy(raw: bytes) -> float:
    if not raw:
        return 0.0
    return float(np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32)).mean())


class STTService:
    SAMPLE_RATE = 16_000

    def __init__(self) -> None:
        self._last_sample_rate = self.SAMPLE_RATE

    @staticmethod
    def available_input_devices() -> list[tuple[int, str, int, float]]:
        devices = sd.query_devices()
        return [
            (index, str(info["name"]), int(info["max_input_channels"]), float(info["default_samplerate"]))
            for index, info in enumerate(devices)
            if int(info["max_input_channels"]) > 0
        ]

    @classmethod
    def _select_input_device(cls) -> tuple[int, str, int]:
        inputs = cls.available_input_devices()
        if not inputs:
            raise RuntimeError("No active recording device is available.")
        default_input = sd.default.device[0]
        selected = next((item for item in inputs if item[0] == default_input), inputs[0])
        index, name, _channels, default_rate = selected
        sample_rate = cls.SAMPLE_RATE
        try:
            sd.check_input_settings(device=index, channels=1, samplerate=sample_rate, dtype="int16")
        except Exception:
            sample_rate = int(default_rate)
            sd.check_input_settings(device=index, channels=1, samplerate=sample_rate, dtype="int16")
        print(f"[STT] Available input devices: {[(i, n) for i, n, _, _ in inputs]}")
        print(f"[STT] Capturing audio from device: {name} (index={index}, sample_rate={sample_rate})")
        return index, name, sample_rate

    @classmethod
    def microphone_available(cls) -> tuple[bool, str]:
        try:
            _index, name, _rate = cls._select_input_device()
            return True, name
        except Exception as exc:
            return False, str(exc)

    def listen_once(self, cancel_event: Event | None = None) -> str:
        return self.transcribe(self.listen_segmented(cancel_event))

    def listen_segmented(
        self,
        cancel_event: Event | None = None,
        on_state: Callable[[str], None] | None = None,
    ) -> bytes:
        """Capture a full utterance; never finalize within MIN_CAPTURE_SECONDS."""
        device, _name, sample_rate = self._select_input_device()
        self._last_sample_rate = sample_rate
        frames_per_chunk = max(256, int(sample_rate * CHUNK_SECONDS))
        audio_queue: queue.Queue[bytes] = queue.Queue()
        status_messages: list[str] = []

        def callback(indata: np.ndarray, _frames: int, _time: Any, status: Any) -> None:
            if status:
                status_messages.append(str(status))
            # Always retain frames despite overflow/underflow notifications.
            audio_queue.put(indata.copy().tobytes())

        def get_frame() -> bytes:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Listening cancelled.")
                try:
                    return audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

        if on_state:
            on_state("LISTENING")
        calibrate_levels: list[float] = []
        captured: list[bytes] = []
        speech_started = False
        speech_started_at = 0.0
        trailing_silence = 0.0
        speech_seconds = 0.0
        level_sum = 0.0
        level_peak = 0.0
        frame_count = 0
        started_at = time.monotonic()

        try:
            with sd.InputStream(
                device=device,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=frames_per_chunk,
                callback=callback,
            ):
                calibration_end = time.monotonic() + CALIBRATE_SECONDS
                while time.monotonic() < calibration_end:
                    raw = get_frame()
                    calibrate_levels.append(_frame_energy(raw))
                ambient = max(ENERGY_FLOOR, float(np.median(calibrate_levels)) if calibrate_levels else ENERGY_FLOOR)
                threshold = max(ENERGY_FLOOR, ambient * ENERGY_HEADROOM)
                print(f"[STT] Ambient energy={ambient:.1f}; speech threshold={threshold:.1f}")

                while True:
                    raw = get_frame()
                    now = time.monotonic()
                    elapsed = now - started_at
                    level = _frame_energy(raw)
                    frame_count += 1
                    level_sum += level
                    level_peak = max(level_peak, level)
                    if frame_count % 20 == 0:
                        print(f"[STT] Audio frame count={frame_count}; level={level:.1f}; peak={level_peak:.1f}")
                    if status_messages:
                        print(f"[STT] Stream status: {status_messages.pop(0)}")

                    if not speech_started:
                        if elapsed >= INITIAL_SILENCE_SECONDS:
                            average = level_sum / max(1, frame_count)
                            print(f"[STT] No speech detected; frames={frame_count}; avg={average:.1f}; peak={level_peak:.1f}")
                            raise RuntimeError("No speech detected. Please try again.")
                        if level >= threshold:
                            speech_started = True
                            speech_started_at = now
                            captured.append(raw)
                            speech_seconds += CHUNK_SECONDS
                        continue

                    captured.append(raw)
                    recording_seconds = now - speech_started_at
                    if level >= threshold:
                        speech_seconds += CHUNK_SECONDS
                        trailing_silence = 0.0
                    else:
                        trailing_silence += CHUNK_SECONDS
                    # Minimum window avoids clipping a sentence on an early pause.
                    if recording_seconds >= MIN_CAPTURE_SECONDS and speech_seconds >= MIN_SPEECH_SECONDS and trailing_silence >= TRAILING_SILENCE_SECONDS:
                        break
                    if recording_seconds >= MAX_UTTERANCE_SECONDS:
                        break
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Microphone capture failed: {exc}") from exc

        pcm = b"".join(captured)
        duration = len(pcm) / (2 * sample_rate)
        average = level_sum / max(1, frame_count)
        print(f"[STT] Capture complete; frames={frame_count}; duration={duration:.2f}s; avg={average:.1f}; peak={level_peak:.1f}")
        if duration < MIN_CAPTURE_SECONDS or speech_seconds < MIN_SPEECH_SECONDS:
            print(f"[STT] No speech detected; usable duration={duration:.2f}s; speech={speech_seconds:.2f}s")
            raise RuntimeError("No speech detected. Please try again.")
        return pcm

    def transcribe(self, pcm: bytes) -> str:
        if not pcm:
            raise RuntimeError("No speech detected. Please try again.")
        audio = sr.AudioData(pcm, self._last_sample_rate, 2)
        for language in ("en-US", "bn-BD"):
            try:
                text = sr.Recognizer().recognize_google(audio, language=language)
                if text and text.strip():
                    return text.strip()
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                raise RuntimeError(f"Speech recognition service unavailable: {exc}") from exc
        raise RuntimeError("No speech detected. Please try again.")