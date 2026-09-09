from __future__ import annotations

import re
from dataclasses import dataclass

from app.automation.application_registry import resolve_application
from app.automation.browser import normalize_url
from app.core.models import ActionRequest


@dataclass(frozen=True)
class IntentRule:
    intent: str
    pattern: re.Pattern[str]
    parameters: tuple[str, ...]


class IntentParser:
    """Deterministic fallback for the allowlisted Phase 5 actions."""
    def __init__(self) -> None:
        self.rules = [
            IntentRule("browser_search", re.compile(r"(?:search|খোঁজো|সার্চ)\s+(?!(?:koro|করো)\b)(?:for\s+)?(?P<query>.+)", re.I), ("query",)),
            IntentRule("browser_search", re.compile(r"(?:google|গুগলে?)\s+(?:e\s+)?(?P<query>.+?)\s+(?:search|সার্চ)\s+(?:koro|করো)", re.I), ("query",)),
            IntentRule("browser_search", re.compile(r"(?P<query>.+?)\s+(?:search|সার্চ)\s+(?:koro|করো)", re.I), ("query",)),
            IntentRule("open_website", re.compile(r"(?P<site>youtube|ইউটিউব|gmail|জিমেইল|google|গুগল|github|linkedin|facebook)\s+(?:open\s+kore\s+dao|খুলে\s+দাও)", re.I), ("site",)),
            IntentRule("open_website", re.compile(r"(?:open|go\s+to|খোলো|খুলে\s+দাও|open\s+koro|open\s+kore\s+dao)\s+(?P<site>youtube|ইউটিউব|gmail|জিমেইল|google|গুগল|github|linkedin|facebook|[\w.-]+\.com)\b", re.I), ("site",)),
            IntentRule("close_application", re.compile(r"(?:close|quit|বন্ধ\s+করো)\s+(?P<application>[\w ]+?)(?:\s+app)?$", re.I), ("application",)),
            IntentRule("open_application", re.compile(r"(?P<application>.+?)\s+(?:open|ওপেন)\s+(?:kore\s+dao|করো|করে\s+দাও)", re.I), ("application",)),
            IntentRule("open_application", re.compile(r"(?:open|launch|খোলো|খুলে\s+দাও|open\s+koro|open\s+kore\s+dao)\s+(?P<application>[\w ]+?)(?:\s+app)?$", re.I), ("application",)),
            IntentRule("excel_type", re.compile(r"(?:next\s+cell(?:-e)?|পরের\s+সেলে).{0,30}?(?:type|লিখো)\s+(?P<value>.+)", re.I), ("value",)),
        ]

    def parse(self, text: str) -> ActionRequest | None:
        normalized = " ".join(text.strip().split())
        if normalized.casefold().replace(",", "") in {"aura stop", "aura cancel", "stop", "cancel", "থামো"}:
            return ActionRequest("cancel", original_text=text)
        for rule in self.rules:
            match = rule.pattern.search(normalized)
            if match:
                params = {key: match.group(key).strip(" .।") for key in rule.parameters}
                if rule.intent == "open_website":
                    url = normalize_url(params["site"])
                    if url is None:
                        continue
                    params = {"url": url}
                elif rule.intent in {"open_application", "close_application"}:
                    application = resolve_application(params["application"])
                    if application is None:
                        continue
                    params = {"application": params["application"]}
                return ActionRequest(rule.intent, params, text)
        return None
