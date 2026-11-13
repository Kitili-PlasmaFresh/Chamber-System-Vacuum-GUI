"""Shared test setup. Runs Qt headless and keeps tests away from the real settings file."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")          # as main() does
    return app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point both versions at a temp settings file and record message boxes instead of showing them."""
    import gui.persistence
    import monroe_gui_original
    from PyQt6.QtWidgets import QMessageBox

    settings = tmp_path / "monroe_settings.json"
    monkeypatch.setattr(monroe_gui_original, "SETTINGS_FILE", str(settings))
    monkeypatch.setattr(gui.persistence, "SETTINGS_FILE", str(settings))
    boxes = []

    def fake(kind, answer=None):
        def box(*args, **kwargs):
            boxes.append((kind, args[1] if len(args) > 1 else ""))
            return answer
        return staticmethod(box)

    monkeypatch.setattr(QMessageBox, "warning", fake("warning"))
    monkeypatch.setattr(QMessageBox, "critical", fake("critical"))
    monkeypatch.setattr(QMessageBox, "information", fake("information"))
    monkeypatch.setattr(QMessageBox, "question", fake("question", QMessageBox.StandardButton.Yes))
    return boxes
