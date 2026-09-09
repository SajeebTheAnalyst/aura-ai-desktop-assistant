from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.models import ActionRequest, ActionResult


class ActivityLogger:
    """Append-only local audit log; never includes environment variables/secrets."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _write(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, request: ActionRequest, result: ActionResult, confirmed: bool = False) -> None:
        self._write({"command": request.original_text, "intent": request.intent,
                     "parameters": request.parameters, "result": result.status.value,
                     "message": result.message, "confirmed": confirmed})

    def record_voice_event(self, event: str, message: str) -> None:
        """Logs voice lifecycle/errors without retaining audio or partial speech."""
        self._write({"command": None, "intent": "voice_capture", "parameters": {"event": event},
                     "result": event, "message": message, "confirmed": False})

    def record_tts_event(self, event: str, message: str) -> None:
        self._write({"command": None, "intent": "text_to_speech", "parameters": {"event": event},
                     "result": event, "message": message, "confirmed": False})

    def record_ai_event(self, event: str, message: str) -> None:
        self._write({"command": None, "intent": "llm_understanding", "parameters": {"event": event},
                     "result": event, "message": message, "confirmed": False})