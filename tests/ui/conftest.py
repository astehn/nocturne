import pytest


@pytest.fixture(scope="session", autouse=True)
def _auto_answer_dialogs():
    """MainWindow.closeEvent prompts a modal QMessageBox.question when the project
    has edits; at qtbot teardown (which closes tracked widgets) that would block
    forever headless. Default all question dialogs to Discard so teardown never
    hangs. Tests that assert on the dialog override this locally via monkeypatch.
    """
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:
        yield
        return
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Discard)
    try:
        yield
    finally:
        QMessageBox.question = orig
