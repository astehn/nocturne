"""Qt tests run headless by default.

The fullscreen tests call `_toggle_fullscreen()` on a window that has been
`show()`n, and on macOS `showFullScreen()` takes over an entire screen — so
running the suite made the machine unusable until it finished. Roughly ten other
tests flash a window for the same reason.

The offscreen platform plugin builds real widgets and delivers real events; it
simply never composites them to a display. Everything CLAUDE.md says about
verifying GUI state by sending Qt events to a real window and reading the widget
back still holds — only the pixels on your monitor go away. Measured on the full
suite: 1345 passed either way, 13 s faster headless.

`setdefault`, not assignment, so you can still watch a test run:

    QT_QPA_PLATFORM=cocoa .venv/bin/python -m pytest tests/ui/test_main_window.py -q

This must run before anything constructs a QApplication — the platform plugin is
chosen at construction, and pytest imports the root conftest before collecting
tests or creating the `qapp` fixture.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# On Windows the offscreen plugin looks for fonts in PySide6/lib/fonts, which Qt
# no longer ships, and finds NONE: every string is measured in a built-in
# fallback ("Preserve luminosity" 228 px, against 103 px in Segoe UI), so every
# does-this-text-fit test fails and none of them means anything. Point it at
# the system's fonts. Measured 2026-10-12: with this, the layout tests that
# failed offscreen pass, as they do under the real `windows` plugin.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))


# --- the user's real settings file is off limits to the suite ----------------
#
# `stack_dialog._toggle_hints` persisted a preference by writing the WHOLE
# settings object to `resolve_settings_path()` — the real ~/.nocturne/settings.json
# — whatever settings path the app had actually been given. MainWindow gets a
# temp path in tests, so a test that toggled those explanations wrote a fresh,
# EMPTY `Settings()` over the developer's file and silently wiped their
# configured GraXpert / RC-Astro / ASTAP paths. It happened for real on
# 2026-09-11; the file was rewritten at 09:29:38 by a full-suite run.
#
# Fixing that one call site is not the guarantee. This is: while the suite runs,
# the default path resolves inside a temp directory, so NO test can reach the
# real file however it gets there. An explicit `home=` still behaves normally,
# because tests/test_settings_migration.py legitimately drives that argument.

import tempfile

import pytest

import nocturne.settings as _settings

_REAL_RESOLVE = _settings.resolve_settings_path
_SANDBOX = tempfile.mkdtemp(prefix="nocturne_settings_")


def _sandboxed_resolve(home: str | None = None) -> str:
    return _REAL_RESOLVE(home=home if home is not None else _SANDBOX)


_settings.resolve_settings_path = _sandboxed_resolve


@pytest.fixture(autouse=True, scope="session")
def _settings_sandbox():
    """Belt and braces: keep the redirect in place for the whole session even if
    something re-imports the module."""
    _settings.resolve_settings_path = _sandboxed_resolve
    yield
    _settings.resolve_settings_path = _REAL_RESOLVE


# `sessionlog._active` and `_started_at` are MODULE GLOBALS. A test that calls
# start_session() sets them for every test that runs after it — and since
# run_cli and _log_step write on every tool invocation and every step, the rest
# of the suite then appends to one leftover temp file and stats it on each
# write. Isolation here rather than in each test, because the writers are deep
# in the app and no individual test knows it is logging.
@pytest.fixture(autouse=True)
def _isolated_session_log():
    import nocturne.core.sessionlog as _sl
    active, started = _sl._active, _sl._started_at
    _sl._active, _sl._started_at = None, None
    try:
        yield
    finally:
        _sl._active, _sl._started_at = active, started


# --- the developer's Nocturne NR models are off limits too -------------------
#
# ~/.nocturne/models is where the Nocturne NR project delivers models for
# testing, and onnxruntime is in .venv — so without this, every Noise Reduction
# panel built by the suite would list whatever happens to be in that folder on
# this machine, and a test asserting the engine list would pass or fail by who
# ran it. Both discovery folders point at an empty directory for the session;
# tests that need a model put one in their own tmp folder and monkeypatch.

import nocturne.core.nr_models as _nr_models

_NR_SANDBOX = tempfile.mkdtemp(prefix="nocturne_nr_models_")


@pytest.fixture(autouse=True)
def _nr_models_sandbox(monkeypatch):
    monkeypatch.setattr(_nr_models, "TRAY_DIR", _NR_SANDBOX)
    monkeypatch.setattr(_nr_models, "SHIPPED_DIR", _NR_SANDBOX)


# --- Windows: the default font the real platform gives -----------------------
#
# Offscreen's default family is "Sans Serif", which resolves to Arial; the real
# `windows` plugin gives Segoe UI 9 pt (both measured on the VM, 2026-10-12).
# Text-fit tests must measure what a Windows user sees, so the suite's
# QApplication starts with that font. A no-op everywhere else.
if sys.platform == "win32":
    import pytest

    @pytest.fixture(scope="session")
    def qapp_cls():
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication

        class _WindowsDefaultFontApp(QApplication):
            def __init__(self, *args):
                super().__init__(*args)
                self.setFont(QFont("Segoe UI", 9))

        return _WindowsDefaultFontApp


# --- prompt refusals -----------------------------------------------------------
#
# Here, not in tests/ui/conftest.py: a command line that mixes tests/ui files with
# files outside it ran the UI tests without them (8 teardown errors in
# test_auto_levels_ui after test_step_panels + test_user_presets, 2026-10-14).
# Each keeps its import guard, so a run without Qt still collects.

import inspect


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
    (tests/ui/conftest.py) share one function-scoped `monkeypatch`, and `undo()` reverts both,
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

    These fixtures and tests/ui/conftest.py's _no_real_file_dialogs cover the routes that had bitten before: the
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
