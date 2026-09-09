from __future__ import annotations

from app.core.models import ActionRequest, Risk


class PermissionManager:
    RISK_BY_INTENT = {"open_website": Risk.LOW, "browser_search": Risk.LOW, "open_application": Risk.LOW,
                      "type_text": Risk.LOW, "press_key": Risk.LOW, "hotkey": Risk.LOW,
                      "close_application": Risk.MEDIUM, "excel_type": Risk.MEDIUM, "analyze_file": Risk.LOW,
                      "rename_file": Risk.MEDIUM, "move_file": Risk.MEDIUM, "delete_file": Risk.HIGH,
                      "shutdown": Risk.HIGH}

    def risk_for(self, request: ActionRequest) -> Risk:
        return self.RISK_BY_INTENT.get(request.intent, Risk.HIGH)

    def requires_confirmation(self, request: ActionRequest) -> bool:
        return self.risk_for(request) is not Risk.LOW
