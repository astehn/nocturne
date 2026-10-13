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
    assert "Enhancements first" in win._save_preset_act.toolTip()


def test_disabled_with_no_picture_and_while_busy(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert not win._save_preset_act.isEnabled()
    win.open_fits(_make_fits(tmp_path)); _crop(win); _stretch(win); _to(win, "enhancements")
    assert win._save_preset_act.isEnabled()          # the precondition the busy check needs
    win._set_busy(True, "x")
    assert not win._save_preset_act.isEnabled()
    win._set_busy(False)
    assert win._save_preset_act.isEnabled()


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
