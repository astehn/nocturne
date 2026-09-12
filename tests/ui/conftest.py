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


@pytest.fixture(autouse=True)
def _refuse_real_pending_prompt(monkeypatch):
    """MainWindow._ask_pending builds its own QMessageBox and calls .exec()
    directly, so it is NOT covered by _auto_answer_dialogs above (that only
    patches the static QMessageBox.question helper). Unstubbed, it blocks
    forever headless — a real hang, not a failure. That happened once already:
    a test navigated away from a pending step without stubbing it, and the run
    sat at near-zero CPU until killed by hand. Raise instead, so the next test
    that adds a guarded navigation without stubbing the prompt gets a named
    failure. Tests that need an answer stub `_ask_pending` locally via
    monkeypatch, which simply overrides this (fixtures are function-scoped and
    monkeypatch unwinds in reverse order).

    The real implementation is stashed on the class as `_real_ask_pending`
    (also via monkeypatch, so it is gone by the next test) for the rare test
    that needs to exercise `_ask_pending`'s actual body — restore it with
    `monkeypatch.setattr(mw.MainWindow, "_ask_pending", mw.MainWindow._real_ask_pending)`,
    not a blanket `monkeypatch.undo()`: this fixture and `_no_real_file_dialogs`
    above share one function-scoped `monkeypatch`, and `undo()` reverts both,
    quietly disarming the file-dialog hang guard along with this one.
    """
    try:
        from nocturne.ui import main_window as mw
    except ImportError:
        return

    monkeypatch.setattr(mw.MainWindow, "_real_ask_pending", mw.MainWindow._ask_pending,
                        raising=False)

    def refuse(self, step_label):
        raise AssertionError(
            f"a real pending-change prompt was opened in a test for "
            f"{step_label!r}. Stub MainWindow._ask_pending via monkeypatch.")

    monkeypatch.setattr(mw.MainWindow, "_ask_pending", refuse)


@pytest.fixture(autouse=True)
def _refuse_real_truncation_prompt(monkeypatch):
    """MainWindow._ask_truncation builds its own QMessageBox and calls .exec()
    directly, same hang risk _refuse_real_pending_prompt above guards against
    for _ask_pending — an unstubbed call blocks forever headless rather than
    failing. Tests that need an answer stub `_ask_truncation` locally via
    monkeypatch, which simply overrides this.
    """
    try:
        from nocturne.ui import main_window as mw
    except ImportError:
        return

    monkeypatch.setattr(mw.MainWindow, "_real_ask_truncation", mw.MainWindow._ask_truncation,
                        raising=False)

    def refuse(self, names, verb):
        raise AssertionError(
            f"a real truncation-confirm prompt was opened in a test for "
            f"{names!r}. Stub MainWindow._ask_truncation via monkeypatch.")

    monkeypatch.setattr(mw.MainWindow, "_ask_truncation", refuse)
