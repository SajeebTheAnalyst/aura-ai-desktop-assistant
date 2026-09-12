"""Google GenAI intent planner. It plans actions but cannot execute them."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from config import (
    GEMINI_API_KEY,
    GEMINI_FALLBACK_MODEL,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
)
from core.context import SYSTEM_PROMPT


class Intent(StrEnum):
    CHAT = "CHAT"
    OPEN_APP = "OPEN_APP"
    SYSTEM_ACTION = "SYSTEM_ACTION"
    WEB_SEARCH = "WEB_SEARCH"
    PLAY_MUSIC = "PLAY_MUSIC"


@dataclass(frozen=True)
class CommandPlan:
    intent: Intent
    target: str = ""
    response: str = ""

    @classmethod
    def chat(cls, response: str) -> "CommandPlan":
        return cls(Intent.CHAT, "", response)


class StructuredResponseError(ValueError):
    """The model did not return the command JSON contract."""


class LLMService:
    COOLDOWN_SECONDS = 60.0  # skip a model that just returned 429 quota

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL) -> None:
        self.api_key = api_key
        self.models = tuple(dict.fromkeys((model, GEMINI_FALLBACK_MODEL)))
        self._client = None
        self._cooldown: dict[str, float] = {}

    def warmup(self) -> None:
        """Import the SDK and build the client in the background so the first
        real request does not pay the import/init latency (~2 s)."""
        import threading

        threading.Thread(target=self._client_or_none, name="aura-llm-warmup", daemon=True).start()

    def _client_or_none(self):
        if not self.api_key:
            return None
        if self._client is None:
            from google import genai
            from google.genai import types

            # Cap each HTTP attempt so a stalled/quota-limited API can never
            # hang the voice loop for tens of seconds (the old 10-15s stalls).
            # 10 s is the API's minimum allowed manual deadline; a lower value
            # is rejected with 400 INVALID_ARGUMENT. attempts=1 disables the
            # SDK's built-in exponential retries (429s would otherwise stall
            # the voice loop ~15 s) - plan() owns the fallback strategy.
            http_options = types.HttpOptions(
                timeout=10_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            )
            try:
                self._client = genai.Client(api_key=self.api_key, http_options=http_options)
            except TypeError:  # older SDK without http_options
                self._client = genai.Client(api_key=self.api_key)
        return self._client

    def plan(self, user_prompt: str) -> CommandPlan:
        # ---- local fast-path (~0 ms) ----
        # Canonical short imperative commands ("open power bi", "open youtube",
        # "go to settings") resolve with the offline classifier without any
        # network round trip - this is what keeps the voice loop under the
        # 2-second end-to-end latency budget. Questions and complex text are
        # delegated to the language model below.
        text = (user_prompt or "").strip()
        profile = self._profile_reply(text)
        if profile is not None:
            return profile
        local = self._classify_locally(text)
        is_simple_command = (
            local.intent is not Intent.CHAT
            and len(text.split()) <= 7
            and not any(q in text.lower() for q in self._QUESTION_WORDS)
        )
        if is_simple_command:
            return local

        client = self._client_or_none()
        if client is None:
            # No API key configured: fall back to the offline classifier so the
            # core commands still work and the loop always has something to say.
            return local
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "intent": {"type": "STRING"},
                        "target": {"type": "STRING"},
                        "response": {"type": "STRING"},
                    },
                    "required": ["intent", "target", "response"],
                },
            )
            for model in self.models:
                if time.monotonic() < self._cooldown.get(model, 0.0):
                    continue  # circuit breaker: model just hit its quota limit
                try:
                    # Single-shot JSON generation: no chat-session handshake,
                    # no automatic function-calling round trips.
                    response = client.models.generate_content(
                        model=model, contents=text, config=config
                    )
                    return self._parse(response.text or "")
                except Exception as exc:
                    if getattr(exc, "code", None) == 429:
                        self._cooldown[model] = time.monotonic() + self.COOLDOWN_SECONDS
                    continue
        except Exception:
            pass
        # Soft fail: speak a local classification (or plain CHAT) so the loop
        # never dies on a parse/generation error.
        return local

    @staticmethod
    def _clean_json(raw_text: str) -> str:
        text = raw_text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        return text

    @classmethod
    def _parse(cls, raw_text: str) -> CommandPlan:
        try:
            data: dict[str, Any] = json.loads(cls._clean_json(raw_text))
            if not isinstance(data, dict):
                raise StructuredResponseError("Response is not a JSON object.")
            response = data.get("response")
            if not isinstance(response, str) or not response.strip():
                raise StructuredResponseError("Response text is missing.")
            intent = Intent(str(data.get("intent", "CHAT")).strip().upper())
            target = str(data.get("target", "") or "").strip()
            return CommandPlan(intent, target, response.strip())
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise StructuredResponseError("Invalid structured Gemini response.") from exc
# ---- offline fallback classifier (used when the API is down / rate-limited) ----
    _SYSTEM_ACTIONS: dict[str, tuple[str, ...]] = {
        "shutdown": ("shutdown", "shut down", "power off", "turn off the pc", "turn off the computer"),
        "restart": ("restart", "reboot"),
        "sleep": ("sleep", "suspend"),
        "lock": ("lock the pc", "lock the screen", "lock screen"),
        "settings": ("settings", "control panel"),
    }
    _SITES: tuple[tuple[str, str], ...] = (
        ("youtube", "youtube"),
        ("google", "google"),
        ("gmail", "gmail"),
        ("github", "github"),
    )
    _DISPLAY_NAMES: dict[str, str] = {
        "youtube": "YouTube",
        "gmail": "Gmail",
        "github": "GitHub",
        "power bi": "Power BI",
        "powerpoint": "PowerPoint",
        "power point": "PowerPoint",
        "vscode": "VS Code",
        "visual studio code": "VS Code",
        "file explorer": "File Explorer",
        "explorer": "File Explorer",
        "calc": "Calculator",
        "cmd": "Command Prompt",
    }
    _APPS: tuple[tuple[str, str], ...] = (
        ("power bi", "powerbi"),
        ("powerpoint", "powerpoint"),
        ("chrome", "chrome"),
        ("notepad", "notepad"),
        ("excel", "excel"),
        ("word", "word"),
        ("calculator", "calculator"),
        ("calc", "calculator"),
        ("explorer", "explorer"),
        ("file explorer", "explorer"),
        ("vscode", "vscode"),
        ("visual studio code", "vscode"),
        ("spotify", "spotify"),
        ("paint", "paint"),
        ("whatsapp", "whatsapp"),
        ("discord", "discord"),
        ("pycharm", "pycharm"),
        ("settings", "settings"),
    )
    _ACTION_VERBS = ("open", "launch", "start", "run", "play", "go")
    _QUESTION_WORDS = ("what", "who", "why", "how", "when", "can you", "tell me", "about", "please")

    @classmethod
    def _profile_reply(cls, text: str) -> CommandPlan | None:
        """Instant, factual replies for frequent Sajeeb/AURA profile questions."""
        query = (text or "").casefold()
        if any(phrase in query for phrase in ("who are you", "what are you", "tumi ke", "tumi ki")):
            return CommandPlan.chat("I am AURA, your assistant for analytics, automation, and Windows tasks.")
        if any(phrase in query for phrase in ("my name", "who am i", "amar nam", "ami ke")):
            return CommandPlan.chat("You are Sajeeb, a data analyst and AI automation specialist.")
        if any(phrase in query for phrase in ("my skill", "my skills", "amar skill", "amar skills")):
            return CommandPlan.chat("Your core skills are Python, SQL, Power BI, Excel, and AI automation.")
        if any(phrase in query for phrase in ("about me", "what do you know about me", "amar bepare", "amar somporke", "my portfolio")):
            return CommandPlan.chat("You build analytics dashboards, AI web apps, and workflow automations for your portfolio.")
        return None

    @classmethod
    def _classify_locally(cls, text: str) -> CommandPlan:
        """Deterministic offline intent plan so core commands survive API outages."""
        raw = text or ""
        t = raw.strip().lower()
        if not t:
            return CommandPlan.chat(raw)
        is_question = any(q in t for q in cls._QUESTION_WORDS)
        has_verb = any(v in t for v in cls._ACTION_VERBS)

        # 0) Music requests: "play <song> on youtube", "play shape of you".
        if t.startswith("play ") and not is_question:
            song = t[len("play "):].strip()
            song = re.sub(r"\s+on\s+(?:youtube|yt|the\s+internet|music)\b.*$", "", song).strip()
            song = re.sub(r"^(?:some|the|a|an)\s+", "", song).strip()
            app_keys = {key for _, key in cls._APPS}
            if song and "youtube" not in song and song not in app_keys:
                return CommandPlan(Intent.PLAY_MUSIC, song, f"Playing {song.title()}.")

        # 1) System actions (shutdown/sleep/etc.) - only when imperative.
        if not is_question:
            for action, keys in cls._SYSTEM_ACTIONS.items():
                if any(k in t for k in keys):
                    replies = {
                        "shutdown": "Shutting down your PC in five seconds.",
                        "restart": "Restarting your PC in five seconds.",
                        "sleep": "Putting your PC to sleep.",
                        "lock": "Locking your PC.",
                        "settings": "Opening Windows settings.",
                    }
                    return CommandPlan(Intent.SYSTEM_ACTION, action, replies[action])

        # 2) Websites / web search.
        for site, key in cls._SITES:
            if site in t and (has_verb or not is_question):
                display = cls._DISPLAY_NAMES.get(key, key.capitalize())
                return CommandPlan(Intent.WEB_SEARCH, key, f"Opening {display}.")

        # 3) Apps - only when there is an explicit action verb.
        if has_verb:
            for app, key in cls._APPS:
                if app in t:
                    display = cls._DISPLAY_NAMES.get(app, app.title())
                    return CommandPlan(Intent.OPEN_APP, key, f"Opening {display}.")

        # 4) Generic search queries.
        if "search" in t or "look up" in t:
            query = re.sub(r"^(please\s+)?(search|look up|google)\s*", "", t).strip(" for: ")
            if query:
                return CommandPlan(Intent.WEB_SEARCH, query, f"Searching for {query}.")

        return CommandPlan.chat(raw)