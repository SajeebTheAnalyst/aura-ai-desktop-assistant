from __future__ import annotations

from dataclasses import dataclass
from threading import Event


@dataclass
class AssistantState:
    listening: bool = False
    paused: bool = False

    def __post_init__(self) -> None:
        self.cancel_event = Event()

    def start_listening(self) -> bool:
        if self.paused or self.listening:
            return False
        self.cancel_event.clear()
        self.listening = True
        return True

    def finish_listening(self) -> None:
        self.listening = False

    def cancel(self) -> None:
        self.cancel_event.set()

    def reset_task(self) -> None:
        self.cancel_event.clear()