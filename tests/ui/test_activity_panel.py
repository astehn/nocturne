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
