"""Long GraXpert denoises must look alive.

A second user restarted Nocturne several times during a GraXpert denoise,
believing it had hung; he only discovered it was normal by timing the same image
in GraXpert itself. Two separate defects made that experience:

1. The "this can take a few minutes" warning already existed but was skipped for
   exactly the users who cannot avoid the wait.
2. GraXpert prints `Progress: N%` every ~2 s and Nocturne discarded all of it.
"""
import numpy as np
import pytest

from nocturne.settings import Settings


class _S(Settings):
    pass


def _settings(graxpert: str = "", rcastro: str = "", engine: str = "rcastro"):
    s = Settings()
    s.graxpert_path = graxpert
    s.rcastro_path = rcastro
    s.denoise_engine = engine
    return s


def test_the_warning_appears_for_a_graxpert_only_user(qtbot, tmp_path, monkeypatch):
    """THE BUG. With GraXpert but no RC-Astro no engine dropdown is shown, so the
    option carries `settings.denoise_engine` — whose default is "rcastro". The
    step's fallback then runs GraXpert anyway, but the label test had already
    failed, so the user got a bare "Applying Noise Reduction…" while the app sat
    silent for minutes.

    The label must follow the engine that will ACTUALLY run.
    """
    from tests.ui.test_main_window import _window
    import nocturne.settings as st

    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(st, "graxpert_valid", lambda s: True)
    monkeypatch.setattr(st, "rcastro_valid", lambda s: False)
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: False)

    label = win._busy_label_for("noise_sharpen", {"engine": "rcastro", "level": "strong"})
    assert "GraXpert" in label, f"no GraXpert warning for a GraXpert-only user: {label!r}"
    assert "minutes" in label


def test_the_warning_stays_for_an_explicit_graxpert_choice(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _window
    import nocturne.ui.main_window as mw

    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    label = win._busy_label_for("noise_sharpen", {"engine": "graxpert", "level": "strong"})
    assert "GraXpert" in label


def test_no_graxpert_warning_when_rcastro_will_run(qtbot, tmp_path, monkeypatch):
    """RC-Astro denoise is seconds, not minutes. Warning about a wait that will
    not happen is its own kind of lie."""
    from tests.ui.test_main_window import _window
    import nocturne.ui.main_window as mw

    win = _window(qtbot, tmp_path)
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    label = win._busy_label_for("noise_sharpen", {"engine": "rcastro", "level": "strong"})
    assert "GraXpert" not in label


def test_a_tool_reporting_progress_drives_the_progress_bar(qtbot, tmp_path):
    """End to end: `report_progress` from inside a tool, on the worker thread,
    reaches the determinate bar. Before this the bar existed but nothing but
    stacking ever fed it, so a GraXpert denoise showed only a counting number.
    """
    from nocturne.core.tasks import clear_ambient, report_progress, set_ambient
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    seen = []
    # Read the bar's state AS the signal lands: the busy state is torn down when
    # the operation finishes, so asserting afterwards would only prove the reset.
    # The slot connected in __init__ runs first, so the state is already set.
    win._tool_progress.progress.connect(
        lambda d, t: seen.append((d, t, win._progress_state)))

    def work():
        report_progress(42, 100)      # as GraXpert's parser does, off the UI thread
        return None

    win._run_busy(work, lambda _r: None, "Denoising…", "failed")
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    done, total, state = seen[-1]
    assert (done, total) == (42, 100)
    assert state == ("Denoising", 42, 100), (
        f"progress did not reach the bar: {state}")


def test_a_tool_that_reports_nothing_leaves_the_bar_alone(qtbot, tmp_path):
    """The indeterminate sweep must remain for tools with no percentage — a bar
    stuck at 0% reads worse than an honest sweep."""
    from tests.ui.test_main_window import _window

    win = _window(qtbot, tmp_path)
    win._run_busy(lambda: None, lambda _r: None, "Working…", "failed")
    assert win._progress_state[2] == 0, "a silent tool should leave total at 0"
