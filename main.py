"""Single executable entry point for AURA."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.assistant import Assistant
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AURA")
    window = MainWindow(Assistant())
    window.show()
    window.start_voice_loop()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())