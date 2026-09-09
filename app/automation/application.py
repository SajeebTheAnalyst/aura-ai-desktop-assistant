from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any

import psutil

from app.automation.application_registry import resolve_application


@dataclass(frozen=True)
class AutomationOutcome:
    success: bool
    message: str
    verified: bool = False


class ApplicationAdapter:
    def __init__(self, launcher: Callable[..., Any] = subprocess.Popen) -> None:
        self.launcher = launcher

    def open(self, name: str, cancel_event: Event | None = None) -> AutomationOutcome:
        if cancel_event and cancel_event.is_set():
            return AutomationOutcome(False, "Application launch cancelled.")
        spec = resolve_application(name)
        if spec is None:
            return AutomationOutcome(False, f"{name or 'That application'} is not allowlisted.")
        if shutil.which(spec.command[0]) is None:
            return AutomationOutcome(False, f"{spec.name.title()} is not installed or is unavailable.")
        try:
            process = self.launcher(list(spec.command))
        except OSError as exc:
            return AutomationOutcome(False, f"I could not open {spec.name}: {exc}")
        if cancel_event and cancel_event.is_set():
            return AutomationOutcome(False, "Application launch cancelled.")
        verified = process.poll() is None
        message = f"Opening {spec.name.title()}." if verified else f"Launch initiated for {spec.name.title()}, but it could not be verified."
        return AutomationOutcome(True, message, verified)

    def close(self, name: str, cancel_event: Event | None = None) -> AutomationOutcome:
        if cancel_event and cancel_event.is_set():
            return AutomationOutcome(False, "Application close cancelled.")
        spec = resolve_application(name)
        if spec is None:
            return AutomationOutcome(False, f"{name or 'That application'} is not allowlisted.")
        found = []
        for process in psutil.process_iter(("name",)):
            if cancel_event and cancel_event.is_set():
                return AutomationOutcome(False, "Application close cancelled.")
            if (process.info.get("name") or "").casefold() in {item.casefold() for item in spec.process_names}:
                found.append(process)
        if not found:
            return AutomationOutcome(False, f"{spec.name.title()} is not currently running.")
        for process in found:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                return AutomationOutcome(False, f"I could not close {spec.name}: {exc}")
        return AutomationOutcome(True, f"Close requested for {spec.name.title()}.", True)