from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Event


class SpeechToTextProvider(ABC):
    @abstractmethod
    def listen_once(self, cancel_event: Event) -> str:
        """Capture one utterance and return its transcript."""