from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from app.core.assistant import Assistant
from app.core.models import TaskStatus
from app.ui.tray import create_tray
from app.voice.faster_whisper_provider import FasterWhisperProvider
from app.voice.worker import VoiceCaptureWorker


class _TtsSignals(QObject):
    status = Signal(str)
    error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, assistant: Assistant) -> None:
        super().__init__()
        self.assistant = assistant
        self.voice_provider = FasterWhisperProvider()
        self.voice_thread: QThread | None = None
        self.voice_worker: VoiceCaptureWorker | None = None
        self.tts_signals = _TtsSignals()
        self.tts_signals.status.connect(self._on_tts_status)
        self.tts_signals.error.connect(self._on_tts_error)
        self.assistant.tts.on_status = self.tts_signals.status.emit
        self.assistant.tts.on_error = self.tts_signals.error.emit
        self.setWindowTitle("AURA - AI Desktop Assistant")
        self.resize(800, 580)
        self._build()
        self.tray = create_tray(self, self.cancel_task)
        QShortcut(QKeySequence("Ctrl+Shift+Q"), self, self.cancel_task)

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("AURA"); title.setObjectName("title")
        subtitle = QLabel("Multilingual AI Desktop Assistant - Safe action mode")
        self.status = QLabel("Ready - type a request or start listening.")
        self.tts_toggle = QPushButton("TTS: ON" if self.assistant.tts.enabled else "TTS: OFF")
        self.tts_toggle.clicked.connect(self.toggle_tts)
        self.command = QTextEdit(); self.command.setPlaceholderText("Try: Chrome open kore Python automation search koro."); self.command.setFixedHeight(100)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        buttons = QHBoxLayout()
        run = QPushButton("Run request"); run.clicked.connect(self.run_request)
        self.listen_button = QPushButton("Listen"); self.listen_button.clicked.connect(self.start_listening)
        pause = QPushButton("Pause"); pause.clicked.connect(self.pause)
        stop = QPushButton("Stop (Ctrl+Shift+Q)"); stop.clicked.connect(self.cancel_task)
        buttons.addWidget(run); buttons.addWidget(self.listen_button); buttons.addWidget(pause); buttons.addWidget(stop); buttons.addWidget(self.tts_toggle)
        layout.addWidget(title); layout.addWidget(subtitle); layout.addWidget(self.status); layout.addWidget(self.command)
        layout.addLayout(buttons); layout.addWidget(QLabel("Activity")); layout.addWidget(self.log)
        self.setCentralWidget(root)
        self.setStyleSheet("QWidget { background:#101521; color:#E9EDF5; font-size:14px; } #title { font-size:32px; font-weight:700; color:#8AB4FF; } QTextEdit { background:#171E2E; border:1px solid #303B52; border-radius:8px; padding:8px; } QPushButton { background:#2869D8; border:0; border-radius:7px; padding:9px 14px; font-weight:600; } QPushButton:hover { background:#3D7BE0; }")

    def run_request(self) -> None:
        self._submit_text(self.command.toPlainText().strip(), from_voice=False)

    def _submit_text(self, text: str, from_voice: bool) -> None:
        if not text:
            return
        result = self.assistant.handle_voice_transcript(text) if from_voice else self.assistant.handle(text)
        if result.status is TaskStatus.NEEDS_CONFIRMATION:
            answer = QMessageBox.question(self, "Confirm action", result.message, QMessageBox.Yes | QMessageBox.No)
            if answer is QMessageBox.Yes:
                result = self.assistant.handle(text, confirmed=True, reset_cancellation=not from_voice)
            else:
                self.status.setText("Action not confirmed.")
                return
        self.status.setText(result.message)
        self.log.append(f"[{result.status.value}] {text}\n{result.message}\n")

    def start_listening(self) -> None:
        if not self.assistant.start_listening():
            self.status.setText("Listening is paused or already active.")
            return
        available, detail = self.voice_provider.microphone_available()
        if not available:
            self.assistant.finish_listening()
            message = f"No usable microphone: {detail}"
            self.assistant.record_voice_event("microphone_unavailable", message)
            self.status.setText(message)
            self.log.append(f"[voice error] {message}\n")
            return
        self.listen_button.setEnabled(False)
        self.status.setText(f"Listening with {detail}…")
        self.voice_thread = QThread(self)
        self.voice_worker = VoiceCaptureWorker(self.voice_provider, self.assistant.state.cancel_event)
        self.voice_worker.moveToThread(self.voice_thread)
        self.voice_thread.started.connect(self.voice_worker.run)
        self.voice_worker.status_changed.connect(self.status.setText)
        self.voice_worker.transcript_ready.connect(self._on_transcript)
        self.voice_worker.failed.connect(self._on_voice_error)
        self.voice_worker.cancelled.connect(self._on_voice_cancelled)
        self.voice_worker.finished.connect(self.assistant.finish_listening)
        self.voice_worker.finished.connect(self.voice_thread.quit)
        self.voice_worker.finished.connect(self.voice_worker.deleteLater)
        self.voice_thread.finished.connect(self._voice_finished)
        self.voice_thread.finished.connect(self.voice_thread.deleteLater)
        self.voice_thread.start()

    def _on_transcript(self, transcript: str) -> None:
        self.command.setPlainText(transcript)
        self.status.setText(f"Recognized: {transcript}")
        self._submit_text(transcript, from_voice=True)

    def _on_voice_error(self, message: str) -> None:
        self.assistant.record_voice_event("failed", message)
        self.status.setText(message)
        self.log.append(f"[voice error] {message}\n")

    def _on_voice_cancelled(self) -> None:
        self.assistant.record_voice_event("cancelled", "Listening cancelled.")
        self.status.setText("Listening cancelled.")
        self.log.append("[voice cancelled] Listening cancelled.\n")

    def _voice_finished(self) -> None:
        self.listen_button.setEnabled(not self.assistant.state.paused)
        self.voice_worker = None
        self.voice_thread = None

    def pause(self) -> None:
        self.assistant.state.paused = not self.assistant.state.paused
        self.listen_button.setEnabled(not self.assistant.state.paused and not self.assistant.state.listening)
        self.status.setText("Listening paused." if self.assistant.state.paused else "Listening resumed.")

    def cancel_task(self) -> None:
        self.assistant.cancel()
        self.status.setText("Stop requested. AURA will cancel its current task.")

    def toggle_tts(self) -> None:
        self.assistant.tts.set_enabled(not self.assistant.tts.enabled)
        self.tts_toggle.setText("TTS: ON" if self.assistant.tts.enabled else "TTS: OFF")

    def _on_tts_status(self, status: str) -> None:
        self.status.setText(status)

    def _on_tts_error(self, message: str) -> None:
        self.assistant.logger.record_tts_event("error", message)
        self.log.append(f"[tts error] {message}\n")