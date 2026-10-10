"""The redesigned start page (Andreas approved the mock-ups 2026-10-10): six
cards in two rows, one row on a short window, an info line under each, a
locked card that dims instead of greying, the clicked card marked while it
opens, and a "get started" panel when there are no projects yet."""
import json
import time
import zipfile
from datetime import datetime

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QEnterEvent, QImage
from PySide6.QtWidgets import QApplication

from nocturne.ui import theme
from nocturne.ui.welcome import (
    _CARD_BG, _PAD, _card_pixmap, CARD_H, CARD_W, LOCKED_OPACITY, SAMPLE_URL, WelcomeScreen, card_info, when_text,
)
from tests.ui.test_main_window import _window

NGC7000 = {"target": "NGC 7000", "exposure": 3260.0, "frames": 163}   # a Nocturne master: EXPTIME total


def _jpeg(colour=QColor(200, 40, 40), w=480, h=270) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(colour)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", 95)
    return bytes(data)


def _bundle(path, meta=None, jpeg=None):
    """A .nocturne as far as the start page reads one: the manifest and the
    thumbnail. The images it never reads are left out."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"base": {"metadata": meta or {}}}))
        if jpeg:
            zf.writestr("preview.jpg", jpeg)
    return str(path)


def _files(tmp_path, n):
    return [_bundle(tmp_path / f"p{i}.nocturne", NGC7000, _jpeg()) for i in range(n)]


def _shown(page):
    return [b for b in page.recent_buttons if b.isVisible()]


def _top(widget, page):
    return widget.mapTo(page, QPoint(0, 0)).y()


# --- layout ----------------------------------------------------------------------
def test_the_page_reads_top_to_bottom(qtbot, tmp_path):
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: _files(tmp_path, 6))
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    title, tag = w.title, w.tagline
    assert abs(_top(title, w) + title.height() - (_top(tag, w) + tag.height())) <= 1, \
        "the tagline is on the title's line"
    assert tag.mapTo(w, QPoint(0, 0)).x() > title.mapTo(w, QPoint(0, 0)).x() + title.width() - 1
    order = [title, w.recent_title, w.recent_buttons[0], w.recent_buttons[3], w.stack_btn,
             w.drop_hint, w.busy_row, w._warning_room, w.update_note]
    tops = [_top(x, w) for x in order]
    assert tops == sorted(tops) and len(set(tops)) == len(tops)
    assert w.recent_title.text() == "RECENT PROJECTS"
    assert w.drop_hint.text() == "…or drop a FITS or TIFF anywhere on this window"
    assert w.drop_hint.isVisible()
    texts = [lab.text() for lab in w.findChildren(type(w.title))]
    assert not any("Stack a night's frames" in t for t in texts), "the old hint line is gone"


def test_six_cards_on_a_large_window_and_three_at_1280x800(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = _files(tmp_path, 8)
    win.resize(1600, 1000)
    win.show()
    qtbot.waitExposed(win)
    page = win._welcome
    qtbot.waitUntil(lambda: len(_shown(page)) == 6, timeout=2000)
    assert page.rows() == 2
    win.resize(1280, 800)                       # re-decided on resize
    qtbot.waitUntil(lambda: len(_shown(page)) == 3, timeout=2000)
    assert page.rows() == 1
    bottom = page.update_note.mapTo(page, QPoint(0, page.update_note.height())).y()
    assert bottom <= page.height(), "everything under the buttons still fits"
    win.resize(1600, 1000)
    qtbot.waitUntil(lambda: len(_shown(page)) == 6, timeout=2000)


def test_the_cards_are_a_three_column_grid_of_filled_pictures(qtbot, tmp_path):
    tall = _bundle(tmp_path / "tall.nocturne", NGC7000, _jpeg(w=200, h=600))
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [tall] + _files(tmp_path, 5))
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    xs = sorted({b.x() for b in w.recent_buttons})
    ys = sorted({b.y() for b in w.recent_buttons})
    assert len(xs) == 3 and len(ys) == 2
    pic = w.recent_buttons[0].picture.toImage()
    # A tall frame cropped to fill: picture right to the box's edges, no ground.
    for x, y in ((1, CARD_H // 2), (CARD_W - 2, CARD_H // 2), (CARD_W // 2, 1)):
        assert pic.pixelColor(x, y).red() > 150, (x, y)


def test_the_buttons_stay_put_in_both_modes(qtbot, tmp_path):
    """While there are cards, however many: a card can vanish (its file moved)
    or appear under the cursor. The empty state is centred on its own height
    instead (review I-3) — see the test below."""
    files = _files(tmp_path, 6)
    for size in ((1200, 700), (1400, 860)):
        source = {"list": files[:1]}
        w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: source["list"])
        qtbot.addWidget(w)
        w.resize(*size)
        w.show()
        qtbot.waitExposed(w)
        empty = w.stack_btn.mapTo(w, QPoint(0, 0))
        for n in (4, 6, 2, 1):
            source["list"] = files[:n]
            w.refresh_recent()
            qtbot.wait(10)
            assert w.stack_btn.mapTo(w, QPoint(0, 0)) == empty, (size, n)


# --- the info line -----------------------------------------------------------------
def test_the_info_line_leaves_out_what_is_missing():
    now = time.time()
    assert card_info(NGC7000, now, now) == "NGC 7000 · 54m · today"
    assert card_info({"target_solved": "M 31"}, now, now) == "M 31 · today"
    assert card_info({"exposure": 20.0, "frames": 90}, now, now) == "30m · today"
    assert card_info({}, now, now) == "today"
    assert card_info({}, None, now) == ""
    assert card_info({"target": "  "}, None, now) == ""
    assert "· ·" not in card_info({"target": "M 8", "exposure": None}, now, now)


def test_a_card_reads_its_line_from_the_bundle(qtbot, tmp_path):
    path = _bundle(tmp_path / "NGC7000_Narrowband.nocturne", NGC7000, _jpeg())
    broken = tmp_path / "broken.nocturne"
    broken.write_bytes(b"not a zip")
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [path, str(broken)])
    qtbot.addWidget(w)
    card, bad = w.recent_buttons
    assert card.text() == "NGC7000_Narrowband"
    assert card.info == "NGC 7000 · 54m · today"
    assert bad.info == "today", "an unreadable bundle still gets a card, with what is known"


def test_when_is_said_in_calendar_days():
    now = datetime(2026, 10, 10, 0, 10).timestamp()
    at = lambda *a: datetime(*a).timestamp()            # noqa: E731
    assert when_text(at(2026, 10, 10, 0, 1), now) == "today"
    assert when_text(at(2026, 10, 9, 23, 50), now) == "yesterday", "twenty minutes, but yesterday"
    assert when_text(at(2026, 10, 7, 12), now) == "3 days ago"
    assert when_text(at(2026, 10, 4, 12), now) == "6 days ago"
    assert when_text(at(2026, 10, 3, 12), now) == "3 Oct"
    assert when_text(at(2025, 12, 24, 12), now) == "24 Dec 2025"
    assert when_text(at(2026, 10, 11, 12), now) == "today", "a clock that disagrees is not 'in -1 days'"


# --- hover -----------------------------------------------------------------------
def test_hovering_lifts_the_card(qtbot, tmp_path):
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: _files(tmp_path, 2))
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    card = w.recent_buttons[0]
    assert card.cursor().shape() == Qt.CursorShape.PointingHandCursor
    before = card.grab().toImage()
    p = QPointF(40, 40)
    QApplication.sendEvent(card, QEnterEvent(p, p, card.mapToGlobal(p)))
    assert card.is_lifted()
    after = card.grab().toImage()
    edge = after.pixelColor(_PAD, _PAD + CARD_H + 20)
    assert abs(edge.blue() - QColor(theme.ACCENT).blue()) < 30 and edge.blue() > edge.red() + 60, \
        "the border turns accent blue"
    assert after != before
    QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
    assert not card.is_lifted()
    card.setEnabled(False)
    QApplication.sendEvent(card, QEnterEvent(p, p, card.mapToGlobal(p)))
    assert not card.is_lifted(), "a locked card does not invite a click"


# --- opening -------------------------------------------------------------------
def _centre(page, card):
    """The picture's centre, as drawn on the page (so behind it is the page)."""
    img = page.grab().toImage()
    at = card.mapTo(page, QPoint(_PAD + CARD_W // 2 + 40, _PAD + CARD_H // 2))
    return img.pixelColor(at)


def test_a_locked_card_dims_but_keeps_its_colour(qtbot, tmp_path):
    """His "nasty grey" (2026-10-10): a disabled QToolButton greyed every
    thumbnail while a project opened."""
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: _files(tmp_path, 3))
    qtbot.addWidget(w)
    w.setStyleSheet(theme.build_stylesheet())       # the real, dark ground behind it
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    card = w.recent_buttons[1]
    live = _centre(w, card)
    card.setEnabled(False)
    locked = _centre(w, card)
    ground = QColor(theme.BG_1)
    assert live.red() > 150 and live.red() - live.green() > 120, "precondition: a strongly red picture"
    # Exactly the picture at LOCKED_OPACITY over the page: dimmed, same colour.
    # The old greyed icon fails this: (153, 153, 153), measured by mutation.
    for ch in ("red", "green", "blue"):
        want = LOCKED_OPACITY * getattr(live, ch)() + (1 - LOCKED_OPACITY) * getattr(ground, ch)()
        assert abs(getattr(locked, ch)() - want) <= 8, (ch, live.getRgb(), locked.getRgb())
    assert locked.red() > locked.green() + 50, "still red, not grey"


def test_the_clicked_card_is_marked_until_the_open_ends(qtbot, tmp_path):
    state = {"busy": False}
    opened = []

    def on_recent(p):
        opened.append(p)
        state["busy"] = True            # the window locks the page

    files = _files(tmp_path, 3)
    w = WelcomeScreen(lambda: None, lambda: None, on_recent=on_recent,
                      recent=lambda: files, locked=lambda: state["busy"])
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    w.recent_buttons[1].click()
    assert opened == [files[1]]
    marks = [b.is_opening() for b in w.recent_buttons]
    assert marks == [False, True, False]
    assert w.recent_buttons[1].ring.isVisibleTo(w)
    assert not w.recent_buttons[0].ring.isVisibleTo(w)
    w.refresh_recent()                  # rebuilt mid-open (the page re-shown)
    assert [b.is_opening() for b in w.recent_buttons] == marks
    state["busy"] = False               # the open failed or was cancelled
    w.refresh_recent()
    assert not any(b.is_opening() for b in w.recent_buttons)
    assert not any(b.ring.isVisibleTo(w) for b in w.recent_buttons)


def test_a_click_that_starts_nothing_leaves_no_mark(qtbot, tmp_path):
    files = _files(tmp_path, 2)
    w = WelcomeScreen(lambda: None, lambda: None, on_recent=lambda p: None,
                      recent=lambda: files)
    qtbot.addWidget(w)
    w.recent_buttons[0].click()          # e.g. "save changes?" answered Cancel
    assert not any(b.is_opening() for b in w.recent_buttons)


def test_opening_from_the_window_marks_one_and_dims_the_rest(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = _files(tmp_path, 3)
    win.resize(1400, 900)
    win.show()
    qtbot.waitExposed(win)
    page = win._welcome
    monkeypatch.setattr(win, "_open_project", lambda p=None: win._set_busy(True, "Opening project…"))
    page.recent_buttons[0].click()
    clicked, other = page.recent_buttons[0], page.recent_buttons[1]
    assert clicked.is_opening() and clicked.ring.isVisibleTo(win)
    assert not other.isEnabled() and not other.is_opening()
    img = page.grab().toImage()
    edge = img.pixelColor(clicked.mapTo(page, QPoint(_PAD + 1, _PAD + CARD_H + 20)))
    assert edge.blue() > 180 and edge.blue() > edge.red() + 80, "a 2 px accent border"
    win._set_busy(False)                 # failed or cancelled: back to normal
    assert all(b.isEnabled() and not b.is_opening() for b in page.recent_buttons)


# --- no projects ------------------------------------------------------------------
def test_with_no_projects_the_page_says_how_to_start(qtbot):
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [])
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    assert w.empty_panel.isVisible() and w.recent_title.text() == "GET STARTED"
    assert not w.drop_hint.isVisible(), "the drop box says it; the hint would repeat it"
    assert SAMPLE_URL == "https://nocturneastro.com/sample-data.html"
    assert f"href='{SAMPLE_URL}'" in w.sample_link.text()
    assert "Download a sample stack" in w.sample_link.text()
    assert w.sample_link.openExternalLinks()
    assert w.drop_zone.isVisible()


def test_a_drop_on_the_drop_box_reaches_the_window(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = []
    win.resize(1400, 900)
    win.show()
    qtbot.waitExposed(win)
    zone = win._welcome.drop_zone
    assert zone.isVisible()
    p = tmp_path / "m.nocturne"
    p.write_text("x")
    opened = []
    monkeypatch.setattr(win, "_open_project", lambda path=None: opened.append(path))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(zone, enter)
    assert enter.isAccepted() and win._drop_overlay.isVisibleTo(win)
    drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(zone, drop)
    qtbot.waitUntil(lambda: opened == [str(p)], timeout=3000)


@pytest.mark.parametrize("n", [0, 6])
def test_the_page_fits_the_smallest_window(qtbot, tmp_path, n):
    from nocturne.ui.main_window import MIN_WINDOW
    win = _window(qtbot, tmp_path)
    win.settings.recent_projects = _files(tmp_path, n)
    win.resize(*MIN_WINDOW)
    win.show()
    qtbot.waitExposed(win)
    assert win.size().toTuple() == MIN_WINDOW, "the page does not raise the window's floor"
    page = win._welcome
    bottom = page.update_note.mapTo(page, QPoint(0, page.update_note.height())).y()
    assert bottom <= page.height()


def test_card_integration_is_whole_minutes_and_hours():
    from nocturne.ui.welcome import _card_integration
    assert _card_integration(20) == "20s"
    assert _card_integration(3260) == "54m"          # 54m 20s
    assert _card_integration(3570) == "1h 00m"       # 59m 30s rounds up into the hour
    assert _card_integration(12300) == "3h 25m"


# --- fix round 1 (review 2026-10-10) ----------------------------------------------
def test_the_empty_page_is_centred_not_held_low(qtbot):
    """Review I-3: the first page a new user sees sat ~250 px low, holding room
    for two rows of cards it did not have."""
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [])
    qtbot.addWidget(w)
    w.resize(1400, 1000)
    w.show()
    qtbot.waitExposed(w)
    assert w.rows() == 2, "precondition: a page tall enough for two rows"
    above = _top(w.title, w)
    below = w.height() - (_top(w.update_note, w) + w.update_note.height())
    assert abs(above - below) <= 4, (above, below)


def _busy_page(qtbot):
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [])
    qtbot.addWidget(w)
    w.resize(1400, 860)
    w.show()
    qtbot.waitExposed(w)
    return w


def _at(widget, page):
    return widget.mapTo(page, QPoint(0, 0))


def test_cancel_has_its_own_line_and_never_moves(qtbot):
    """His request, 2026-10-10: the label's ticking dots changed its width and
    walked the Cancel button sideways. Buttons must never move."""
    w = _busy_page(qtbot)
    before = _at(w.stack_btn, w)
    w.show_busy("Opening project…")
    qtbot.wait(10)
    assert _at(w.stack_btn, w) == before, "the row's room was already there"
    cancel, label, ring = _at(w.busy_cancel, w), _at(w.busy_label, w), _at(w.busy_ring, w)
    assert cancel.y() >= label.y() + w.busy_label.height(), "Cancel under the text"
    assert abs(ring.y() + w.busy_ring.height() / 2 - (label.y() + w.busy_label.height() / 2)) <= 2, \
        "ring and text share the first line"
    centre = w.width() / 2
    assert abs(cancel.x() + w.busy_cancel.width() / 2 - centre) <= 1, "Cancel centred"
    for dots in range(4):
        w.set_busy_text("Opening project…" + "." * dots)
        qtbot.wait(5)
        assert (_at(w.busy_cancel, w), _at(w.busy_label, w), _at(w.busy_ring, w)) == \
            (cancel, label, ring), dots
    w.busy_cancel.setText("Finishing…")           # what the window says when nothing can stop
    qtbot.wait(5)
    assert _at(w.busy_cancel, w) == cancel
    w.hide_busy()
    qtbot.wait(5)
    assert _at(w.stack_btn, w) == before


def test_the_label_is_wide_enough_for_three_dots(qtbot):
    w = _busy_page(qtbot)
    w.show_busy("Opening project…")
    fm = w.busy_label.fontMetrics()
    assert w.busy_label.width() >= fm.horizontalAdvance("Opening project…...")


def test_a_cancel_from_the_window_keeps_its_place(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.resize(1400, 900)
    win.show()
    qtbot.waitExposed(win)
    page = win._welcome
    win._set_busy(True, "Opening project…")
    win._show_busy_visuals()
    qtbot.wait(5)
    assert page.busy_label.isVisible(), "precondition: the page's row is the one ticking"
    where = [_at(x, page) for x in (page.busy_cancel, page.busy_label, page.busy_ring)]
    texts = set()
    for _ in range(4):
        win._tick_ellipsis()
        qtbot.wait(5)
        texts.add(page.busy_label.text())
        assert [_at(x, page) for x in (page.busy_cancel, page.busy_label, page.busy_ring)] == where
    assert len(texts) == 4, "precondition: the dots really ticked"
    win._set_busy(False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_a_garbage_exposure_never_breaks_the_page(qtbot, tmp_path, value):
    """Review I-1: a NaN EXPTIME saved into a bundle raised out of the card
    and stopped the app launching."""
    path = _bundle(tmp_path / "bad.nocturne", {"target": "M 8", "exposure": value, "frames": 10})
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [path])
    qtbot.addWidget(w)
    assert [b.info for b in w.recent_buttons] == ["M 8 · today"]


def test_non_positive_totals_are_left_out():
    now = time.time()
    assert card_info({"exposure": 30.0, "frames": -3}, now, now) == "today"
    assert card_info({"exposure": 0.0, "frames": 3}, now, now) == "today"


def test_a_card_that_cannot_be_built_falls_back_to_its_name(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.welcome as wm
    path = _bundle(tmp_path / "Odd.nocturne", NGC7000, _jpeg())
    corrupt = tmp_path / "corrupt.nocturne"
    with zipfile.ZipFile(corrupt, "w") as zf:
        zf.writestr("manifest.json", "{not json")
    monkeypatch.setattr(wm, "card_info", lambda *a, **k: 1 / 0)
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [path, str(corrupt)])
    qtbot.addWidget(w)
    assert [b.text() for b in w.recent_buttons] == ["Odd", "corrupt"]
    assert [b.info for b in w.recent_buttons] == ["", ""]


def test_the_app_launches_with_a_garbage_bundle_in_the_list(qtbot, tmp_path):
    from nocturne.settings import Settings, save_settings
    bad = _bundle(tmp_path / "bad.nocturne", {"exposure": float("nan"), "frames": 10})
    s = Settings()
    s.recent_projects = [bad]
    save_settings(s, str(tmp_path / "settings.json"))
    win = _window(qtbot, tmp_path)
    assert [b.text() for b in win._welcome.recent_buttons] == ["bad"]


def test_hiding_the_page_clears_the_opening_mark(qtbot, tmp_path):
    """Review M-2: a successful open hides the page before the window goes
    idle, so the rebuild that clears the mark never ran."""
    state = {"busy": False}
    files = _files(tmp_path, 2)
    w = WelcomeScreen(lambda: None, lambda: None, on_recent=lambda p: state.update(busy=True),
                      recent=lambda: files, locked=lambda: state["busy"])
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.recent_buttons[0].click()
    assert w.recent_buttons[0].is_opening()
    w.hide()
    assert not any(b.is_opening() or b.ring.isVisibleTo(w) for b in w.recent_buttons)
    w.show()                                          # shown again while still busy
    assert not any(b.is_opening() for b in w.recent_buttons)


def test_an_open_that_raises_leaves_no_mark(qtbot, tmp_path):
    """Review M-3."""
    def boom(p):
        raise OSError("disk full")
    files = _files(tmp_path, 2)
    w = WelcomeScreen(lambda: None, lambda: None, on_recent=boom, recent=lambda: files)
    qtbot.addWidget(w)
    with pytest.raises(OSError):
        w._card_clicked(w.recent_buttons[0])
    assert not any(b.is_opening() or b.ring.isVisibleTo(w) for b in w.recent_buttons)


def test_the_placeholder_is_the_bare_crescent(qtbot):
    """Review M-6: the app icon's dark rounded square showed round the moon."""
    img = _card_pixmap(None, 1.0).toImage()
    ground = _CARD_BG.rgb()
    dark_not_ground, cream = 0, 0
    for y in range(CARD_H):
        for x in range(CARD_W):
            c = img.pixelColor(x, y)
            if c.rgb() == ground:
                continue
            if max(c.red(), c.green(), c.blue()) > 200:
                cream += 1
            elif max(c.red(), c.green(), c.blue()) < 45:
                dark_not_ground += 1
    assert cream > 300, "the crescent is drawn"
    assert dark_not_ground < 40, dark_not_ground
