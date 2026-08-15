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


@pytest.fixture(autouse=True)
def _no_real_file_dialogs(monkeypatch):
    """A real file dialog in the suite blocks forever with nothing to click.

    That happened once already: migrating the app off the static
    QFileDialog.getXxx helpers left old monkeypatches pointing at a class the
    code no longer calls, so tests opened genuine modal panels and the run hung
    instead of failing. A hang tells you nothing; this raises with the caption,
    which names the test and the dialog in one line.
    """
    from nocturne.ui import file_dialogs

    def refuse(parent, caption, directory, filters):
        raise AssertionError(
            f"a real file dialog was opened in a test: {caption!r}. Patch "
            f"nocturne.ui.file_dialogs.choose_folder / open_file / save_file.")

    monkeypatch.setattr(file_dialogs, "_prepare", refuse)
