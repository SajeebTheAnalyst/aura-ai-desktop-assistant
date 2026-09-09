import unittest

from app.ai.intent_parser import IntentParser


class IntentParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser()

    def test_banglish_search(self) -> None:
        action = self.parser.parse("Chrome open kore Python automation search koro.")
        self.assertEqual(action.intent, "browser_search")
        self.assertEqual(action.parameters["query"], "Chrome open kore Python automation")

    def test_open_excel(self) -> None:
        action = self.parser.parse("Open Excel")
        self.assertEqual(action.intent, "open_application")
        self.assertEqual(action.parameters["application"], "Excel")

    def test_cancel(self) -> None:
        self.assertEqual(self.parser.parse("AURA, stop").intent, "cancel")


if __name__ == "__main__":
    unittest.main()
