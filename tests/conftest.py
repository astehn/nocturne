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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


# The suite must describe a RELEASE, not this machine. `~/.nocturne/models`
# holds models from the separate Nocturne NR project during internal testing,
# and MainWindow inserts a Linear Denoise stage when it finds one — so on
# 2026-09-18 three navigation tests failed here and passed everywhere else,
# because a file in a developer's home directory had changed the pipeline.
#
# Pointed at an empty directory for the whole session. A test that wants the
# stage sets EXTERNAL_DIR itself, which also makes that intent visible.
import nocturne.core.denoise_model as _denoise_model  # noqa: E402

_NO_MODELS = tempfile.mkdtemp(prefix="nocturne_no_models_")
_denoise_model.EXTERNAL_DIR = _NO_MODELS


@pytest.fixture(autouse=True, scope="session")
def _no_external_models():
    _denoise_model.EXTERNAL_DIR = _NO_MODELS
    yield


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
