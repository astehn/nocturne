"""Curves on small screens (Andreas, 2026-09-26): when the step area cannot
hold the inline curve editor, the step offers only the large editor. The
inline editor shrinks to 240 px (its pre-August size) before it goes, so a
1920x1080 window — and his 2364x1100 — keep it.

Measured 2026-09-26 (styled, offscreen): room for the step 208 px at
1280x800, 252 at 1512x982, 350 at 1920x1080, 370 at 2364x1100."""
import pytest
from PySide6.QtWidgets import QApplication

from nocturne.ui.theme import build_stylesheet
from tests.ui.test_main_window import _make_fits, _window


@pytest.fixture(autouse=True)
def _styled():
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(before)


def _curves(qtbot, tmp_path, w, h):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(w, h); win.show(); qtbot.waitExposed(win)
    win._go_to_id("stretch", user_initiated=False)
    win._panel.apply_btn.click(); qtbot.wait(30)
    win._go_to_id("curves", user_initiated=False); qtbot.wait(50)
    return win


@pytest.mark.parametrize("w,h,inline", [(1280, 800, False), (1512, 982, False),
                                        (1920, 1080, True), (2364, 1100, True)])
def test_the_inline_editor_only_where_it_fits(qtbot, tmp_path, w, h, inline):
    win = _curves(qtbot, tmp_path, w, h)
    p = win._panel
    assert p.curve_editor.isVisible() is inline
    assert p.expand_btn.isVisible()
    if not inline:
        assert "curve editor" in p.expand_btn.text().lower()
    else:
        # and the step's own controls fit without scrolling. (The "How this
        # works" text below them may still scroll — it is open by default.)
        room = win._side.scroll.viewport().height()
        assert p.minimumSizeHint().height() <= room, f"Curves' controls scroll at {w}x{h}"


def test_a_curve_made_in_the_large_editor_is_what_apply_commits(qtbot, tmp_path):
    """With the inline editor hidden, the large one must still round-trip."""
    from nocturne.core.curves import curve_key
    win = _curves(qtbot, tmp_path, 1280, 800)
    assert not win._panel.curve_editor.isVisible()
    pts = [(0.0, 0.0), (0.4, 0.6), (1.0, 1.0)]
    win._on_curves_dialog_apply({curve_key("rgb", "all"): pts})
    qtbot.wait(20)
    assert win._panel.apply_btn.state() == "pending"
    win._panel.apply_btn.click(); qtbot.wait(30)
    assert [n for n, _ in win.project.entries()][-1] == "Curves"
    committed = win.project.entries()[-1][1]
    assert list(map(tuple, committed[curve_key("rgb", "all")])) == pts


def test_resizing_brings_the_inline_editor_back(qtbot, tmp_path):
    win = _curves(qtbot, tmp_path, 1280, 800)
    assert not win._panel.curve_editor.isVisible()
    win.resize(1920, 1080); qtbot.wait(50)
    assert win._panel.curve_editor.isVisible()
    win.resize(1280, 800); qtbot.wait(50)
    assert not win._panel.curve_editor.isVisible()


def test_where_there_is_room_the_inline_editor_is_its_full_size(qtbot, tmp_path):
    """Review 2026-09-26: a 240 px minimum made it 240 everywhere (it has no
    size hint of its own) — 25% smaller than main at his window size. Where
    the room is there, it is 320 as on main."""
    from nocturne.ui.main_window import _CURVE_FULL
    win = _curves(qtbot, tmp_path, 2560, 1440)
    assert win._panel.curve_editor.height() == _CURVE_FULL


def test_in_the_band_between_it_shrinks_but_never_below_240(qtbot, tmp_path):
    from nocturne.ui.main_window import _CURVE_FULL, _CURVE_MIN
    win = _curves(qtbot, tmp_path, 1920, 1080)
    h = win._panel.curve_editor.height()
    assert _CURVE_MIN <= h <= _CURVE_FULL
    assert win._panel.minimumSizeHint().height() <= win._side.scroll.viewport().height()
