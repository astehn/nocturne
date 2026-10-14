"""Save as Preset… (user presets, Task 4): the gate, the dialog, what is stored."""
import pytest
pytest.importorskip("PySide6")
from tests.ui.test_main_window import _FakeTrim, _crop, _make_fits, _window


def _to(win, sid):
    win._go_to_id(sid, user_initiated=False)


def _stretch(win):
    win._go_to_id("stretch", user_initiated=False)
    win._panel.apply_btn.click()


@pytest.mark.parametrize("sid,ok", [("crop", False), ("stretch", False), ("levels", False),
                                    ("star_reduction", False), ("enhancements", True),
                                    ("export", True)])
def test_enabled_only_from_enhancements_on(qtbot, tmp_path, sid, ok):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win); _stretch(win)
    _to(win, sid)
    assert win.current_stage_id() == sid
    assert win._save_preset_act.isEnabled() is ok
    assert ("Enhancements first" in win._save_preset_act.toolTip()) is (not ok)
    btn = getattr(win._panel, "save_preset_btn", None)
    # On Export only since 2026-10-14: on Enhancements it read as an
    # Enhancements-only preset. The menu item serves both steps.
    assert (btn is not None) is (sid == "export"), "the button lives on Export only"
    if btn is not None:
        assert btn.isEnabled() is ok and btn.toolTip() == win._save_preset_act.toolTip()


def test_disabled_on_a_linear_picture_even_at_enhancements(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _to(win, "enhancements")                          # navigating there auto-stretches
    assert win._save_preset_act.isEnabled()
    win.project.undo()                                # the Stretch: linear again, same step
    win._refresh()
    assert win.current_stage_id() == "enhancements"
    assert win.project.is_linear_at(win.project.position)
    assert not win._save_preset_act.isEnabled()
    # The real reason: it is at the step, it is not stretched (review 2026-10-14).
    assert "Stretch the picture first" in win._save_preset_act.toolTip()
    _to(win, "export")                                # no auto-stretch on the way
    assert win.project.is_linear_at(win.project.position)
    assert not win._panel.save_preset_btn.isEnabled()
    assert win._panel.save_preset_btn.toolTip() == win._save_preset_act.toolTip()


def test_disabled_with_no_picture_and_while_busy(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert not win._save_preset_act.isEnabled()
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "export")
    assert win._save_preset_act.isEnabled()          # the precondition the busy check needs
    assert win._panel.save_preset_btn.isEnabled()
    win._set_busy(True, "x")
    assert not win._save_preset_act.isEnabled()
    assert not win._panel.save_preset_btn.isEnabled()
    win._refresh()                                    # a repaint mid-job must not relight it
    assert not win._panel.save_preset_btn.isEnabled()
    win._set_busy(False)
    assert win._save_preset_act.isEnabled()
    assert win._panel.save_preset_btn.isEnabled()


def _answer(monkeypatch, name="M 8", replace=True):
    import nocturne.ui.save_preset_dialog as spd
    seen = {}
    def fake_exec(self):
        seen["dlg"] = self
        self.name_edit.setText(name)
        def ask(n):
            seen["asked"] = n
            return replace
        self._ask_replace = ask
        self._on_save()
        return self.result()
    monkeypatch.setattr(spd.SavePresetDialog, "exec", fake_exec)
    return seen


def test_saving_stores_the_steps_after_the_crop_and_a_preview(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="LP")); _crop(win); _stretch(win)
    win._enhance("Vibrance"); _to(win, "enhancements")
    seen = _answer(monkeypatch)
    win._save_preset()
    [p] = win._presets.list()
    assert [s["stage"] for s in p.steps] == ["stretch", "enhance"]
    assert p.data_type == "dualband" and p.name == "M 8"
    assert open(p.preview_path, "rb").read()[:2] == b"\xff\xd8"
    assert [seen["dlg"].steps_list.item(i).text() for i in range(seen["dlg"].steps_list.count())] \
        == ["Stretch", "Vibrance"]
    assert str(tmp_path) in p.folder                  # sandboxed beside settings.json


def test_overwriting_asks_and_cancel_keeps_the_old(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    _answer(monkeypatch); win._save_preset()
    [old] = win._presets.list()
    win._enhance("Vibrance")
    seen = _answer(monkeypatch, name="m 8", replace=False)
    win._save_preset()
    assert seen["asked"] == "m 8"
    [still] = win._presets.list()
    assert (still.id, still.steps) == (old.id, old.steps)


def test_overwriting_confirmed_replaces_it(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    _answer(monkeypatch); win._save_preset()
    [old] = win._presets.list()
    win._enhance("Vibrance")
    _answer(monkeypatch, name="m 8", replace=True)
    win._save_preset()
    [new] = win._presets.list()
    assert new.id != old.id
    assert [s["stage"] for s in new.steps] == ["stretch", "enhance"]


def test_a_new_name_is_never_asked_about(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    seen = _answer(monkeypatch, name="M 8", replace=False)
    win._save_preset()
    assert "asked" not in seen
    assert [p.name for p in win._presets.list()] == ["M 8"]


def test_left_out_steps_are_listed_and_excluded_ones_are_not(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win)
    win._apply_star_spikes(win.project.current())     # the legacy "" option
    h, w = win.project.current().data.shape[:2]
    monkeypatch.setattr(mw, "TrimDialog", lambda img, parent=None: _FakeTrim((1, h - 1, 1, w - 1)))
    win._trim()
    assert [n for n, _ in win.project.entries()][-1] == "Trim"     # the precondition
    _to(win, "enhancements")
    seen = _answer(monkeypatch)
    win._save_preset()
    lbl = seen["dlg"].left_out_label
    assert lbl.isVisibleTo(seen["dlg"]) and "Star Spikes" in lbl.text()
    assert "Crop" not in lbl.text() and "Trim" not in lbl.text()
    assert win._presets.list()[0].left_out == ("Star Spikes",)


def test_the_target_prefills_the_name(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    win.project.set_current_metadata("target", "NGC 7000")
    import nocturne.ui.save_preset_dialog as spd
    seen = {}
    def fake_exec(self):
        seen["name"] = self.name_edit.text()
        return 0
    monkeypatch.setattr(spd.SavePresetDialog, "exec", fake_exec)
    win._save_preset()
    assert seen["name"] == "NGC 7000"
    assert win._presets.list() == []                  # cancelled: nothing written


def test_blank_name_cannot_be_saved(qtbot):
    from nocturne.ui.save_preset_dialog import SavePresetDialog
    d = SavePresetDialog(b"", "", ["Stretch"], [], existing=lambda n: False)
    qtbot.addWidget(d)
    assert not d.save_btn.isEnabled()
    d.name_edit.setText("   ")
    assert not d.save_btn.isEnabled()
    d.name_edit.setText("M 8")
    assert d.save_btn.isEnabled()
    assert not d.left_out_label.isVisibleTo(d)        # nothing left out: no warning line


def test_nothing_to_save_disables_save(qtbot):
    from nocturne.ui.save_preset_dialog import SavePresetDialog
    d = SavePresetDialog(b"", "M 8", [], [], existing=lambda n: False)
    qtbot.addWidget(d)
    assert not d.save_btn.isEnabled()
    assert "Nothing to save yet" in d.findChild(type(d.left_out_label), "emptyNote").text()


def test_the_dialog_says_what_is_never_saved_and_why_steps_were_left_out(qtbot):
    from PySide6.QtWidgets import QLabel
    from nocturne.ui.save_preset_dialog import SavePresetDialog
    d = SavePresetDialog(b"", "M 8", ["Stretch"], ["Star Spikes", "Linear Denoise"],
                         existing=lambda n: False)
    qtbot.addWidget(d)
    texts = [w.text() for w in d.findChildren(QLabel)]
    assert "Crop, rotate, flip and Trim belong to this picture and are not saved." in texts
    assert "Star Spikes (saved before its settings were recorded)" in d.left_out_label.text()
    assert "Linear Denoise — a preset cannot replay it" in d.left_out_label.text()


# --- fix round 1 ---------------------------------------------------------------

@pytest.mark.parametrize("exc", [OSError("disk full"), ValueError("disk full")])
def test_a_failed_save_warns_and_keeps_the_name(qtbot, tmp_path, monkeypatch, exc):
    import nocturne.ui.save_preset_dialog as spd
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(win._presets, "save", boom)
    calls = []
    def fake_exec(self):
        calls.append((self, self.name_edit.text()))
        if len(calls) == 1:
            self.name_edit.setText("M 8")
            self._on_save()
            return self.result()
        return 0                                      # the user gives up the second time
    monkeypatch.setattr(spd.SavePresetDialog, "exec", fake_exec)
    win._save_preset()                                # must not raise
    assert len(calls) == 2, "the dialog comes back after a failed save"
    assert calls[1] == (calls[0][0], "M 8"), "same dialog, name kept"
    assert "Couldn't save the preset: disk full" in win._warning.text()
    assert "disk full" in calls[0][0].error_label.text()


def test_a_preset_error_is_reported_too(qtbot, tmp_path, monkeypatch):
    from nocturne.user_presets import PresetError
    import nocturne.ui.save_preset_dialog as spd
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    monkeypatch.setattr(win._presets, "save",
                        lambda *a, **k: (_ for _ in ()).throw(PresetError("a preset needs a name")))
    n = []
    def fake_exec(self):
        n.append(1)
        if len(n) > 1:
            return 0
        self.name_edit.setText("M 8"); self._on_save(); return self.result()
    monkeypatch.setattr(spd.SavePresetDialog, "exec", fake_exec)
    win._save_preset()
    assert "Couldn't save the preset: a preset needs a name" in win._warning.text()


def test_nothing_capturable_keeps_the_action_off_and_says_why(qtbot, tmp_path):
    from tests.ui.test_open_tiff import _write_stretched_tiff
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    _to(win, "export")
    assert win.current_stage_id() == "export"
    assert not win.project.is_linear_at(win.project.position)   # the other half of the gate holds
    assert not win._save_preset_act.isEnabled()
    assert not win._panel.save_preset_btn.isEnabled()
    tip = win._save_preset_act.toolTip()
    assert "nothing to save" in tip.lower() and "Enhancements first" not in tip
    assert win._panel.save_preset_btn.toolTip() == tip
    win._enhance("Vibrance")
    assert win._save_preset_act.isEnabled()
    assert win._panel.save_preset_btn.isEnabled()


def test_a_long_target_is_cut_at_a_word_to_fit(qtbot):
    from nocturne.ui.save_preset_dialog import SavePresetDialog
    from nocturne.user_presets import MAX_NAME
    long = " ".join(["Andromedae"] * 20)              # 80 falls inside a word
    assert long[MAX_NAME - 1] != " " and long[MAX_NAME] != " "
    d = SavePresetDialog(b"", long, ["Stretch"], [], existing=lambda n: False)
    qtbot.addWidget(d)
    got = d.name_edit.text()
    assert 0 < len(got) <= MAX_NAME and got == got.strip()
    assert long.startswith(got) and got.split() == ["Andromedae"] * len(got.split())


def test_the_preview_is_drawn_at_the_screens_pixel_ratio(qtbot, monkeypatch):
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.ui.save_preset_dialog import SavePresetDialog, _PREVIEW_EDGE
    from nocturne.user_presets import preview_jpeg
    jpg = preview_jpeg(AstroImage(np.full((400, 600, 3), 0.5, np.float32), is_linear=False))
    monkeypatch.setattr(SavePresetDialog, "devicePixelRatioF", lambda self: 2.0)
    d = SavePresetDialog(jpg, "M 8", ["Stretch"], [], existing=lambda n: False)
    qtbot.addWidget(d)
    pm = d.preview_pixmap                            # what was handed to the label
    assert pm.devicePixelRatio() == 2.0
    assert pm.width() == 2 * _PREVIEW_EDGE           # device pixels, so sharp on Retina
    assert d.minimumWidth() >= 360


# --- placement (owner, 2026-10-13): not on the toolbar ---------------------------

def test_it_is_not_on_the_toolbar(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert "Save as Preset…" not in [a.text() for a in win._overflow.all_actions]
    assert win._save_preset_act not in win._toolbar.actions()


def test_it_is_in_the_project_menu(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    from PySide6.QtWidgets import QMenu
    # findChildren, not menuAction().menu(): that wrapper let PySide delete the menu.
    [project] = [m for m in win.menuBar().findChildren(QMenu) if m.title() == "Project"]
    texts = [a.text() for a in project.actions()]
    assert "Save as Preset…" in texts
    assert texts.index("Save as Preset…") > texts.index("Provenance report…")
    assert project.actions()[texts.index("Save as Preset…")] is win._save_preset_act


def test_the_export_button_saves(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "export")
    _answer(monkeypatch)
    win._panel.save_preset_btn.click()
    assert [p.name for p in win._presets.list()] == ["M 8"]


@pytest.mark.parametrize("size", [(1280, 800), (1440, 900 - 30 - 28)])
def test_the_export_button_is_whole_and_reachable(qtbot, tmp_path, size):
    """On Export it may sit below the fold at 1280x800 (spec 2026-10-14: the
    gallery and preset buttons may scroll); it must still be whole, inside the
    column, and reachable by scrolling. Real window, real stylesheet."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = _window(qtbot, tmp_path)
        win.open_fits(_make_fits(tmp_path))
        win.resize(*size); win.show(); qtbot.waitExposed(win)
        _crop(win); _stretch(win)
        _to(win, "export"); qtbot.wait(80)
        btn = win._panel.save_preset_btn
        assert btn.isVisible() and btn.isEnabled()
        win._side.scroll.ensureWidgetVisible(btn); qtbot.wait(20)
        view = win._side.scroll.viewport()
        top = btn.mapTo(view, btn.rect().topLeft())
        assert 0 <= top.y() and top.y() + btn.height() <= view.height(), "not reachable"
        assert btn.width() >= btn.minimumSizeHint().width(), "label clipped"
        assert btn.mapTo(win._side, btn.rect().topRight()).x() <= win._side.width()
    finally:
        app.setStyleSheet(before)
