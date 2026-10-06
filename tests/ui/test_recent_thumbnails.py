"""The start page shows the last four projects as thumbnails (Andreas,
2026-10-06). The thumbnail is a small JPEG saved inside the project, so the
page never reads the images; projects saved before have a placeholder."""
import zipfile

import numpy as np
from PySide6.QtGui import QImage

from nocturne.history.project_store import PREVIEW_NAME, load_project, read_preview, save_project
from nocturne.ui.welcome import WelcomeScreen, _card_pixmap
from tests.ui.test_main_window import _make_fits, _window


def _saved_by_the_app(qtbot, tmp_path, monkeypatch, name="M 31.nocturne"):
    from nocturne.ui import file_dialogs
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    out = str(tmp_path / name)
    monkeypatch.setattr(file_dialogs, "save_file", lambda *a, **k: (out, ""))
    win._save_project_as()
    return win, out


def test_saving_stores_a_small_preview_of_the_picture(qtbot, tmp_path, monkeypatch):
    win, path = _saved_by_the_app(qtbot, tmp_path, monkeypatch)
    jpeg = read_preview(path)
    assert jpeg and jpeg[:2] == b"\xff\xd8", "a JPEG"
    img = QImage.fromData(jpeg)
    assert not img.isNull() and max(img.width(), img.height()) <= 480
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(PREVIEW_NAME)
        assert info.compress_type == zipfile.ZIP_STORED
    # ...and the project still opens, the preview simply carried along.
    loaded = load_project(path, str(tmp_path / "cache"))
    assert [n for n, _ in loaded.project.entries()] == ["Stretch"]


def test_a_project_saved_before_thumbnails_has_none(qtbot, tmp_path):
    from nocturne.history.project import Project
    from nocturne.core.image import AstroImage
    proj = Project(AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True, metadata={}),
                   str(tmp_path / "c"))
    path = str(tmp_path / "old.nocturne")
    save_project(proj, path)
    assert read_preview(path) is None


def test_a_broken_file_does_not_break_the_start_page(tmp_path):
    p = tmp_path / "broken.nocturne"
    p.write_bytes(b"not a zip at all")
    assert read_preview(str(p)) is None
    assert read_preview(str(tmp_path / "gone.nocturne")) is None


def test_the_card_shows_the_preview_and_old_projects_the_crescent(qtbot, tmp_path, monkeypatch):
    win, path = _saved_by_the_app(qtbot, tmp_path, monkeypatch)
    with_preview = _card_pixmap(read_preview(path), 1.0).toImage()
    placeholder = _card_pixmap(None, 1.0).toImage()
    assert with_preview.size() == placeholder.size()
    assert with_preview != placeholder, "a saved picture is not the placeholder"
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [path])
    qtbot.addWidget(w)
    assert len(w.recent_buttons) == 1 and w.recent_buttons[0].text() == "M 31"
    assert not w.recent_buttons[0].icon().isNull()


def test_four_cards_fit_the_smallest_window(qtbot, tmp_path):
    """MIN_WINDOW is 1120 x 650; the start page there is about 1100 x 550."""
    files = []
    for i in range(4):
        p = tmp_path / f"a much longer project name than usual {i}.nocturne"
        p.write_text("x")
        files.append(str(p))
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: files)
    qtbot.addWidget(w)
    w.resize(1100, 550)
    w.show()
    qtbot.waitExposed(w)
    for b in w.recent_buttons:
        r = b.geometry()
        top_left = b.mapTo(w, r.topLeft() - r.topLeft())
        assert top_left.x() >= 0 and top_left.x() + b.width() <= 1100, "inside the width"
        assert top_left.y() + b.height() <= 550, "inside the height"
    assert len({b.height() for b in w.recent_buttons}) == 1, "a long name does not make a taller card"


def test_nothing_but_the_cards_is_drawn_in_the_row(qtbot, tmp_path):
    """The card used to measure the row was parented to it and drawn as a
    stray box above the first card."""
    from PySide6.QtWidgets import QToolButton
    p = tmp_path / "a.nocturne"
    p.write_text("x")
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [str(p)])
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    shown = [b for b in w._recent_area.findChildren(QToolButton) if b.isVisible()]
    assert shown == w.recent_buttons
