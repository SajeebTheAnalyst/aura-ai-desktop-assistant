import unittest

from app.core.models import ActionRequest
from app.core.permissions import PermissionManager


class PermissionTests(unittest.TestCase):
    def test_unknown_action_is_high_risk(self) -> None:
        self.assertTrue(PermissionManager().requires_confirmation(ActionRequest("run_shell")))

    def test_search_is_low_risk(self) -> None:
        self.assertFalse(PermissionManager().requires_confirmation(ActionRequest("browser_search")))


if __name__ == "__main__":
    unittest.main()
