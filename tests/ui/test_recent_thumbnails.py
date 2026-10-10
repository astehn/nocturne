"""The start page shows the last projects as thumbnails (Andreas,
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
    from nocturne.ui.welcome import CARD_W, CARD_H, _CARD_BG
    with_preview = _card_pixmap(read_preview(path), 1.0).toImage()
    placeholder = _card_pixmap(None, 1.0).toImage()
    assert with_preview.size() == placeholder.size()
    # The picture fills the middle of the card; the ground shows only around it.
    centre = with_preview.pixelColor(CARD_W // 2, CARD_H // 2)
    assert centre != _CARD_BG and centre != placeholder.pixelColor(CARD_W // 2, CARD_H // 2)
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [path])
    qtbot.addWidget(w)
    assert len(w.recent_buttons) == 1 and w.recent_buttons[0].text() == "M 31"
    card = w.recent_buttons[0].picture.toImage()
    assert card.pixelColor(CARD_W // 2, CARD_H // 2) == centre, "the card draws the preview"


def test_the_cards_fit_the_smallest_window(qtbot, tmp_path):
    """MIN_WINDOW is 1120 x 650; the start page there is about 1100 x 550 —
    one row of three."""
    files = []
    for i in range(6):
        p = tmp_path / f"a much longer project name than usual {i}.nocturne"
        p.write_text("x")
        files.append(str(p))
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: files)
    qtbot.addWidget(w)
    w.resize(1100, 550)
    w.show()
    qtbot.waitExposed(w)
    shown = [b for b in w.recent_buttons if b.isVisible()]
    assert len(shown) == 3
    for b in shown:
        top_left = b.mapTo(w, b.rect().topLeft())
        assert top_left.x() >= 0 and top_left.x() + b.width() <= 1100, "inside the width"
        assert top_left.y() >= 0 and top_left.y() + b.height() <= 550, "inside the height"
    bottom = w.update_note.mapTo(w, w.update_note.rect().bottomLeft()).y()
    assert bottom <= 550, "and the rows under the buttons too"
    assert len({b.height() for b in w.recent_buttons}) == 1, "a long name does not make a taller card"


def test_nothing_but_the_cards_is_drawn_in_the_row(qtbot, tmp_path):
    """The card used to measure the row was parented to it and drawn as a
    stray box above the first card."""
    from PySide6.QtWidgets import QAbstractButton
    p = tmp_path / "a.nocturne"
    p.write_text("x")
    w = WelcomeScreen(lambda: None, lambda: None, recent=lambda: [str(p)])
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    shown = [b for b in w._head.findChildren(QAbstractButton) if b.isVisible()]
    assert shown == w.recent_buttons


def test_a_preview_that_fails_never_fails_the_save(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw

    def boom(*a, **k):
        raise RuntimeError("no preview today")
    monkeypatch.setattr(mw, "jpeg_bytes", boom)
    win, path = _saved_by_the_app(qtbot, tmp_path, monkeypatch)
    assert read_preview(path) is None
    assert [n for n, _ in load_project(path, str(tmp_path / "c")).project.entries()] == ["Stretch"]


def test_the_preview_is_drawn_from_a_small_copy(qtbot, tmp_path):
    """Stretching the whole frame first cost ~2.9 GB extra on a 33 MP save."""
    from nocturne.core.image import AstroImage
    from nocturne.ui.main_window import PREVIEW_EDGE, _preview_source
    big = AstroImage(np.zeros((4320, 7680, 3), np.float32), is_linear=True, metadata={})
    src = _preview_source(big)
    assert max(src.data.shape[:2]) <= 4 * PREVIEW_EDGE and src.is_linear
    small = AstroImage(np.zeros((300, 400, 3), np.float32), is_linear=False, metadata={})
    assert _preview_source(small) is small


def test_a_hidden_start_page_is_not_rebuilt_after_every_step(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert not win._welcome.isVisible()
    calls = []
    win._welcome.refresh_recent = lambda: calls.append(1)
    win._set_busy(True)
    win._set_busy(False)
    assert calls == []
