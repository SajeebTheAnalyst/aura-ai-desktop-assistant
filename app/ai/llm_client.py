from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from threading import Event
from typing import Any

from app.ai.prompt import AURA_SYSTEM_PROMPT
from app.automation.application_registry import resolve_application
from app.automation.browser import normalize_url
from app.core.models import ActionRequest, StructuredCommand


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    """Providers return validated command data; they never execute local actions."""
    @abstractmethod
    def understand_command(self, text: str, cancel_event: Event | None = None) -> StructuredCommand | None: ...


class OpenAILLMProvider(LLMProvider):
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_environment(cls) -> "OpenAILLMProvider | None":
        api_key = os.getenv("AURA_LLM_API_KEY", "").strip() or os.getenv("AI_API_KEY", "").strip()
        if not api_key or os.getenv("AURA_LLM_PROVIDER", "openai").strip().casefold() != "openai":
            return None
        from openai import OpenAI
        return cls(OpenAI(api_key=api_key, timeout=20.0, max_retries=0), os.getenv("AURA_LLM_MODEL", "gpt-4o-mini").strip())

    def understand_command(self, text: str, cancel_event: Event | None = None) -> StructuredCommand | None:
        if cancel_event and cancel_event.is_set():
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": AURA_SYSTEM_PROMPT}, {"role": "user", "content": text}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            if cancel_event and cancel_event.is_set():
                return None
            content = response.choices[0].message.content
            if not content:
                raise LLMError("The LLM returned an empty response.")
            return StructuredCommandValidator.from_payload(json.loads(content), text)
        except LLMError:
            raise
        except (json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise LLMError(f"The LLM returned invalid structured data: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"AI command understanding failed: {exc}") from exc


class StructuredCommandValidator:
    ALLOWED_INTENTS = {"open_website", "browser_search", "open_application", "close_application",
                       "type_text", "press_key", "hotkey"}
    LANGUAGES = {"en", "bn", "banglish", "mixed"}

    @classmethod
    def from_payload(cls, payload: Any, original_text: str) -> StructuredCommand:
        if not isinstance(payload, dict):
            raise LLMError("Structured command must be an object.")
        raw_steps = payload.get("steps")
        if raw_steps is None and "intent" in payload:
            raw_steps = [{"intent": payload.get("intent"), "parameters": payload.get("parameters", {})}]
        if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > 5:
            raise LLMError("Structured command must contain one to five steps.")
        steps = tuple(cls._step(step, original_text) for step in raw_steps)
        language = str(payload.get("response_language", "en")).casefold()
        if language not in cls.LANGUAGES:
            language = "en"
        explanation = str(payload.get("explanation", ""))[:240]
        return StructuredCommand(steps, language, explanation)

    @classmethod
    def _step(cls, raw_step: Any, original_text: str) -> ActionRequest:
        if not isinstance(raw_step, dict) or raw_step.get("intent") not in cls.ALLOWED_INTENTS:
            raise LLMError("The command contains an unsupported intent.")
        intent = raw_step["intent"]
        params = raw_step.get("parameters", {})
        if not isinstance(params, dict):
            raise LLMError("Action parameters must be an object.")
        if intent == "browser_search":
            query = str(params.get("query", "")).strip()
            if not query:
                raise LLMError("browser_search requires a query.")
            params = {"query": query}
        elif intent == "open_website":
            url = str(params.get("url", "")).strip()
            normalized = normalize_url(url)
            if normalized is None:
                raise LLMError("open_website requires a safe HTTP(S) URL.")
            params = {"url": normalized}
        elif intent in {"open_application", "close_application"}:
            application = str(params.get("application", "")).casefold().strip()
            spec = resolve_application(application)
            if spec is None:
                raise LLMError("The application is not allowlisted.")
            params = {"application": spec.name}
        elif intent == "type_text":
            text = str(params.get("text", ""))
            if not text or len(text) > 2000:
                raise LLMError("type_text requires one to two thousand characters.")
            params = {"text": text}
        elif intent == "press_key":
            key = str(params.get("key", "")).strip().casefold()
            if not key or len(key) > 12 or any(char in key for char in "\r\n;|"):
                raise LLMError("press_key requires one safe key name.")
            params = {"key": key}
        else:
            keys = params.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
                raise LLMError("hotkey requires one to four keys.")
            normalized_keys = [str(key).strip().casefold() for key in keys]
            if any(not key or len(key) > 12 or any(char in key for char in "\r\n;|") for key in normalized_keys):
                raise LLMError("hotkey contains an unsafe key name.")
            params = {"keys": normalized_keys}
        return ActionRequest(intent, params, original_text)
