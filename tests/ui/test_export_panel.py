"""The Export panel as redesigned on 2026-10-14 (spec 2026-10-14-export-redesign, "B1").

Format and colour space are buttons, as everywhere else in the app; the notes
appear only when they say something; the gallery moves behind its own button;
Save as Preset… moves here from Enhancements. What reaches `on_export` must not
change by a single character — recipes, Batch and the exporter read the same
strings they always did.
"""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog, QLabel, QPushButton  # noqa: E402

from nocturne.core.colour import EIGHT_BIT_SPACES, SPACES  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402
from nocturne.ui.step_panels import EXPORT_FORMATS, SIXTEEN_BIT_FORMATS, build_panel  # noqa: E402

FACTS = {"handle": "@andreasstehn", "target": "NGC 7000", "frames": "163",
         "sub_s": "20.00", "instrument": "ZWO Seestar S30 Pro",
         "captured_on": "2026-08-09"}


def _stage(sid="export"):
    return next(s for s in path_stages() if s.id == sid)


def _panel(qtbot, **kw):
    p = build_panel(_stage(), **kw)
    qtbot.addWidget(p)
    return p


# --- format tiles -------------------------------------------------------------

def test_the_format_tiles_are_the_four_formats_in_order(qtbot):
    p = _panel(qtbot)
    assert [p.format_box.itemText(i) for i in range(p.format_box.count())] == EXPORT_FORMATS
    assert [b.text() for b in p.format_box.buttons()] == ["TIFF", "PNG", "FITS", "Layers"]
    assert [b.sub for b in p.format_box.buttons()] == [
        "16-bit", "8-bit", "data", "starless + stars"]
    assert p.format_box.currentText() == "TIFF (16-bit)", "today's default"


def test_the_format_tiles_are_one_exclusive_choice(qtbot):
    p = _panel(qtbot)
    tiles = p.format_box.buttons()
    tiles[1].click()
    assert [t.isChecked() for t in tiles] == [False, True, False, False]
    tiles[1].click()                          # a second press does not un-choose it
    assert p.format_box.currentText() == "PNG"


@pytest.mark.parametrize("i,fmt", list(enumerate(EXPORT_FORMATS)))
def test_each_tile_hands_on_export_exactly_todays_string(qtbot, i, fmt):
    """Assert-unchanged: the strings `export_final` matches on, letter for
    letter, captured from EXPORT_FORMATS before the redesign."""
    got = []
    p = _panel(qtbot, on_export=lambda f, s: got.append((f, s)))
    p.format_box.buttons()[i].click()
    p.export_btn.click()
    assert got == [(fmt, "sRGB")]
    assert fmt == ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"][i]


# --- colour space -------------------------------------------------------------

def test_the_space_buttons_carry_todays_space_names(qtbot):
    p = _panel(qtbot)
    assert [p.space_box.itemText(i) for i in range(p.space_box.count())] == list(SPACES)
    assert [b.text() for b in p.space_box.buttons()] == ["sRGB", "P3", "Adobe RGB", "ProPhoto"]
    assert p.space_box.currentText() == "sRGB"


@pytest.mark.parametrize("i,space", list(enumerate(SPACES)))
def test_each_space_button_reaches_on_export_unchanged(qtbot, i, space):
    got = []
    p = _panel(qtbot, on_export=lambda f, s: got.append((f, s)))
    p.space_box.buttons()[i].click()
    p.export_btn.click()
    assert got == [("TIFF (16-bit)", space)]


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_wide_spaces_follow_todays_rule_on_every_format(qtbot, fmt):
    """Identical to _restrict_space before the redesign: wide only for a 16-bit
    format, and a wide choice pulled back to sRGB, not just greyed."""
    p = _panel(qtbot)
    p.space_box.setCurrentText("ProPhoto RGB")
    p.format_box.setCurrentText(fmt)
    wide_ok = fmt in SIXTEEN_BIT_FORMATS
    assert [b.isEnabled() for b in p.space_box.buttons()] == [
        wide_ok or s in EIGHT_BIT_SPACES for s in SPACES]
    assert p.space_box.currentText() == ("ProPhoto RGB" if wide_ok else "sRGB")


def test_pressing_a_greyed_space_cannot_choose_it(qtbot):
    got = []
    p = _panel(qtbot, on_export=lambda f, s: got.append((f, s)))
    p.format_box.setCurrentText("PNG")
    p.space_box.buttons()[2].click()          # disabled: click() is a no-op
    p.export_btn.click()
    assert got == [("PNG", "sRGB")]


def test_the_space_note_is_the_short_one(qtbot):
    p = _panel(qtbot)
    assert p.space_note.text() == ("Tagged, so other programs show it as you see it "
                                   "here. Wider spaces for 16-bit TIFF only.")


# --- notes that appear only when they matter ------------------------------------

def test_burn_annotations_is_hidden_until_main_window_shows_it(qtbot):
    p = _panel(qtbot)
    assert not p.burn_annotations.isVisibleTo(p)
    assert p.burn_annotations.text() == "Burn annotations (PNG)"


def test_the_star_split_note_shows_only_for_layers_without_a_tool(qtbot):
    p = _panel(qtbot, split_enabled=False)
    assert "built-in star split" in p.split_note.text()
    assert not p.split_note.isVisibleTo(p), "TIFF chosen: nothing to say"
    p.format_box.setCurrentText("Starless + Stars (two TIFFs)")
    assert p.split_note.isVisibleTo(p)
    p.format_box.setCurrentText("PNG")
    assert not p.split_note.isVisibleTo(p)


def test_no_star_split_note_with_a_tool_set_up(qtbot):
    p = _panel(qtbot, split_enabled=True)
    p.format_box.setCurrentText("Starless + Stars (two TIFFs)")
    shown = " ".join(l.text() for l in p.findChildren(QLabel) if l.isVisibleTo(p))
    assert "built-in star split" not in shown


# --- the gallery, behind its own button -----------------------------------------

def test_no_gallery_button_without_gallery_fields(qtbot):
    p = _panel(qtbot)
    assert p.gallery_btn is None and p.gallery_dialog is None


def test_the_gallery_button_and_its_line(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    assert p.gallery_btn.text() == "Share to the gallery…"
    assert not p.gallery_btn.icon().isNull(), "the upload icon"
    assert p.gallery_hint.text() == ("Optional — your picture in the public gallery "
                                     "at nocturneastro.com.")


def test_the_gallery_block_lives_in_the_dialog_not_the_panel(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    assert isinstance(p.gallery_dialog, QDialog)
    for w in (p.wall_consent, p.wall_btn, p.wall_note):
        assert p.gallery_dialog.isAncestorOf(w)
    assert not p.gallery_dialog.isVisible()
    words = " ".join(l.text() for l in p.gallery_dialog.findChildren(QLabel))
    assert "looked at before it appears" in words
    assert "The gallery will show: NGC 7000" in words


def test_the_button_opens_the_dialog_and_cancel_closes_it(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    p.show()
    p.gallery_btn.click()
    qtbot.waitUntil(p.gallery_dialog.isVisible, timeout=2000)
    p.gallery_dialog.cancel_btn.click()
    qtbot.waitUntil(lambda: not p.gallery_dialog.isVisible(), timeout=2000)


def test_a_spent_send_stays_spent_across_a_reopen(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", on_wall_submit=lambda t: None)
    p.show()
    p.gallery_btn.click()
    p.wall_consent.setChecked(True)
    p.wall_btn.click()
    p.wall_finished(True, "Sent. It will appear once it has been looked at.")
    p.gallery_dialog.cancel_btn.click()
    p.gallery_btn.click()
    qtbot.waitUntil(p.gallery_dialog.isVisible, timeout=2000)
    assert not p.wall_btn.isEnabled() and not p.wall_consent.isEnabled()
    assert "looked at" in p.wall_note.text()
    p.gallery_dialog.cancel_btn.click()


def test_the_outcome_also_reaches_the_panel_line(qtbot):
    """The dialog can be closed while a send is in flight; its answer must
    still land somewhere the user can read it."""
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", on_wall_submit=lambda t: None)
    p.wall_consent.setChecked(True)
    p.wall_btn.click()
    p.wall_finished(False, "Could not reach the gallery: timed out")
    assert p.gallery_hint.text() == "Could not reach the gallery: timed out"


# --- Save as Preset… ---------------------------------------------------------------

def test_save_as_preset_is_on_export_with_its_line(qtbot):
    got = []
    p = _panel(qtbot, on_save_preset=lambda: got.append(1))
    assert p.save_preset_btn.text() == "Save as Preset…"
    assert not p.save_preset_btn.icon().isNull(), "the bookmark icon"
    assert p.save_preset_hint.text() == "Keep this look for similar pictures."
    assert not p.save_preset_btn.isEnabled(), "MainWindow gates it"
    p.save_preset_btn.setEnabled(True)
    p.save_preset_btn.click()
    assert got == [1]


def test_save_as_preset_is_no_longer_on_enhancements(qtbot):
    p = build_panel(_stage("enhancements"))
    qtbot.addWidget(p)
    assert getattr(p, "save_preset_btn", None) is None
    assert "Save as Preset…" not in [b.text() for b in p.findChildren(QPushButton)]


def test_the_order_top_to_bottom(qtbot):
    """B1: Format, Colour space, note, Burn, split note, gallery, preset."""
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", split_enabled=False)
    p.format_box.setCurrentText("Starless + Stars (two TIFFs)")
    p.burn_annotations.setVisible(True)
    p.resize(360, 900); p.show(); qtbot.waitExposed(p)
    seq = [p.format_box, p.space_box, p.space_note, p.burn_annotations, p.split_note,
           p.gallery_btn, p.gallery_hint, p.save_preset_btn, p.save_preset_hint]
    ys = [w.mapTo(p, w.rect().topLeft()).y() for w in seq]
    assert ys == sorted(ys) and len(set(ys)) == len(ys), ys


# --- in the real window -------------------------------------------------------------

def _solve(win):
    from astropy.wcs import WCS
    from nocturne.tools.astap import SolveResult
    wc = WCS(naxis=2); wc.wcs.crpix = [12, 12]; wc.wcs.crval = [100.0, 0.0]
    wc.wcs.cd = [[-0.001, 0], [0, 0.001]]; wc.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    win._solve = (win._solve_sig(), SolveResult(True, wc, 100.0, 0.0, 3.6), [])


@pytest.mark.parametrize("solved", [False, True])
def test_burn_annotations_shows_only_with_a_plate_solve(qtbot, tmp_path, solved):
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    if solved:
        _solve(win)
    win._go_to_id("export", user_initiated=False)
    p = win._panel
    assert p.burn_annotations.isVisibleTo(p) is solved
    assert p.burn_annotations.isEnabled(), "shown means usable, as before"


def test_a_ticked_burn_still_reaches_the_png_export(qtbot, tmp_path, monkeypatch):
    """Same behaviour as before: the window reads the box at export time."""
    from nocturne.ui import file_dialogs
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _solve(win)
    win._go_to_id("export", user_initiated=False)
    burned = []
    monkeypatch.setattr(win, "_save_png_with_annotations",
                        lambda img, path, res: burned.append(path))
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: (str(tmp_path / "o.png"), "")))
    win._panel.burn_annotations.setChecked(True)
    win._panel.format_box.setCurrentText("PNG")
    win._panel.export_btn.click()
    qtbot.waitUntil(lambda: bool(burned), timeout=3000)


def test_the_export_button_reaches_export_final_with_todays_strings(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    got = []
    monkeypatch.setattr(win, "export_final", lambda f, s="sRGB": got.append((f, s)))
    win._go_to_id("export", user_initiated=False)
    p = win._panel
    p.format_box.buttons()[3].click()
    p.space_box.buttons()[1].click()
    p.export_btn.click()
    assert got == [("Starless + Stars (two TIFFs)", "Display P3")]
    assert win._export_space() == "Display P3"


@pytest.mark.parametrize("size", [(1280, 800), (1440, 900 - 30 - 28)])
def test_format_space_and_export_fit_without_scrolling(qtbot, tmp_path, size):
    """Spec: Format, Colour space and Export visible without scrolling at both
    sizes; the gallery and preset buttons may scroll at 1280x800. Real
    window, real stylesheet, gallery offered (a handle set)."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    from tests.ui.test_main_window import _make_fits, _window
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = _window(qtbot, tmp_path)
        win.settings.handle = "@tester"
        win.open_fits(_make_fits(tmp_path))
        win.resize(*size); win.show(); qtbot.waitExposed(win)
        win._go_to_id("export", user_initiated=False); qtbot.wait(80)
        p = win._panel
        assert p.gallery_btn is not None, "fixture: the gallery is offered"
        scroll = win._side.scroll
        assert scroll.verticalScrollBar().value() == 0
        view = scroll.viewport()
        for name, w in [("format", p.format_box), ("space", p.space_box)] + [
                (b.text(), b) for b in p.format_box.buttons() + p.space_box.buttons()]:
            assert w.isVisible(), name
            r = QRect(w.mapTo(view, w.rect().topLeft()), w.size())
            assert view.rect().contains(r), f"{name} at {r.getRect()} outside {view.height()} px"
            # The Crop fit test's 8 px allowance for Cocoa's fonts.
            assert r.bottom() <= view.height() - 8, f"{name} ends at {r.bottom()} px"
            assert w.mapTo(win._side, w.rect().topRight()).x() <= win._side.width(), name
        for b in p.format_box.buttons() + p.space_box.buttons():
            assert b.width() >= b.minimumSizeHint().width(), b.text()
        # Export is pinned in the action slot, outside the scroll.
        eb = p.export_btn
        assert eb.isVisible() and not scroll.isAncestorOf(eb)
        r = QRect(eb.mapTo(win, eb.rect().topLeft()), eb.size())
        assert win.rect().contains(r), f"Export at {r.getRect()}"
    finally:
        app.setStyleSheet(before)


def test_the_layers_sub_label_fits_its_tile(qtbot, tmp_path):
    """"starless + stars" is the longest second line; at the 1280x800 column
    it must not be cut by the tile's edge."""
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.format_tiles import IconTile
    from nocturne.ui.theme import build_stylesheet
    from tests.ui.test_main_window import _make_fits, _window
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = _window(qtbot, tmp_path)
        win.open_fits(_make_fits(tmp_path))
        win.resize(1280, 800); win.show(); qtbot.waitExposed(win)
        win._go_to_id("export", user_initiated=False); qtbot.wait(80)
        for t in win._panel.format_box.buttons():
            fm = QFontMetrics(IconTile.sub_font(t.font()))
            assert fm.horizontalAdvance(t.sub) <= t.width() - 4, (t.sub, t.width())
    finally:
        app.setStyleSheet(before)
