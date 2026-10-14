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
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", gallery_ready=True)
    assert p.gallery_btn.text() == "Share to the gallery…"
    assert not p.gallery_btn.icon().isNull(), "the upload icon"
    assert p.gallery_hint.text() == "Your exported picture in the public gallery."


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
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", gallery_ready=True)
    p.show()
    p.gallery_btn.click()
    qtbot.waitUntil(p.gallery_dialog.isVisible, timeout=2000)
    p.gallery_dialog.cancel_btn.click()
    qtbot.waitUntil(lambda: not p.gallery_dialog.isVisible(), timeout=2000)


def test_a_spent_send_stays_spent_across_a_reopen(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", on_wall_submit=lambda t: None,
               gallery_ready=True)
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
    assert p.save_preset_hint.text() == "Saves the steps for similar pictures — not this picture."
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


# --- fix round 1 (adversarial review 2026-10-14) ---------------------------------------

def _export_win(qtbot, tmp_path, stretched=True):
    from tests.ui.test_main_window import _make_fits, _window
    win = _window(qtbot, tmp_path)
    win.settings.handle = "@tester"
    win.open_fits(_make_fits(tmp_path))
    if stretched:
        win._go_to_id("stretch", user_initiated=False)
        win._panel.apply_btn.click()
    win._go_to_id("export", user_initiated=False)
    return win


def _held_submit(monkeypatch):
    """Replace the network send with one that waits to be released."""
    import threading
    gate, answer = threading.Event(), {}
    def fake(*a, **k):
        gate.wait(5)
        return answer.get("r", (True, "Sent. It will appear once it has been looked at."))
    monkeypatch.setattr("nocturne.core.submit.submit", fake)
    return gate, answer


def test_a_rebuild_mid_send_cannot_send_twice_and_the_answer_lands(qtbot, tmp_path, monkeypatch):
    """A plate solve landing (or any _rebuild_panel) mid-send built a fresh
    panel with Send live again, and the answer then wrote to a deleted one."""
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    gate, _ = _held_submit(monkeypatch)
    old = win._panel
    old.wall_consent.setChecked(True)
    old.wall_btn.click()
    win._rebuild_panel(); qtbot.wait(20)
    new = win._panel
    assert new is not old
    new.wall_consent.setChecked(True)
    assert not new.wall_btn.isEnabled(), "Send came back on the rebuilt panel mid-send"
    assert new.gallery_hint.text() == "Sending…"
    gate.set()
    qtbot.waitUntil(lambda: "looked at" in new.gallery_hint.text(), timeout=4000)
    assert "looked at" in new.wall_note.text()
    assert not new.wall_btn.isEnabled() and not new.wall_consent.isEnabled(), "spent"
    win._rebuild_panel()
    p = win._panel
    p.wall_consent.setChecked(True)
    assert not p.wall_btn.isEnabled(), "a sent picture is spent across rebuilds"
    assert "looked at" in p.gallery_hint.text()


def test_a_failed_send_survives_a_rebuild_and_can_be_retried(qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    gate, answer = _held_submit(monkeypatch)
    answer["r"] = (False, "Could not reach the gallery: timed out")
    win._panel.wall_consent.setChecked(True)
    win._panel.wall_btn.click()
    gate.set()
    qtbot.waitUntil(lambda: "Could not" in win._panel.gallery_hint.text(), timeout=4000)
    win._rebuild_panel()
    p = win._panel
    assert "Could not" in p.gallery_hint.text()
    p.wall_consent.setChecked(True)
    assert p.wall_btn.isEnabled(), "a failure must leave the retry"


def test_the_send_state_belongs_to_one_picture(qtbot, tmp_path, monkeypatch):
    from tests.ui.test_main_window import _make_fits
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    gate, _ = _held_submit(monkeypatch)
    win._panel.wall_consent.setChecked(True)
    win._panel.wall_btn.click()
    win._dirty = False
    (tmp_path / "b").mkdir()
    gen = win._project_gen
    win.open_fits(_make_fits(tmp_path / "b"))    # a new picture while the old one sends
    qtbot.waitUntil(lambda: win._project_gen != gen, timeout=4000)   # opened, THEN it lands
    gate.set(); qtbot.wait(300)
    win._go_to_id("export", user_initiated=False)
    p = win._panel
    p.wall_consent.setChecked(True)
    assert p.wall_btn.isEnabled(), "the old picture's send spent the new one"
    assert "looked at" not in p.gallery_hint.text()


def test_the_panel_line_says_sending_while_in_flight(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", on_wall_submit=lambda t: None)
    p.wall_consent.setChecked(True)
    p.wall_btn.click()
    assert p.gallery_hint.text() == "Sending…"


def test_the_dialog_does_not_repeat_its_title(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    assert p.gallery_dialog.windowTitle() == "Share to the gallery"
    assert "Share to the gallery" not in [l.text() for l in p.gallery_dialog.findChildren(QLabel)]


@pytest.mark.parametrize("why", ["linear", "empty", "ok"])
def test_the_preset_tooltip_gives_the_real_reason_on_export(qtbot, tmp_path, why):
    from nocturne.ui import main_window as mw
    if why == "empty":
        from tests.ui.test_main_window import _window
        from tests.ui.test_open_tiff import _write_stretched_tiff
        win = _window(qtbot, tmp_path)
        win.open_any(_write_stretched_tiff(tmp_path))
        win._go_to_id("export", user_initiated=False)
    else:
        win = _export_win(qtbot, tmp_path, stretched=(why == "ok"))
    assert win.current_stage_id() == "export"
    btn = win._panel.save_preset_btn
    want = {"linear": mw._PRESET_TIP_LINEAR, "empty": mw._PRESET_TIP_EMPTY,
            "ok": mw._PRESET_TIP_ON}[why]
    assert btn.toolTip() == want and win._save_preset_act.toolTip() == want
    assert btn.isEnabled() is (why == "ok")
    if why == "linear":
        assert "Stretch the picture first" in want and "Enhancements" not in want


def test_before_enhancements_the_menu_item_keeps_its_text(qtbot, tmp_path):
    from nocturne.ui import main_window as mw
    win = _export_win(qtbot, tmp_path)
    win._go_to_id("levels", user_initiated=False)
    assert win._save_preset_act.toolTip() == mw._PRESET_TIP_OFF


def test_the_empty_preset_browser_points_at_export():
    from nocturne.ui.preset_browser import _EMPTY
    assert _EMPTY == ("Process a picture through to Export, then press Save as Preset… "
                      "(or use the Project menu).")


# --- fix round 2: "sent" belongs to the exact version that was sent ------------------

def _send_and_land(qtbot, win, monkeypatch):
    gate, _ = _held_submit(monkeypatch)
    win._panel.wall_consent.setChecked(True)
    win._panel.wall_btn.click()
    gate.set()
    qtbot.waitUntil(lambda: "looked at" in win._panel.gallery_hint.text(), timeout=4000)


def _edit(win):
    """Change the picture: a real Enhancements tap, a new history state."""
    win._go_to_id("enhancements", user_initiated=False)
    win._enhance("Vibrance")
    win._go_to_id("export", user_initiated=False)


def test_an_edited_picture_can_be_sent_again(qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    _send_and_land(qtbot, win, monkeypatch)
    win._async_enabled = False
    before = win.project.state_token(win.project.position)
    _edit(win)
    assert win.project.state_token(win.project.position) != before, "fixture: no edit"
    p = win._panel
    p.wall_consent.setChecked(True)
    assert p.wall_btn.isEnabled(), "the changed version must be sendable"
    assert "looked at" not in p.gallery_hint.text()


def test_undoing_back_to_the_sent_version_is_spent_again(qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    _send_and_land(qtbot, win, monkeypatch)
    win._async_enabled = False
    _edit(win)
    win.project.undo(); win._refresh(); win._rebuild_panel()
    p = win._panel
    p.wall_consent.setChecked(True)
    assert not p.wall_btn.isEnabled(), "this exact version has been sent"


def test_a_send_landing_after_an_edit_does_not_spend_the_new_version(
        qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    win._async_enabled = True
    gate, _ = _held_submit(monkeypatch)
    win._panel.wall_consent.setChecked(True)
    win._panel.wall_btn.click()
    win._async_enabled = False
    _edit(win)
    gate.set(); qtbot.wait(300)
    p = win._panel
    p.wall_consent.setChecked(True)
    assert p.wall_btn.isEnabled(), "the old version's send spent the new one"


def test_busy_sweeps_the_gallery_dialog_but_not_its_cancel(qtbot, tmp_path, monkeypatch):
    """The busy gate's rule — no panel button can START work mid-job — covers
    the dialog: Send (live before, consent ticked) goes off and comes back.
    Cancel only closes the window, so it stays live (keep_live)."""
    win = _export_win(qtbot, tmp_path)
    _do_export(qtbot, win, monkeypatch, tmp_path)        # Share waits for an export
    p = win._panel
    p.wall_consent.setChecked(True)
    assert p.wall_btn.isEnabled(), "fixture: Send live before the job"
    win._set_busy(True, "Working…")
    assert not p.wall_btn.isEnabled() and not p.wall_consent.isEnabled()
    assert not p.gallery_btn.isEnabled()
    assert p.gallery_dialog.cancel_btn.isEnabled()
    win._set_busy(False)
    assert p.wall_btn.isEnabled() and p.gallery_btn.isEnabled()


# --- C2 (owner's choice after testing B1, 2026-10-14) -------------------------------------

OPTIONAL_HEADING = "OPTIONAL — DOESN'T SAVE YOUR PICTURE"


def test_one_heading_over_both_extras(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    assert p.optional_heading.text() == OPTIONAL_HEADING
    assert p.optional_heading.objectName() == "panelSectionLabel"
    p.resize(360, 900); p.show(); qtbot.waitExposed(p)
    ys = [w.mapTo(p, w.rect().topLeft()).y() for w in (
        p.space_note, p.optional_heading, p.gallery_btn, p.gallery_hint,
        p.save_preset_btn, p.save_preset_hint)]
    assert ys == sorted(ys) and len(set(ys)) == len(ys), ys


def test_the_heading_stands_over_the_preset_alone_without_a_gallery(qtbot):
    p = _panel(qtbot)
    assert p.optional_heading.text() == OPTIONAL_HEADING


def test_the_preset_line_says_it_does_not_save_the_picture(qtbot):
    p = _panel(qtbot)
    assert p.save_preset_hint.text() == "Saves the steps for similar pictures — not this picture."


def test_share_is_off_until_exported_at_the_panel(qtbot):
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    assert not p.gallery_btn.isEnabled()
    assert p.gallery_hint.text() == "Available after you export."
    assert "export" in p.gallery_btn.toolTip().lower()
    p2 = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a", gallery_ready=True)
    assert p2.gallery_btn.isEnabled()
    assert p2.gallery_hint.text() == "Your exported picture in the public gallery."


def test_the_dialog_links_to_the_gallery(qtbot, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString())))
    p = _panel(qtbot, wall_fields=dict(FACTS), wall_handle="@a")
    link = p.gallery_dialog.gallery_link
    assert "See the gallery ↗" in link.text()
    assert "text-decoration:none" in link.text(), "the How-this-works link style"
    link.linkActivated.emit("https://nocturneastro.com/gallery.html")
    assert opened == ["https://nocturneastro.com/gallery.html"]


def _do_export(qtbot, win, monkeypatch, tmp_path, ok=True, cancel=False):
    from nocturne.ui import file_dialogs
    out = tmp_path / "out.tiff"
    monkeypatch.setattr(file_dialogs, "save_file",
                        staticmethod(lambda *a, **k: ("" if cancel else str(out), "")))
    if not ok:
        from nocturne.ui import main_window as mw
        def boom(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(mw, "save_tiff", boom)
    win._panel.export_btn.click()
    qtbot.wait(50)


def test_share_wakes_after_an_export_and_sleeps_after_an_edit(qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    p = win._panel
    assert not p.gallery_btn.isEnabled()
    assert p.gallery_hint.text() == "Available after you export."
    _do_export(qtbot, win, monkeypatch, tmp_path)
    p = win._panel
    assert p.gallery_btn.isEnabled(), "exported: Share is offered"
    assert p.gallery_hint.text() == "Your exported picture in the public gallery."
    assert "out.tiff" in p.desc_box.text(), "the export-done line stays"
    win._rebuild_panel()
    assert win._panel.gallery_btn.isEnabled(), "same version, still exported"
    _edit(win)
    p = win._panel
    assert not p.gallery_btn.isEnabled(), "a changed picture needs a new export"
    assert p.gallery_hint.text() == "Available after you export."


@pytest.mark.parametrize("how", ["failed", "cancelled"])
def test_a_failed_or_cancelled_export_does_not_wake_share(qtbot, tmp_path, monkeypatch, how):
    win = _export_win(qtbot, tmp_path)
    _do_export(qtbot, win, monkeypatch, tmp_path, ok=(how != "failed"), cancel=(how == "cancelled"))
    win._sync_step_controls(); win._rebuild_panel()     # read back from the record itself
    assert not win._panel.gallery_btn.isEnabled()
    assert win._panel.gallery_hint.text() == "Available after you export."


def test_share_is_still_swept_while_busy_once_exported(qtbot, tmp_path, monkeypatch):
    win = _export_win(qtbot, tmp_path)
    _do_export(qtbot, win, monkeypatch, tmp_path)
    p = win._panel
    assert p.gallery_btn.isEnabled()
    win._set_busy(True, "Working…")
    assert not p.gallery_btn.isEnabled()
    win._refresh()
    assert not win._panel.gallery_btn.isEnabled(), "a refresh mid-job relit it"
    win._set_busy(False)
    assert win._panel.gallery_btn.isEnabled()
