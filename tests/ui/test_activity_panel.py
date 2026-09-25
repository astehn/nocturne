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
    from nocturne.ui.theme import DANGER, WARNING
    p = _panel(qtbot)
    p.add("notice", "Colour was switched off")
    notice_html = p.view.toHtml().lower()
    assert WARNING.lower() in notice_html and DANGER.lower() not in notice_html
    p.clear()
    p.add("warn", "RC-Astro failed")
    assert DANGER.lower() in p.view.toHtml().lower()


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
