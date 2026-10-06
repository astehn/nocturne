"""Drag a project or an image onto the window and it opens (Andreas,
2026-10-06: "i have myself on several occasions actually tried to drag at least
images into nocturne with no luck")."""
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from nocturne.ui.file_drop import dropped_file
from tests.ui.test_main_window import _make_fits, _window


def _mime(*paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def _enter(win, mime):
    ev = QDragEnterEvent(QPoint(200, 200), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win, ev)
    return ev


def _drop(win, mime):
    ev = QDropEvent(QPointF(200, 200), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win, ev)
    return ev


# --- which files ---------------------------------------------------------------
def test_one_project_or_one_image_is_accepted(tmp_path):
    files = {}
    for name in ("a.nocturne", "b.fits", "c.FIT", "d.fts", "e.tif", "f.TIFF", "g.jpg", "h.png"):
        p = tmp_path / name
        p.write_text("x")
        files[name] = p
    assert dropped_file(_mime(files["a.nocturne"])) == ("project", str(files["a.nocturne"]))
    for n in ("b.fits", "c.FIT", "d.fts", "e.tif", "f.TIFF"):
        assert dropped_file(_mime(files[n]))[0] == "image", n
    assert dropped_file(_mime(files["g.jpg"])) is None
    assert dropped_file(_mime(files["h.png"])) is None
    assert dropped_file(_mime(files["b.fits"], files["e.tif"])) is None, "two files: refused"
    assert dropped_file(_mime(tmp_path)) is None, "a folder: refused"
    assert dropped_file(_mime(tmp_path / "gone.fits")) is None
    web = QMimeData()
    web.setUrls([QUrl("https://example.com/x.fits")])
    assert dropped_file(web) is None, "not a local file"
    text = QMimeData()
    text.setText("/tmp/x.fits")
    assert dropped_file(text) is None


# --- the window ----------------------------------------------------------------
def test_an_image_dropped_on_the_start_page_opens(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    fits = _make_fits(tmp_path)
    ev = _enter(win, _mime(fits))
    assert ev.isAccepted() and win._drop_overlay.isVisibleTo(win)
    assert "Drop to open this image" in win._drop_overlay.text()
    _drop(win, _mime(fits))
    assert not win._drop_overlay.isVisibleTo(win)
    assert win.project is not None and win.current_stage_id() == "load"


def test_a_project_dropped_opens_through_the_project_door(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    p = tmp_path / "m.nocturne"
    p.write_text("x")
    opened = []
    monkeypatch.setattr(win, "_open_project", lambda path=None: opened.append(path))
    _enter(win, _mime(p))
    assert "Drop to open this project" in win._drop_overlay.text()
    _drop(win, _mime(p))
    assert opened == [str(p)]


def test_an_image_dropped_mid_edit_asks_first(qtbot, tmp_path, monkeypatch):
    """The menu's unsaved-changes question comes with the drop."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    asked = []
    monkeypatch.setattr(win, "_confirm_save_if_dirty", lambda: asked.append(1) or False)
    before = win.project
    (tmp_path / "b").mkdir()
    other = _mime(_make_fits(tmp_path / "b"))
    _enter(win, other)
    _drop(win, other)
    assert asked and win.project is before, "cancelled: the picture stays"


def test_refused_drops_do_nothing(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    jpg = tmp_path / "x.jpg"
    jpg.write_text("x")
    calls = []
    monkeypatch.setattr(win, "open_any", lambda p: calls.append(p))
    ev = _enter(win, _mime(jpg))
    assert not ev.isAccepted() and not win._drop_overlay.isVisibleTo(win)
    _drop(win, _mime(jpg))
    assert calls == []


def test_nothing_is_dropped_while_work_runs(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    fits = _make_fits(tmp_path)
    calls = []
    monkeypatch.setattr(win, "open_any", lambda p: calls.append(p))
    win._set_busy(True)
    ev = _enter(win, _mime(fits))
    assert not ev.isAccepted()
    _drop(win, _mime(fits))
    win._set_busy(False)
    assert calls == []


def test_leaving_the_window_hides_the_overlay(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    _enter(win, _mime(_make_fits(tmp_path)))
    assert win._drop_overlay.isVisibleTo(win)
    QApplication.sendEvent(win, QDragLeaveEvent())
    assert not win._drop_overlay.isVisibleTo(win)


def test_the_picture_hands_drops_on_to_the_window(qtbot, tmp_path):
    """A QGraphicsView accepts drops by default and would swallow a file
    dragged over the image before the window saw it."""
    win = _window(qtbot, tmp_path)
    assert win.acceptDrops()
    assert not win.image_view.acceptDrops()
    assert not win.image_view.viewport().acceptDrops()
