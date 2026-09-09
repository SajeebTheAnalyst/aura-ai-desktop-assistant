from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QMenu, QSystemTrayIcon


def create_tray(window: QMainWindow, cancel: Callable[[], None]) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(QIcon(), window)
    menu = QMenu(window)
    menu.addAction("Open AURA", window.showNormal)
    menu.addAction("Stop current task", cancel)
    menu.addAction("Exit AURA", window.close)
    tray.setContextMenu(menu)
    tray.show()
    return tray
