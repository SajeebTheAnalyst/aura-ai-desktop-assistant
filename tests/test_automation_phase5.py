import unittest
from threading import Event
from unittest.mock import patch

from app.automation.application import ApplicationAdapter
from app.automation.application_registry import resolve_application
from app.automation.browser import BrowserAdapter, normalize_url
from app.automation.keyboard import KeyboardAdapter
from app.ai.intent_parser import IntentParser
from app.ai.llm_client import LLMError, StructuredCommandValidator
from app.core.actions import SafeActions
from app.core.models import ActionRequest, TaskStatus


class FakeProcess:
    def __init__(self, running: bool = True) -> None:
        self.running = running

    def poll(self):
        return None if self.running else 0


class FakeKeyboard(KeyboardAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def type_text(self, text, cancel_event=None):
        self.calls.append(("type_text", text))

    def press_key(self, key, cancel_event=None):
        self.calls.append(("press_key", key))

    def hotkey(self, keys, cancel_event=None):
        self.calls.append(("hotkey", keys))


class AutomationPhase5Tests(unittest.TestCase):
    def test_deterministic_parser_handles_requested_language_variants(self) -> None:
        parser = IntentParser()
        self.assertEqual(parser.parse("নোটপ্যাড ওপেন করো").parameters["application"], "নোটপ্যাড")
        self.assertEqual(parser.parse("ইউটিউব খুলে দাও").parameters["url"], "https://youtube.com")
        self.assertEqual(parser.parse("Chrome open kore dao").parameters["application"], "Chrome")
        self.assertEqual(parser.parse("Google e Python automation search koro").parameters["query"], "Python automation")

    def test_llm_schema_rejects_unimplemented_actions(self) -> None:
        with self.assertRaises(LLMError):
            StructuredCommandValidator.from_payload({"intent": "execute_powershell", "parameters": {}}, "run it")

    def test_application_registry_rejects_arbitrary_executable(self) -> None:
        self.assertIsNotNone(resolve_application("Notepad app"))
        self.assertIsNone(resolve_application(r"C:\\something\\unknown.exe"))

    def test_application_adapter_uses_allowlisted_command_only(self) -> None:
        launched: list[list[str]] = []

        def launcher(command):
            launched.append(command)
            return FakeProcess()

        with patch("app.automation.application.shutil.which", return_value="C:\\Windows\\notepad.exe"):
            outcome = ApplicationAdapter(launcher).open("notepad")
        self.assertTrue(outcome.success)
        self.assertTrue(outcome.verified)
        self.assertEqual(launched, [["notepad.exe"]])

    def test_browser_url_validation_rejects_unsafe_schemes_and_injection(self) -> None:
        self.assertEqual(normalize_url("youtube.com"), "https://youtube.com")
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("youtube.com && shutdown"))
        self.assertIsNone(normalize_url("file:///secret.txt"))

    def test_browser_adapter_encodes_search_data(self) -> None:
        opened: list[str] = []
        outcome = BrowserAdapter(lambda url: opened.append(url) or True).search("Python desktop automation")
        self.assertTrue(outcome.success)
        self.assertEqual(opened, ["https://www.google.com/search?q=Python+desktop+automation"])

    def test_safe_actions_route_to_browser_and_keyboard_adapters(self) -> None:
        opened: list[str] = []
        keyboard = FakeKeyboard()
        actions = SafeActions(browser=BrowserAdapter(lambda url: opened.append(url) or True), keyboard=keyboard)
        website = actions.open_website(ActionRequest("open_website", {"url": "github.com"}))
        typing = actions.type_text(ActionRequest("type_text", {"text": "Hello"}))
        hotkey = actions.hotkey(ActionRequest("hotkey", {"keys": ["ctrl", "l"]}))
        self.assertEqual(website.status, TaskStatus.COMPLETED)
        self.assertEqual(typing.status, TaskStatus.COMPLETED)
        self.assertEqual(hotkey.status, TaskStatus.COMPLETED)
        self.assertEqual(opened, ["https://github.com"])
        self.assertEqual(keyboard.calls, [("type_text", "Hello"), ("hotkey", ("ctrl", "l"))])

    def test_cancelled_action_does_not_call_adapter(self) -> None:
        event = Event()
        event.set()
        keyboard = FakeKeyboard()
        result = SafeActions(cancel_event=event, keyboard=keyboard).type_text(ActionRequest("type_text", {"text": "blocked"}))
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(keyboard.calls, [])

    def test_cancelled_multi_step_stops_remaining_steps(self) -> None:
        event = Event()
        keyboard = FakeKeyboard()

        class CancellingKeyboard(FakeKeyboard):
            def type_text(self, text, cancel_event=None):
                super().type_text(text, cancel_event)
                event.set()

        actions = SafeActions(cancel_event=event, keyboard=CancellingKeyboard())
        first = actions.type_text(ActionRequest("type_text", {"text": "first"}))
        second = actions.press_key(ActionRequest("press_key", {"key": "enter"}))
        self.assertEqual(first.status, TaskStatus.COMPLETED)
        self.assertEqual(second.status, TaskStatus.CANCELLED)


if __name__ == "__main__":
    unittest.main()