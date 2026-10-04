"""After an export, the Export step says where the file went and reveals it.

The 2026-10-04 first-time-user audit (F-05): the only trace of a finished
export was an Activity line, so the user had to leave the app to find it. The
line lives in the pinned description box, because Export scrolls ~400 px at
1280x800 and a "done" line below the fold would not be seen.
"""
import re

import pytest

from tests.ui.test_main_window import _make_fits, _window


def _desc(win) -> str:
    return re.sub(r"<[^>]+>", "", win._panel.desc_box.text().replace("<br>", "\n"))


def _export(win, monkeypatch, path, fmt="TIFF"):
    from nocturne.ui import file_dialogs
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (str(path), "")))
    win.export_final(fmt)


def _at_export(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("export")
    return win


def test_before_any_export_it_is_just_the_description(qtbot, tmp_path):
    from nocturne.ui.step_panels import STEP_DESCRIPTIONS
    win = _at_export(qtbot, tmp_path)
    assert _desc(win) == STEP_DESCRIPTIONS["export"]


def test_a_finished_export_names_the_file_and_offers_to_reveal_it(qtbot, tmp_path, monkeypatch):
    from nocturne.ui.step_panels import REVEAL_LABEL
    win = _at_export(qtbot, tmp_path)
    out = tmp_path / "pic.tiff"
    _export(win, monkeypatch, out)
    assert out.exists(), "fixture: the export really happened"
    assert _desc(win).splitlines()[1] == f"Saved pic.tiff · {REVEAL_LABEL}"
    assert win._panel.desc_box.toolTip() == str(out), "the full path, on hover"


def test_the_link_reveals_exactly_that_file(qtbot, tmp_path, monkeypatch):
    win = _at_export(qtbot, tmp_path)
    out = tmp_path / "pic.tiff"
    _export(win, monkeypatch, out)
    revealed = []
    monkeypatch.setattr(win, "_reveal_in_file_manager", revealed.append)
    win._panel.desc_box.linkActivated.emit("reveal")
    assert revealed == [str(out)]


def test_a_failed_export_announces_nothing(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    from nocturne.ui.step_panels import STEP_DESCRIPTIONS
    win = _at_export(qtbot, tmp_path)
    monkeypatch.setattr(mw, "save_tiff",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    _export(win, monkeypatch, tmp_path / "pic.tiff")
    assert "Export failed" in win._warning.text(), "fixture: it really failed"
    assert _desc(win) == STEP_DESCRIPTIONS["export"]


def test_it_survives_leaving_and_returning(qtbot, tmp_path, monkeypatch):
    win = _at_export(qtbot, tmp_path)
    _export(win, monkeypatch, tmp_path / "pic.tiff")
    shown = _desc(win)
    win._go_to_id("levels"); qtbot.wait(20)
    win._go_to_id("export"); qtbot.wait(20)
    assert _desc(win) == shown


def test_a_new_image_clears_it(qtbot, tmp_path, monkeypatch):
    """Captured and asserted UNCHANGED from a fresh window's Export step: an
    old file must never be announced over new work."""
    win = _at_export(qtbot, tmp_path)
    fresh = _desc(win)
    _export(win, monkeypatch, tmp_path / "pic.tiff")
    assert _desc(win) != fresh, "fixture"
    other = tmp_path / "other"; other.mkdir()
    win.open_fits(_make_fits(other))
    win._go_to_id("export"); qtbot.wait(20)
    assert _desc(win) == fresh


def test_a_name_is_text_not_markup(qtbot, tmp_path, monkeypatch):
    win = _at_export(qtbot, tmp_path)
    _export(win, monkeypatch, tmp_path / "a<b>c.tiff")
    assert "a<b>c.tiff" in _desc(win).replace("&lt;", "<").replace("&gt;", ">")
    assert "&lt;b&gt;" in win._panel.desc_box.text()


def test_a_long_name_stays_on_one_line_at_1280x800(qtbot, tmp_path, monkeypatch):
    """Under the real stylesheet: the box is two lines tall and the first is
    the description. Middle-elided, so the extension is still readable — and
    Export's pinned area must not grow."""
    from PySide6.QtWidgets import QApplication, QLabel
    from tests.ui.test_stable_frame import _settle, _themed_window
    app = QApplication.instance()
    before = app.styleSheet()
    try:
        win = _themed_window(qtbot, tmp_path, (1280, 800))
        win._go_to_id("export", user_initiated=False); _settle(qtbot)
        d = win._panel.desc_box
        box_h, scroll_h = d.height(), win._side.scroll.height()
        long = "IC1805_drizzle_331x10s_55min_final_version_with_extra_stars_v7.tiff"
        _export(win, monkeypatch, tmp_path / long)
        _settle(qtbot)
        # And after a rebuild: the text is then set on a box not yet laid out
        # (640 px wide, unstyled font) — the review found the name unelided
        # there, wrapping the link out of the box (2026-10-04).
        win._go_to_id("levels", user_initiated=False); _settle(qtbot)
        win._go_to_id("export", user_initiated=False); _settle(qtbot)
        d = win._panel.desc_box
        line = _desc(win).splitlines()[1]
        assert "…" in line and line.split(" · ")[0].endswith(".tiff"), line
        free = QLabel(d.text()); free.setObjectName("stepDesc"); free.setWordWrap(True)
        free.setParent(d.parentWidget()); free.hide(); free.ensurePolished()
        assert free.heightForWidth(d.width()) <= d.height(), "a third line would be clipped"
        assert (d.height(), win._side.scroll.height()) == (box_h, scroll_h)
    finally:
        app.setStyleSheet(before)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_reveal_uses_the_platforms_own_file_manager(qtbot, tmp_path, monkeypatch, platform):
    import subprocess
    import sys
    from PySide6.QtGui import QDesktopServices
    win = _window(qtbot, tmp_path)
    target = tmp_path / "pic.tiff"
    target.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **k: calls.append(("popen", args)))
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: calls.append(("url", url.toLocalFile()))))
    win._reveal_in_file_manager(str(target))
    if platform == "darwin":
        assert calls == [("popen", ["open", "-R", str(target)])]
    else:
        assert calls == [("url", str(tmp_path))]
