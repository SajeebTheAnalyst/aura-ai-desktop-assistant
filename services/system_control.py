"""Windows system control engine: turns AURA intent plans into real actions.

Design rules:
- ``execute_system_command`` never raises; every path returns a short spoken
  reply so the voice loop always keeps going.
- OPEN_APP resolves apps via PATH, well-known install locations, then the
  Windows ``start`` launcher; unknown apps degrade to a web search.
- SYSTEM_ACTION handles shutdown / restart / sleep / lock / settings.
- WEB_SEARCH opens Google / other sites, or runs a Google query.
- PLAY_MUSIC plays the requested song on YouTube immediately: direct
  top-result parsing of the YouTube search page (8 s timeout) with pywhatkit's
  ``playonyt`` local scrape as fallback - never a stuck search/playlist tab.
  Re-triggers of the same song are deduplicated (no duplicate browser tabs; the
  playing window is refocused instead).
- ``dry_run=True`` returns the would-be command instead of executing it
  (used for safe testing of destructive actions).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
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


def _play_music(target: str, dry_run: bool = False) -> str:
    """Play a song on YouTube immediately - top result, never a search tab.

    Order: pywhatkit.playonyt (if installed) -> direct top-result parsing of
    the YouTube search page -> plain YouTube search tab as a last resort.
    Re-triggers of the same song inside the dedup window never open a duplicate
    tab; the window already playing it is refocused instead.
    """
    song = (target or "").strip()
    if not song:
        return "Which song should I play?"
    key = song.lower()
    now = time.time()
    with _music_lock:
        recently = now - _music_cache.get(key, 0.0) < _MUSIC_DEDUP_SECONDS
    if recently and not dry_run:
        # Same song re-triggered: do NOT open a duplicate tab - refocus the
        # YouTube window that is already playing it.
        _refocus_youtube_window()
        return f"Already playing {song.title()}."
    if dry_run:
        return f"[dry-run] playonyt('{song}') -> top YouTube result with autoplay"
    with _music_lock:
        _music_cache[key] = now

    # 1) Direct search-query parsing: scrape the top result's video id
    #    (bounded by an 8 s timeout - the fastest, most reliable path).
    video_id = _extract_youtube_video_id(song)
    if video_id:
        try:
            webbrowser.open(f"https://www.youtube.com/watch?v={video_id}&autoplay=1")
            return f"Playing {song.title()}."
        except Exception:
            pass

    # 2) pywhatkit.playonyt - its LOCAL scrape picks the top watch result.
    #    (use_api stays False: the pywhatkit.herokuapp.com API is defunct.)
    try:
        from pywhatkit import playonyt  # lazy: heavy import, music requests only

        playonyt(song)
        return f"Playing {song.title()}."
    except Exception:
        pass

    # 3) Last resort: a YouTube search tab for the song.
    try:
        webbrowser.open(f"https://www.youtube.com/results?search_query={quote(song)}")
        return f"Playing {song.title()}."
    except Exception:
        return f"I could not start {song.title()}."


def _refocus_youtube_window() -> bool:
    """Bring an already-open YouTube window/tab to the front. Never raises."""
    try:
        import pygetwindow as gw

        for window in gw.getAllWindows():
            if "youtube" in (window.title or "").lower():
                try:
                    if window.isMinimized:
                        window.restore()
                    window.activate()
                    return True
                except Exception:
                    return False
    except Exception:
        return False
    return False


def _extract_youtube_video_id(song: str) -> str | None:
    """Direct search-query parsing: return the top result's 11-char video id."""
    try:
        import requests

        response = requests.get(
            "https://www.youtube.com/results",
            params={"search_query": song},
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            timeout=8,
        )
        if response.status_code != 200:
            return None
        match = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', response.text)
        return match.group(1) if match else None
    except Exception:
        return None


# ---- music playback dedup state ----
_MUSIC_DEDUP_SECONDS = 12.0  # window in which re-triggers reuse the open tab
_music_cache: dict[str, float] = {}  # song -> last triggered epoch (seconds)
_music_lock = threading.Lock()


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
        elif intent == "PLAY_MUSIC":
            reply = _play_music(target, dry_run)
        else:
            return response or "I did not understand that command."
    except Exception as exc:  # final safety net - always speak something
        return response or f"I could not complete that: {exc}"
    # Prefer the model's natural voice reply; else our own execution text.
    return response or reply