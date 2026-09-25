from PySide6.QtCore import Qt

from nocturne.ui.activity_panel import ActivityChannel, ActivityPanel


def _panel(qtbot):
    p = ActivityPanel()
    qtbot.addWidget(p)
    return p


def test_one_stream_in_order_with_kinds(qtbot):
    p = _panel(qtbot)
    p.add("step", "Background (strong) · Δ1.2%")
    p.add("result", "SPCC: 212 stars matched")
    p.add("warn", "RC-Astro failed")
    text = p.text()
    assert text.index("Background") < text.index("SPCC") < text.index("RC-Astro")
    assert [e.split(" ", 1)[1] for e in p.entries("result")] == ["SPCC: 212 stars matched"]


def test_each_kind_is_coloured_apart(qtbot):
    p = _panel(qtbot)
    for kind in ("step", "result", "info", "warn"):
        p.add(kind, kind)
    html = p.view.toHtml()
    assert html.count("color:") >= 3          # result, info, warn carry colours


def test_channels_keep_the_old_apis_and_stay_separate(qtbot):
    p = _panel(qtbot)
    log = ActivityChannel(p, "step")
    out = ActivityChannel(p, "result")
    log.append_entry("Opened x · 24×24")
    out.show_line("Plate solved")
    assert "Opened x" in log.text() and "Plate solved" not in log.text()
    assert out.toPlainText() == "Plate solved"
    assert out.isReadOnly()
    assert out.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    out.clear()
    assert out.toPlainText() == "" and "Opened x" in log.text()


def test_clear_empties_everything(qtbot):
    p = _panel(qtbot)
    p.add("step", "a"); p.add("result", "b")
    p.clear()
    assert p.text() == "" and p.entries() == []


def test_an_empty_line_is_ignored_like_the_old_output_box(qtbot):
    p = _panel(qtbot)
    ActivityChannel(p, "result").show_line("")
    assert p.entries() == []


def test_the_large_view_shows_everything_unwrapped(qtbot):
    p = _panel(qtbot)
    p.add("step", "x" * 300)
    dlg = p.open_large(extra="Command: graxpert\nstderr: boom")
    qtbot.addWidget(dlg)
    assert "x" * 300 in dlg.text_edit.toPlainText()
    assert "stderr: boom" in dlg.text_edit.toPlainText()


def test_a_notice_is_amber_and_a_warning_red(qtbot):
    """A notice is a consequence of the user's own action (main window's
    `_show_notice`); logging it in the warning's red calls it an error."""
    from nocturne.ui.activity_panel import NOTICE_COLOUR, WARN_COLOUR
    p = _panel(qtbot)
    p.add("notice", "Colour was switched off")
    notice_html = p.view.toHtml().lower()
    assert NOTICE_COLOUR.lower() in notice_html and WARN_COLOUR.lower() not in notice_html
    p.clear()
    p.add("warn", "RC-Astro failed")
    assert WARN_COLOUR.lower() in p.view.toHtml().lower()


def _contrast(a: str, b: str) -> float:
    def lum(h):
        def ch(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        h = h.lstrip("#")
        r, g, bl = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(bl)
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _colour_of(style: str) -> str:
    return style.split("color:", 1)[1].split(";", 1)[0].strip()


def test_the_lines_are_quiet_beside_the_image_but_still_told_apart(qtbot):
    """Andreas, 2026-09-25: bright text right beside a dark image pulls the
    eye off the image. Step lines are not the bright TEXT, every kind still
    differs from every other, and none drops below 4.5:1 on either dark
    background the box can sit on."""
    from nocturne.ui.activity_panel import KIND_STYLE
    from nocturne.ui.theme import BG_1, BG_2, TEXT
    p = _panel(qtbot)
    p.add("step", "Crop")
    step_html = p.view.toHtml().lower()
    assert _colour_of(KIND_STYLE["step"]).lower() != TEXT.lower()
    assert TEXT.lower() not in step_html
    kinds = ("step", "result", "info", "warn", "notice")
    assert len({KIND_STYLE[k] for k in kinds}) == len(kinds)
    hues = [_colour_of(KIND_STYLE[k]).lower() for k in ("step", "result", "warn", "notice")]
    assert len(set(hues)) == len(hues)
    for k in kinds:
        c = _colour_of(KIND_STYLE[k])
        # and quieter than TEXT: at most ~half its contrast
        assert 4.5 <= _contrast(c, BG_2) and _contrast(c, BG_1) < 0.5 * _contrast(TEXT, BG_1), k


def test_the_text_is_smaller_than_the_window_font(qtbot):
    """Relative, so it follows the app font — and re-applied when the app
    stylesheet's own font arrives, which QTextEdit would otherwise copy over
    the document's."""
    from PySide6.QtGui import QFont
    p = _panel(qtbot)
    def size(f):
        return f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF()
    assert size(p.view.document().defaultFont()) <= size(p.view.font()) - 1
    big = QFont(p.view.font())
    big.setPointSizeF(20)
    p.view.setFont(big)
    assert 18 <= p.view.document().defaultFont().pointSizeF() <= 19
    p.view.setStyleSheet("font-size: 16px;")
    p.view.ensurePolished()
    assert 14 <= p.view.document().defaultFont().pixelSize() <= 15


def _newest_is_in_view(p) -> bool:
    from PySide6.QtGui import QTextCursor
    cur = p.view.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    return p.view.viewport().rect().contains(p.view.cursorRect(cur).center())


def test_no_scrollbar_and_the_newest_line_always_shows(qtbot):
    """Andreas, 2026-09-25: no scrollbar in the activity box; newest at the
    bottom, older lines off the top, the full history behind ⤢."""
    p = _panel(qtbot)
    p.resize(220, 90)
    p.show()
    qtbot.waitExposed(p)
    for i in range(40):
        p.add("step", f"line {i}")
    bar = p.view.verticalScrollBar()
    assert p.view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert bar.maximum() > 0, "precondition: more lines than fit"
    assert bar.value() == bar.maximum()
    assert _newest_is_in_view(p)
    assert not _newest_is_in_view_after_scrolling_to_top(p)


def _newest_is_in_view_after_scrolling_to_top(p) -> bool:
    p.view.verticalScrollBar().setValue(0)
    shown = _newest_is_in_view(p)
    p.view.verticalScrollBar().setValue(p.view.verticalScrollBar().maximum())
    return shown


def test_a_rebuild_after_clearing_one_kind_still_shows_the_newest(qtbot):
    p = _panel(qtbot)
    p.resize(220, 90)
    p.show()
    qtbot.waitExposed(p)
    for i in range(40):
        p.add("step" if i % 2 else "result", f"line {i}")
    p.clear("result")
    bar = p.view.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.value() == bar.maximum()
    assert _newest_is_in_view(p)


def test_the_newest_line_survives_a_resize(qtbot):
    """No scrollbar, so a newest line pushed below the fold by a window
    resize could not be recovered by eye (re-review, 2026-09-25)."""
    p = _panel(qtbot)
    p.resize(220, 300)
    p.show()
    qtbot.waitExposed(p)
    for i in range(60):
        p.add("step", f"line {i} with some words to wrap")
    assert p.view.verticalScrollBar().maximum() > 0, "precondition: more than fits"
    for w, h in ((220, 120), (220, 90), (160, 90), (220, 400), (300, 150)):
        p.resize(w, h)
        qtbot.wait(10)
        assert _newest_is_in_view(p), f"newest line out of view at {w}x{h}"


def test_a_resize_does_not_yank_someone_reading_history(qtbot):
    p = _panel(qtbot)
    p.resize(220, 150)
    p.show()
    qtbot.waitExposed(p)
    for i in range(60):
        p.add("step", f"line {i}")
    p.view.verticalScrollBar().setValue(0)
    p.resize(220, 140)
    qtbot.wait(10)
    assert p.view.verticalScrollBar().value() == 0
