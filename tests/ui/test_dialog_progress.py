"""A dialog doing its own background work can report progress too.

Starless Levels showed a moving bar because its star split goes through
`_run_busy`, which publishes a CancelToken carrying the progress sink. Narrowband
does the SAME split through `run_async` — its own thread, no token — so
`report_progress` found nobody listening and the dialog sat on a static
"Removing stars…" for the whole wait. Andreas spotted the inconsistency
immediately: same work, same cost, one of them silent.
"""
import pytest

from nocturne.core.tasks import current, report_progress
from nocturne.ui.worker import run_async


def test_run_async_publishes_a_sink_when_asked(qtbot):
    from PySide6.QtCore import QThreadPool

    seen = []
    done = []

    def work():
        assert current() is not None, "no ambient token on the worker thread"
        report_progress(37, 100)
        return "ok"

    run_async(QThreadPool.globalInstance(), work, done.append,
              on_progress=lambda d, t: seen.append((d, t)))
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    assert seen == [(37, 100)]


def test_without_a_handler_nothing_changes(qtbot):
    """Every other run_async caller must be untouched."""
    from PySide6.QtCore import QThreadPool

    done = []
    run_async(QThreadPool.globalInstance(), lambda: report_progress(1, 2) or "ok",
              done.append)
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    assert done == ["ok"]


def test_the_narrowband_dialog_shows_the_percentage(qtbot):
    """The wait is the star split, and the dialog's only sign of life was a
    static line of text."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.ui.narrowband_dialog import NarrowbandDialog

    from nocturne.settings import Settings

    img = AstroImage(np.full((32, 32, 3), 0.4, np.float32), is_linear=False, metadata={})
    # starless/stars supplied so construction does not kick off a real split.
    dlg = NarrowbandDialog(Settings(), img, starless=img, stars=None)
    qtbot.addWidget(dlg)
    dlg._on_split_progress(43, 100)
    assert "43%" in dlg.preview.message_text(), (
        f"the dialog does not show progress: {dlg.preview.message_text()!r}")


def test_the_colour_balance_dialog_shows_the_percentage(qtbot):
    """Same split, same wait — checked separately because the two dialogs each
    launch their own, and covering one would leave the other silent."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.ui.color_balance_dialog import ColorBalanceDialog

    img = AstroImage(np.full((32, 32, 3), 0.4, np.float32), is_linear=False, metadata={})
    from nocturne.settings import Settings

    dlg = ColorBalanceDialog(Settings(), img, starless=img, stars=None)
    qtbot.addWidget(dlg)
    dlg._on_split_progress(61, 100)
    assert "61%" in dlg.preview.message_text()


def test_every_dialog_that_splits_stars_reports_it():
    """A guard: a future dialog that launches the split without asking for
    progress would be silent for minutes, and nothing would say so."""
    import pathlib
    import re

    ui = pathlib.Path(__file__).resolve().parents[2] / "nocturne" / "ui"
    offenders = []
    for p in sorted(ui.glob("*_dialog.py")):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"run_async\((?:[^()]|\([^()]*\))*\)", src, re.S):
            call = m.group(0)
            if "_starx_runner" in call and "on_progress" not in call:
                offenders.append(f"{p.name}:{src[:m.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "splits stars without reporting progress: " + ", ".join(offenders))
