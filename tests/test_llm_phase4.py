import tempfile
import unittest
from pathlib import Path
from threading import Event

from app.ai.llm_client import LLMError, LLMProvider, OpenAILLMProvider, StructuredCommandValidator
from app.core.assistant import Assistant
from app.core.logging import ActivityLogger
from app.core.models import ActionResult, StructuredCommand, TaskStatus
from app.voice.text_to_speech import AsyncTextToSpeech, TextToSpeechProvider


class SilentTTS(TextToSpeechProvider):
    def speak(self, text: str) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_available(self) -> bool:
        return True


class FakeLLM(LLMProvider):
    def __init__(self, result: StructuredCommand | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def understand_command(self, text: str, cancel_event: Event | None = None) -> StructuredCommand | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class LLMPhase4Tests(unittest.TestCase):
    def make_assistant(self, llm: LLMProvider) -> Assistant:
        self.temp_dir = tempfile.TemporaryDirectory()
        tts = AsyncTextToSpeech(SilentTTS())
        self.addCleanup(tts.close)
        return Assistant(ActivityLogger(Path(self.temp_dir.name) / "activity.jsonl"), tts, llm)

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def test_openai_provider_parses_structured_json(self) -> None:
        class Message:
            content = '{"intent":"browser_search","parameters":{"query":"Python automation"}}'
        class Choice:
            message = Message()
        class Completions:
            def create(self, **kwargs):
                return type("Response", (), {"choices": [Choice()]})()
        client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
        command = OpenAILLMProvider(client, "test-model").understand_command("Search Python automation")
        self.assertEqual(command.steps[0].intent, "browser_search")
        self.assertEqual(command.steps[0].parameters["query"], "Python automation")

    def test_openai_provider_rejects_malformed_json(self) -> None:
        class Message:
            content = "not json"
        class Choice:
            message = Message()
        class Completions:
            def create(self, **kwargs):
                return type("Response", (), {"choices": [Choice()]})()
        client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
        with self.assertRaises(LLMError):
            OpenAILLMProvider(client, "test-model").understand_command("Do something")

    def test_english_bangla_and_banglish_structured_steps_validate(self) -> None:
        for text, language in (("Open YouTube", "en"), ("ইউটিউব ওপেন করো", "bn"), ("YouTube open koro", "banglish")):
            command = StructuredCommandValidator.from_payload(
                {"steps": [{"intent": "open_website", "parameters": {"url": "https://youtube.com"}}], "response_language": language},
                text,
            )
            self.assertEqual(command.steps[0].intent, "open_website")
            self.assertEqual(command.response_language, language)

    def test_multi_step_llm_result_uses_existing_router(self) -> None:
        command = StructuredCommand((
            StructuredCommandValidator.from_payload({"intent": "open_website", "parameters": {"url": "https://youtube.com"}}, "x").steps[0],
            StructuredCommandValidator.from_payload({"intent": "browser_search", "parameters": {"query": "Python automation"}}, "x").steps[0],
        ))
        assistant = self.make_assistant(FakeLLM(command))
        calls: list[str] = []
        assistant.router.register("open_website", lambda request: calls.append(request.intent) or ActionResult(TaskStatus.COMPLETED, "Opened.", request))
        assistant.router.register("browser_search", lambda request: calls.append(request.intent) or ActionResult(TaskStatus.COMPLETED, "Searched.", request))
        result = assistant.handle("Open YouTube and search for Python automation.")
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(calls, ["open_website", "browser_search"])

    def test_invalid_and_unsafe_llm_output_is_rejected(self) -> None:
        for payload in (
            {"intent": "delete_everything", "parameters": {}},
            {"intent": "open_application", "parameters": {"application": "powershell"}},
        ):
            with self.assertRaises(LLMError):
                StructuredCommandValidator.from_payload(payload, "unsafe")

    def test_provider_failure_falls_back_to_deterministic_parser(self) -> None:
        assistant = self.make_assistant(FakeLLM(error=LLMError("network failure")))
        calls: list[str] = []
        assistant.router.register("open_application", lambda request: calls.append(request.parameters["application"]) or ActionResult(TaskStatus.COMPLETED, "Opened.", request))
        result = assistant.handle("Open Excel")
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(calls, ["Excel"])

    def test_cancel_discards_llm_result_without_routing(self) -> None:
        assistant = self.make_assistant(FakeLLM(StructuredCommandValidator.from_payload({"intent": "open_website", "parameters": {"url": "https://youtube.com"}}, "x")))
        assistant.state.cancel()
        calls: list[str] = []
        assistant.router.register("open_website", lambda request: calls.append(request.intent) or ActionResult(TaskStatus.COMPLETED, "Opened.", request))
        result = assistant.handle("Open YouTube", reset_cancellation=False)
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(calls, [])

    def test_cancel_does_not_call_llm(self) -> None:
        llm = FakeLLM()
        assistant = self.make_assistant(llm)
        result = assistant.handle("AURA, stop")
        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertEqual(llm.calls, 0)


if __name__ == "__main__":
    unittest.main()