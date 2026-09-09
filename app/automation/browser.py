from __future__ import annotations

import re
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from urllib.parse import quote_plus, urlsplit


KNOWN_SITES = {
    "youtube": "https://youtube.com",
    "ইউটিউব": "https://youtube.com",
    "google": "https://google.com",
    "গুগল": "https://google.com",
    "github": "https://github.com",
    "linkedin": "https://linkedin.com",
    "facebook": "https://facebook.com",
    "gmail": "https://mail.google.com",
    "জিমেইল": "https://mail.google.com",
}


@dataclass(frozen=True)
class BrowserOutcome:
    success: bool
    message: str
    verified: bool = False


def normalize_url(value: str) -> str | None:
    raw = value.strip()
    if not raw or any(char.isspace() or ord(char) < 32 for char in raw):
        return None
    if raw.casefold() in KNOWN_SITES:
        return KNOWN_SITES[raw.casefold()]
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return None
    if not re.fullmatch(r"[A-Za-z0-9.-]+", parts.hostname) or "." not in parts.hostname:
        return None
    return parts.geturl()


class BrowserAdapter:
    def __init__(self, opener: Callable[[str], bool] = webbrowser.open) -> None:
        self.opener = opener

    def open_website(self, value: str, cancel_event: Event | None = None) -> BrowserOutcome:
        if cancel_event and cancel_event.is_set():
            return BrowserOutcome(False, "Browser action cancelled.")
        url = normalize_url(value)
        if url is None:
            return BrowserOutcome(False, "That is not a safe HTTP(S) website address.")
        try:
            initiated = bool(self.opener(url))
        except OSError as exc:
            return BrowserOutcome(False, f"I could not open the website: {exc}")
        return BrowserOutcome(initiated, f"Opening {url}." if initiated else "The browser could not be opened.", initiated)

    def search(self, query: str, cancel_event: Event | None = None) -> BrowserOutcome:
        text = query.strip()
        if not text:
            return BrowserOutcome(False, "I need search terms before I can search.")
        if cancel_event and cancel_event.is_set():
            return BrowserOutcome(False, "Browser search cancelled.")
        url = f"https://www.google.com/search?q={quote_plus(text)}"
        try:
            initiated = bool(self.opener(url))
        except OSError as exc:
            return BrowserOutcome(False, f"I could not start the browser search: {exc}")
        return BrowserOutcome(initiated, f"Searching the web for {text}." if initiated else "The browser search could not be started.", initiated)