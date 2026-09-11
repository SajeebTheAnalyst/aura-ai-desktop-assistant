"""Windows system control engine: turns AURA intent plans into real actions.

Design rules:
- ``execute_system_command`` never raises; every path returns a short spoken
  reply so the voice loop always keeps going.
- OPEN_APP resolves apps via PATH, well-known install locations, then the
  Windows ``start`` launcher; unknown apps degrade to a web search.
- SYSTEM_ACTION handles shutdown / restart / sleep / lock / settings.
- WEB_SEARCH opens YouTube / Google / other sites, or runs a Google query.
- ``dry_run=True`` returns the would-be command instead of executing it
  (used for safe testing of destructive actions).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from typing import Any
from urllib.parse import quote

# Friendly spoken names -> Windows executable name or launcher alias.
APP_LAUNCHERS: dict[str, str] = {
    "powerbi": "PBIDesktop.exe",
    "power bi": "PBIDesktop.exe",
    "powerpoint": "powerpnt",
    "power point": "powerpnt",
    "ppt": "powerpnt",
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "notepad": "notepad",
    "cmd": "cmd",
    "command prompt": "cmd",
    "terminal": "cmd",
    "paint": "mspaint",
    "calculator": "calc",
    "calc": "calc",
    "excel": "excel",
    "word": "winword",
    "explorer": "explorer",
    "file explorer": "explorer",
    "spotify": "spotify",
    "vscode": "code",
    "visual studio code": "code",
    "pycharm": "pycharm",
    "discord": "discord",
    "steam": "steam",
    "whatsapp": "whatsapp",
    "vlc": "vlc",
    "settings": "ms-settings:",
}

# Standard install locations for apps that are normally NOT on PATH.
KNOWN_PATHS: dict[str, tuple[str, ...]] = {
    "PBIDesktop.exe": (
        r"C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        r"C:\Program Files (x86)\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Power BI Desktop\bin\PBIDesktop.exe"),
    ),
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ),
    "msedge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ),
    "powerpnt": (
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        r"C:\Program Files\Microsoft Office\root\Office15\POWERPNT.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
    ),
    "excel": (
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        r"C:\Program Files\Microsoft Office\root\Office15\EXCEL.EXE",
    ),
    "winword": (
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\root\Office15\WINWORD.EXE",
        r"C:\Program Files\Microsoft Office\root\Office16\WORD.EXE",
    ),
    "code": (
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ),
}

# action -> (shell command, natural spoken reply)
SYSTEM_COMMANDS: dict[str, tuple[str, str]] = {
    "shutdown": ("shutdown /s /t 5", "Shutting down your PC in five seconds."),
    "restart": ("shutdown /r /t 5", "Restarting your PC in five seconds."),
    "sleep": ("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", "Putting your PC to sleep."),
    "lock": ("rundll32.exe lkf.dll,,Lock", "Locking your PC."),
    "settings": ("start ms-settings:", "Opening Windows settings."),
}

SITE_URLS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
}


def resolve_launcher(target: str) -> str | None:
    """Map a spoken app name to a launcher/exe name (or None if unknown)."""
    name = (target or "").strip().lower()
    if not name:
        return None
    if name in APP_LAUNCHERS:
        return APP_LAUNCHERS[name]
    for alias, launcher in APP_LAUNCHERS.items():
        if name.startswith(alias) or f" {alias} " in f" {name} ":
            return launcher
    return None


def find_executable(launcher: str) -> str | None:
    """Locate an executable on PATH or in known install folders (fast probes)."""
    exe = shutil.which(launcher)
    if exe:
        return exe
    for candidate in KNOWN_PATHS.get(launcher, ()):
        if os.path.isfile(candidate):
            return candidate
    return None
def _open_app(target: str, dry_run: bool = False) -> str:
    name = (target or "").strip()
    key = name.lower()
    if not name:
        return "Which application should I open?"
    launcher = resolve_launcher(key)
    if launcher:
        exe = find_executable(launcher)
        if exe:
            if dry_run:
                return f"[dry-run] launch {exe}"
            try:
                subprocess.Popen([exe], cwd=os.path.expanduser("~"))
                return f"Opening {name}."
            except Exception:
                pass  # fall through to the `start` launcher
        # Registered alias or scheme (e.g. "ms-settings:", "chrome", "code").
        if dry_run:
            return f'[dry-run] start "" "{launcher}"'
        try:
            subprocess.Popen(f'start "" "{launcher}"', shell=True)
            return f"Opening {name}."
        except Exception:
            pass  # fall through to the web fallback
    # Unknown/untracked app -> Windows Start launcher, then a web search.
    if dry_run:
        return f'[dry-run] fallback start "" "{key}" then google search'
    try:
        subprocess.Popen(f'start "" "{key}"', shell=True)
        return f"Trying to open {name} for you."
    except Exception:
        pass
    try:
        webbrowser.open(f"https://www.google.com/search?q={quote(f'how to open {name} on windows')}")
        return f"I could not find {name}, so I searched for it."
    except Exception:
        return f"I could not open {name}."


def _system_action(target: str, dry_run: bool = False) -> str:
    action = (target or "").strip().lower()
    entry = SYSTEM_COMMANDS.get(action)
    if entry is None:
        return f"Sorry, {target or 'that system action'} is not supported."
    command, reply = entry
    if dry_run:
        return f"[dry-run] {command}"
    try:
        os.system(command)
        return reply
    except Exception as exc:
        return f"I could not complete that action: {exc}"


def _web_search(target: str, dry_run: bool = False) -> str:
    name = (target or "").strip()
    key = name.lower()
    if key in SITE_URLS:
        if dry_run:
            return f"[dry-run] open {SITE_URLS[key]}"
        webbrowser.open(SITE_URLS[key])
        return f"Opening {key}."
    if not name or key in {"search", "web"}:
        if dry_run:
            return "[dry-run] open https://www.google.com"
        webbrowser.open("https://www.google.com")
        return "Opening Google search."
    if dry_run:
        return f"[dry-run] open https://www.google.com/search?q={quote(name)}"
    webbrowser.open(f"https://www.google.com/search?q={quote(name)}")
    return f"Searching Google for {name}."


def execute_system_command(intent_data: dict[str, Any] | None, *, dry_run: bool = False) -> str:
    """Execute an intent plan and return the short spoken reply. Never raises.

    ``intent_data`` mirrors the LLM contract:
        {"intent": "OPEN_APP", "target": "powerbi", "response": "Opening Power BI."}
    """
    data = intent_data or {}
    intent = str(data.get("intent", "CHAT")).strip().upper()
    target = str(data.get("target", "") or "").strip()
    response = str(data.get("response", "") or "").strip()
    try:
        if intent == "OPEN_APP":
            reply = _open_app(target, dry_run)
        elif intent == "SYSTEM_ACTION":
            reply = _system_action(target, dry_run)
        elif intent == "WEB_SEARCH":
            reply = _web_search(target, dry_run)
        else:
            return response or "I did not understand that command."
    except Exception as exc:  # final safety net - always speak something
        return response or f"I could not complete that: {exc}"
    # Prefer the model's natural voice reply; else our own execution text.
    return response or reply