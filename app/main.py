from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.core.assistant import Assistant
from app.core.logging import ActivityLogger
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AURA")
    app.setOrganizationName("AURA")
    logger = ActivityLogger(Path("logs") / "activity.jsonl")
    window = MainWindow(Assistant(logger))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
