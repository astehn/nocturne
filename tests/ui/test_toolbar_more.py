"""Screen-size piece 4 (Andreas, 2026-09-26): a click-only More ▾ instead of
Qt's hover-collapsing overflow, a fixed never-overflow set, and an Icons only
toolbar style on Settings ▸ General (default stays Icons and text)."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QToolButton

from nocturne.ui.theme import build_stylesheet
from tests.ui.test_main_window import _make_fits, _window

PINNED = ("Open Image", "Open Project", "Save Project", "Settings", "Auto Enhance",
          "Undo", "Redo", "Reset", "Before/After", "Fit", "100%")
FIRST_TO_GO = ["Batch…", "Save Recipe", "Share", "Upscale Crop", "Trim",
               "Starless Levels…", "Star Spikes…", "Colour Balance", "Narrowband…",
               "Plate Solve", "Combine…", "Ha/OIII…", "Stack…"]


@pytest.fixture(autouse=True)
def _styled():
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(before)


def _settle(qtbot, win):
    """Wait until the bar has stopped re-laying itself out — a fixed short
    wait once ended mid-sequence and hid a real bug (review 2026-09-26)."""
    for _ in range(3):
        qtbot.waitUntil(lambda: not win._overflow._pending, timeout=2000)
        qtbot.wait(10)


def _cut(win):
    """Tools on the bar that Qt could not fit and hid — the user-visible failure."""
    return [a.text() for a in win._toolbar.actions()
            if a.isVisible() and a.text() and win._toolbar.widgetForAction(a) is not None
            and not win._toolbar.widgetForAction(a).isVisible()]


def _win(qtbot, tmp_path, width, style="text"):
    win = _window(qtbot, tmp_path)
    win.settings.toolbar_style = style
    win._apply_toolbar_style()
    win.resize(width, 800); win.show(); qtbot.waitExposed(win)
    _settle(qtbot, win)
    return win


def _on_bar(win, text):
    act = next((a for a in win._toolbar.actions() if a.text() == text), None)
    w = win._toolbar.widgetForAction(act) if act is not None else None
    return act is not None and act.isVisible() and w is not None and w.isVisible()


def _qt_chevron(win):
    ext = win._toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    return ext is not None and ext.isVisible() and ext.width() > 0


@pytest.mark.parametrize("width", [1120, 1280, 1366, 1440, 1512, 1920, 2364])
def test_the_bar_always_fits_nothing_is_cut(qtbot, tmp_path, width):
    win = _win(qtbot, tmp_path, width)
    for text in PINNED:
        assert _on_bar(win, text), f"{text} left the bar at {width}"
    assert not _cut(win), f"on the bar but cut off by Qt at {width}: {_cut(win)}"
    gone = [a.text() for a in win._overflow.hidden]
    assert gone == FIRST_TO_GO[:len(gone)], "tools left in the wrong order"
    assert win._more_act.isVisible() == bool(gone)


def test_a_wide_window_needs_no_more(qtbot, tmp_path):
    win = _win(qtbot, tmp_path, 3200)
    assert win._overflow.hidden == [] and not win._more_act.isVisible()


def test_the_menu_holds_exactly_what_left_and_works(qtbot, tmp_path):
    win = _win(qtbot, tmp_path, 1280)
    hidden = win._overflow.hidden
    assert hidden, "precondition: something overflows at 1280 with text"
    shown = [p.text() for p in win._more_btn.menu().actions() if p.isVisible()]
    order = [a.text() for a in win._overflow._all if a in hidden]
    assert shown == order, "the menu should read in toolbar order"
    fired = []
    batch = next(a for a in hidden if a.text() == "Batch…")
    assert batch.isEnabled(), "a tool in More must stay live"
    batch.triggered.disconnect()
    batch.triggered.connect(lambda *_: fired.append(True))
    win._overflow.proxy_for(batch).trigger()
    assert fired == [True]


def test_menu_items_follow_the_real_tool_state(qtbot, tmp_path):
    win = _win(qtbot, tmp_path, 1280)
    share = win._share_act
    assert share in win._overflow.hidden
    proxy = win._overflow.proxy_for(share)
    assert proxy.isEnabled() == share.isEnabled() is False     # no image yet
    share.setEnabled(True)
    assert proxy.isEnabled()


def test_the_more_menu_opens_on_click_not_hover(qtbot, tmp_path):
    win = _win(qtbot, tmp_path, 1280)
    assert win._more_btn.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup


def test_icons_only_fits_at_1280_with_nothing_in_more(qtbot, tmp_path):
    win = _win(qtbot, tmp_path, 1280, style="icons")
    assert win._toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert win._overflow.hidden == []
    assert not _cut(win)
    for a in win._toolbar.actions():
        if not a.isSeparator() and a.text() and a.isVisible():
            assert a.toolTip(), f"{a.text()} has no tooltip in icons-only"


@pytest.mark.parametrize("width,style", [(1440, "text"), (1180, "icons"), (1120, "text")])
def test_the_bar_does_not_change_between_steps(qtbot, tmp_path, width, style):
    """At widths where tools are SPLIT between the bar and More — at 1280 with
    text all of them are in More, and a dependence on greyed-out state could
    not show."""
    win = _win(qtbot, tmp_path, width, style)
    win.open_fits(_make_fits(tmp_path)); _settle(qtbot, win)
    assert win._overflow.hidden and len(win._overflow.hidden) < 13, "precondition: a split bar"

    def snap():
        return ([a.text() for a in win._overflow.hidden],
                [(a.text(), win._toolbar.widgetForAction(a).mapTo(win, QPoint(0, 0)).x())
                 for a in win._toolbar.actions()
                 if a.isVisible() and not a.isSeparator() and win._toolbar.widgetForAction(a)])
    first = snap()
    for i, st in enumerate(list(win._stages)):
        if st.enabled:
            win._go_to(i, user_initiated=False); _settle(qtbot, win)
            assert snap() == first, st.id


def test_the_style_is_a_setting_and_defaults_to_text(qtbot, tmp_path):
    from nocturne.settings import Settings, load_settings, save_settings
    assert Settings().toolbar_style == "text"
    p = str(tmp_path / "s.json")
    save_settings(Settings(toolbar_style="icons"), p)
    assert load_settings(p).toolbar_style == "icons"


def test_general_offers_the_toolbar_style(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(Settings())
    qtbot.addWidget(dlg)
    assert dlg.tabs.widget(0).isAncestorOf(dlg.toolbar_box)
    assert dlg.toolbar_box.currentText() == "Icons and text"
    dlg.toolbar_box.setCurrentText("Icons only")
    assert dlg.result_settings().toolbar_style == "icons"


@pytest.mark.parametrize("width", [1120, 1280, 1400])
def test_pressing_ok_in_settings_moves_nothing(qtbot, tmp_path, width):
    """OK re-polishes the bar (a FontChange). With a wiped width cache that put
    every tool in More back on the bar for a few frames and cut Undo…100%."""
    win = _win(qtbot, tmp_path, width)
    before = ([a.text() for a in win._overflow.hidden], win._toolbar.toolButtonStyle())
    seen = []
    orig = win._overflow._apply

    def spy(all_items, hidden):
        orig(all_items, hidden)
        seen.append(([a.text() for a in hidden], win._toolbar.toolButtonStyle(), _cut(win)))
    win._overflow._apply = spy
    win._apply_toolbar_style()          # what Settings ▸ OK does
    _settle(qtbot, win)
    for step in seen:
        assert (step[0], step[1]) == before and not step[2], step
    assert ([a.text() for a in win._overflow.hidden], win._toolbar.toolButtonStyle()) == before
