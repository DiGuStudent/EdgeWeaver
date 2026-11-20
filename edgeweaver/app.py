"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .mainwindow import MainWindow, application_icon


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("EdgeWeaver")
    app.setApplicationDisplayName("EdgeWeaver")
    app.setOrganizationName("EdgeWeaver")
    app.setStyle("Fusion")
    app.setWindowIcon(application_icon())

    window = MainWindow()
    window.show()
    for arg in argv[1:]:
        p = Path(arg)
        if p.suffix.lower() == ".tim" and p.exists():
            window.open_document(str(p))
            break
    return app.exec()
