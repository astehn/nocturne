import inspect

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
        # Quitting with an unapplied preview asks, and qtbot closes every test
        # window at teardown — which is not a user quitting. Answer "discard"
        # for that one caller instead of failing the test that owned it.
        # Tests that actually exercise the quit prompt stub this themselves.
        if any(f.function == "closeEvent" for f in inspect.stack()[1:8]):
            return "discard"
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

    def refuse(self, names, label, verb, **kw):
        raise AssertionError(
            f"a real truncation-confirm prompt was opened in a test for "
            f"{names!r}. Stub MainWindow._ask_truncation via monkeypatch.")

    monkeypatch.setattr(mw.MainWindow, "_ask_truncation", refuse)


@pytest.fixture(autouse=True)
def _refuse_real_geometry_prompt(monkeypatch):
    """Same guard again, for the Rotate/Flip confirm.

    Rotate and Flip discard ALL processing, so `_apply_geometry` asks before
    truncating — and like the two above it builds its own QMessageBox and calls
    .exec(), which headless blocks forever instead of failing. Refusing loudly
    is deliberately not "return True": a test that unexpectedly opens this
    prompt has discovered that its fixture now has processing history to lose,
    which is worth knowing rather than papering over.
    """
    try:
        from nocturne.ui import main_window as mw
    except ImportError:
        return

    monkeypatch.setattr(mw.MainWindow, "_real_ask_geometry", mw.MainWindow._ask_geometry,
                        raising=False)

    def refuse(self, names, label):
        raise AssertionError(
            f"a real geometry-confirm prompt was opened in a test for {names!r} "
            f"({label}). Stub MainWindow._ask_geometry via monkeypatch.")

    monkeypatch.setattr(mw.MainWindow, "_ask_geometry", refuse)


@pytest.fixture(autouse=True)
def _refuse_real_auto_stretch_prompt(monkeypatch):
    """And again for the auto-stretch confirm.

    Navigating to a post-stretch step on a still-linear image commits a Stretch
    on the user's behalf, which truncates — it asks when that would cost a
    toolbar commit made while linear. Same .exec() hang risk, same loud refusal.
    """
    try:
        from nocturne.ui import main_window as mw
    except ImportError:
        return

    monkeypatch.setattr(mw.MainWindow, "_real_ask_auto_stretch",
                        mw.MainWindow._ask_auto_stretch, raising=False)

    def refuse(self, names, dest_label):
        raise AssertionError(
            f"a real auto-stretch confirm was opened in a test for {names!r} "
            f"(navigating to {dest_label}). Stub MainWindow._ask_auto_stretch.")

    monkeypatch.setattr(mw.MainWindow, "_ask_auto_stretch", refuse)


@pytest.fixture(scope="session", autouse=True)
def _no_generic_modal_exec():
    """A dialog that is neither a QMessageBox nor a file panel blocks forever.

    The three fixtures above cover the routes that had bitten before: the
    static QMessageBox.question, the app's own file_dialogs helper, and
    _ask_pending's hand-built box. Nothing covered a plain `SomeDialog.exec()`,
    and on 2026-09-22 the new ReportDialog arrived through exactly that gap:
    three existing tests called `_report_problem`, which had changed from
    opening a browser to opening a dialog. The run did not fail — it sat there
    for 1 hour 43 minutes against a normal 3.5, silent, having written zero
    bytes, until Andreas asked whether it was stuck.

    NOT a QMessageBox patch: _auto_answer_dialogs deliberately ANSWERS those
    rather than refusing, because closeEvent needs an answer at teardown, and
    refusing would break every test that closes a window with edits.

    Session-scoped. `setattr` on a PySide6 class is expensive — they are C++
    types and it invalidates their method caches — and doing it per test across
    ~1670 UI tests took this directory from 2m48 to over 4m15.
    """
    try:
        from PySide6.QtWidgets import QDialog
    except ImportError:                       # pragma: no cover - no Qt, no dialogs
        yield
        return

    def refuse(self, *a, **k):
        raise AssertionError(
            f"{type(self).__name__}.exec() would block the suite on a user who "
            "is never coming. Patch exec, or call the handler under it directly.")

    # exec_() as well: PySide's deprecation shim SWALLOWS the AssertionError,
    # prints a traceback and returns 0, so a test using it would neither hang
    # nor fail — it would silently read a bogus result code.
    saved = (QDialog.exec, QDialog.exec_)
    QDialog.exec, QDialog.exec_ = refuse, refuse
    try:
        yield
    finally:
        QDialog.exec, QDialog.exec_ = saved
