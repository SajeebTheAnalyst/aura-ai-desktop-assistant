"""Allowlisted Windows and browser operations."""
from __future__ import annotations

import os
import webbrowser
from urllib.parse import quote, urlencode


class OSService:
    def shutdown_pc(self) -> str:
        os.system("shutdown /s /t 5")
        return "Your PC will shut down in five seconds."

    def sleep_pc(self) -> str:
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "Putting your PC to sleep."

    def open_app(self, app_name: str) -> str:
        name = app_name.strip()
        if not name:
            return "Which application should I open?"
        try:
            from AppOpener import open as open_application
            open_application(name, match_closest=True, output=False)
            return f"Opening {name}."
        except Exception as exc:
            return f"I could not open {name}: {exc}"

    def youtube_search(self, query: str) -> str:
        if not query.strip():
            return "What should I search for on YouTube?"
        webbrowser.open(f"https://www.youtube.com/results?search_query={quote(query)}")
        return f"Searching YouTube for {query}."

    def send_gmail(self, to: str, subject: str, body: str) -> str:
        if not to.strip():
            return "Please provide the recipient email address first."
        params = urlencode({"view": "cm", "to": to, "su": subject, "body": body})
        webbrowser.open(f"https://mail.google.com/mail/?{params}")
        return "I opened a Gmail compose window with the supplied draft. It has not been sent."