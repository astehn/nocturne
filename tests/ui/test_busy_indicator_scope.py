"""What a long operation shows. Andreas, 2026-10-04: the thin bar drawn over the
top edge of the image is gone. It only ever appeared when the right column
already showed progress, so it duplicated it.

History: on 2026-09-13 the bar was scoped to user-requested, image-changing work
and kept off step-entry splits ("I dont think that we need to show indicator 1").

What stays: the right column (label, progress, elapsed, Cancel), the busy CURSOR
(it is what tells you the click you just made is being ignored) and the disabled
controls. Nothing is drawn on top of the picture.
"""
from __future__ import annotations

from tests.ui.test_main_window import _window, _make_fits


def _win(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    return win


def _show_now(win):
    """Skip BUSY_DELAY_MS; the visuals are timer-driven."""
    win._show_busy_visuals()


def test_nothing_is_drawn_over_the_image_any_more(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    before = sorted(c.objectName() + type(c).__name__ for c in win.image_view.children())
    _show_now(win)
    after = sorted(c.objectName() + type(c).__name__ for c in win.image_view.children())
    assert after == before, "a busy op must add nothing on top of the picture"
    win._hide_busy_visuals()


def test_the_right_column_still_reports(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    win._busy_label_text = "Separating stars…"
    _show_now(win)
    # isHidden(), not isVisible(): the suite never shows the top-level window.
    assert "Separating stars" in win._busy_label.text()
    assert not win._cancel_btn.isHidden() and not win._elapsed_label.isHidden()
    win._hide_busy_visuals()


def test_the_busy_cursor_is_still_set_and_balanced(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication
    win = _win(qtbot, tmp_path)
    _show_now(win)
    assert win._cursor_active is True
    win._hide_busy_visuals()
    assert win._cursor_active is False
    assert QApplication.overrideCursor() is None


def test_no_module_imports_the_busy_bar():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2] / "nocturne"
    hits = [p for p in root.rglob("*.py") if re.search(r"busy_bar|BusyBar", p.read_text())]
    assert hits == []
