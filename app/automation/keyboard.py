from __future__ import annotations

import ctypes
import sys
from abc import ABC, abstractmethod
from threading import Event
from ctypes import wintypes


class KeyboardAdapter(ABC):
    @abstractmethod
    def type_text(self, text: str, cancel_event: Event | None = None) -> None: ...

    @abstractmethod
    def press_key(self, key: str, cancel_event: Event | None = None) -> None: ...

    @abstractmethod
    def hotkey(self, keys: tuple[str, ...], cancel_event: Event | None = None) -> None: ...


class _KeyInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeyInput), ("padding", ctypes.c_ubyte * 32)]


class _Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", _InputUnion)]


class WindowsKeyboardAdapter(KeyboardAdapter):
    _KEYS = {"enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
             "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
             "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}

    def _vk(self, key: str) -> int:
        normalized = key.casefold().strip()
        if normalized in self._KEYS:
            return self._KEYS[normalized]
        if len(normalized) == 1:
            return ord(normalized.upper())
        if normalized.startswith("f") and normalized[1:].isdigit() and 1 <= int(normalized[1:]) <= 12:
            return 0x70 + int(normalized[1:]) - 1
        raise ValueError(f"Unsupported key: {key}")

    def _send(self, vk: int, key_up: bool = False) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows keyboard automation is only available on Windows.")
        flags = 0x0002 if key_up else 0
        ctypes.windll.user32.keybd_event(vk, 0, flags, 0)

    def type_text(self, text: str, cancel_event: Event | None = None) -> None:
        for char in text:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Keyboard typing cancelled.")
            for key_up in (False, True):
                flags = 0x0004 | (0x0002 if key_up else 0)
                input_event = _Input(1, _InputUnion(_KeyInput(0, ord(char), flags, 0, None)))
                if ctypes.windll.user32.SendInput(1, ctypes.byref(input_event), ctypes.sizeof(_Input)) != 1:
                    raise OSError("Windows rejected the keyboard input.")

    def press_key(self, key: str, cancel_event: Event | None = None) -> None:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Key press cancelled.")
        vk = self._vk(key)
        self._send(vk)
        self._send(vk, True)

    def hotkey(self, keys: tuple[str, ...], cancel_event: Event | None = None) -> None:
        if not keys:
            raise ValueError("At least one key is required.")
        pressed = []
        try:
            for key in keys:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Hotkey cancelled.")
                vk = self._vk(key)
                self._send(vk)
                pressed.append(vk)
            for vk in reversed(pressed):
                self._send(vk, True)
        finally:
            for vk in reversed(pressed):
                self._send(vk, True)