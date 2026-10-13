import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QListWidget
from PySide6.QtCore import Qt
from nocturne.settings import Settings
from nocturne import user_presets as up

STEPS = [{"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
         {"stage": "enhance", "option": "Vibrance"}]


def _jpeg():
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (60, 40), (40, 10, 60)).save(b, "JPEG")
    return b.getvalue()


# Created order, name order and target order all DIFFER, so a sort test cannot
# pass by symmetry: created M 8, Heart, M 31; name Heart, M 31, M 8;
# target M 31, M 8, NGC 896.
def _lib(tmp_path, specs=(("M 8", "M 8", "dualband", 3), ("M 31", "M 31", "broadband", 1),
                          ("Heart", "NGC 896", "dualband", 2))):
    lib = up.PresetLibrary(str(tmp_path / "presets"))
    for name, target, dt, t in specs:
        lib.save(name, STEPS, _jpeg(), target=target, data_type=dt, now=1_760_000_000 + t)
    return lib


def _browser(qtbot, lib, picture_type="dualband", settings=None, **kw):
    from nocturne.ui.preset_browser import PresetBrowser
    b = PresetBrowser(lib, picture_type=picture_type, settings=settings or Settings(), **kw)
    qtbot.addWidget(b)
    return b


def _select(b, name):
    b.items.setCurrentRow(_names(b).index(name))


def _names(b):
    return [b.items.item(i).text().split("\n")[0].split(" — ")[0] for i in range(b.items.count())
            if not b.items.item(i).isHidden()]


def test_default_is_grid_on_a_big_screen_and_list_on_a_small_one(qtbot, tmp_path):
    lib = _lib(tmp_path)
    assert _browser(qtbot, lib, screen_height=1400).items.viewMode() == QListWidget.ViewMode.IconMode
    assert _browser(qtbot, lib, screen_height=775).items.viewMode() == QListWidget.ViewMode.ListMode


def test_the_view_choice_is_remembered(qtbot, tmp_path):
    s, saved = Settings(), []
    b = _browser(qtbot, _lib(tmp_path), settings=s, screen_height=1400,
                 on_settings_changed=lambda: saved.append(s.preset_view))
    b.list_btn.click()
    assert s.preset_view == "list" and saved == ["list"]
    b2 = _browser(qtbot, _lib(tmp_path / "x"), settings=s, screen_height=1400)
    assert b2.items.viewMode() == QListWidget.ViewMode.ListMode


def test_both_views_hold_the_same_presets_with_previews_only_in_grid(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path), screen_height=1400)
    grid = _names(b)
    assert not b.items.item(0).icon().isNull()
    b.list_btn.click()
    assert _names(b) == grid and b.items.item(0).icon().isNull()


@pytest.mark.parametrize("key,want", [("created", ["M 8", "Heart", "M 31"]),
                                      ("name", ["Heart", "M 31", "M 8"]),
                                      ("target", ["M 31", "M 8", "Heart"])])
def test_sort(qtbot, tmp_path, key, want):
    s = Settings()
    b = _browser(qtbot, _lib(tmp_path), settings=s)
    b.sort_box.setCurrentIndex(b.sort_box.findData(key))
    assert _names(b) == want and s.preset_sort == key


def test_last_used_sort(qtbot, tmp_path):
    lib = _lib(tmp_path)
    lib.touch(lib.find("M 31"), now=1_770_000_000)
    b = _browser(qtbot, lib)
    b.sort_box.setCurrentIndex(b.sort_box.findData("last_used"))
    assert _names(b)[0] == "M 31"


def test_search_and_type_filter(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path), picture_type="broadband")
    b.search.setText("ngc 8")
    assert _names(b) == ["Heart"]
    b.search.setText("")
    b.type_filter.setChecked(True)
    assert _names(b) == ["M 31"]


def test_dual_band_preset_is_disabled_on_broadband_with_a_reason(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path), picture_type="broadband")
    item = next(b.items.item(i) for i in range(b.items.count())
                if b.items.item(i).text().startswith("M 8"))
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert "dual-band" in item.toolTip()
    b.items.setCurrentItem(item)
    assert not b.choose_btn.isEnabled()


def test_broadband_preset_on_dual_band_is_allowed_and_marked(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path), picture_type="dualband")
    item = next(b.items.item(i) for i in range(b.items.count())
                if b.items.item(i).text().startswith("M 31"))
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled and "broadband" in item.text()


def test_choose_returns_the_preset_and_cancel_returns_none(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path))
    _select(b, "Heart")
    b.choose_btn.click()
    assert b.chosen().name == "Heart"
    b2 = _browser(qtbot, _lib(tmp_path / "y"))
    b2.reject()
    assert b2.chosen() is None


def test_details_show_the_steps_a_preset_holds(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path))
    b.items.setCurrentRow(0)
    assert [b.details_steps.item(i).text() for i in range(b.details_steps.count())] == \
        ["Stretch", "Vibrance"]
    assert "2 steps" in b.details_meta.text()


def test_rename_in_place_and_a_clash_is_a_message_not_a_crash(qtbot, tmp_path):
    lib = _lib(tmp_path)
    b = _browser(qtbot, lib)
    _select(b, "Heart")
    b._ask_name = lambda cur: "Heart Nebula"
    b.rename_btn.click()
    assert lib.find("Heart Nebula") is not None and "Heart Nebula" in _names(b)
    b._ask_name = lambda cur: "m 8"
    b.rename_btn.click()
    assert lib.find("Heart Nebula") is not None and b.warning.text()


def test_delete_asks_and_removes(qtbot, tmp_path):
    lib = _lib(tmp_path)
    b = _browser(qtbot, lib, current_id=lib.find("M 8").id)
    _select(b, "M 8")
    b._ask_delete = lambda p: False
    b.delete_btn.click()
    assert lib.find("M 8") is not None
    b._ask_delete = lambda p: True
    b.delete_btn.click()
    assert lib.find("M 8") is None and "M 8" not in _names(b) and b.deleted_current


def test_empty_state_explains_how_presets_are_made(qtbot, tmp_path):
    b = _browser(qtbot, up.PresetLibrary(str(tmp_path / "none")))
    assert b.empty_label.isVisibleTo(b) and "Save as Preset" in b.empty_label.text()
    assert "Enhancements" in b.empty_label.text()


def test_use_no_preset_clears(qtbot, tmp_path):
    lib = _lib(tmp_path)
    b = _browser(qtbot, lib, current_id=lib.find("M 8").id)
    b.no_preset_btn.click()
    assert b.chosen() is None and b.cleared


def test_a_preset_with_no_preview_still_lists(qtbot, tmp_path):
    import os
    lib = _lib(tmp_path)
    os.remove(lib.find("M 8").preview_path)
    assert "M 8" in _names(_browser(qtbot, lib))


def test_no_match_says_so_and_hides_the_list(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path))
    b.search.setText("zzz")
    assert b.empty_label.isVisibleTo(b) and b.empty_label.text() == "No preset matches."
    assert not b.items.isVisibleTo(b) and not b.choose_btn.isEnabled()
    b.search.setText("")
    assert b.items.isVisibleTo(b) and not b.empty_label.isVisibleTo(b)


def test_current_preset_starts_selected_and_no_preset_button_only_then(qtbot, tmp_path):
    lib = _lib(tmp_path)
    b = _browser(qtbot, lib, current_id=lib.find("Heart").id)
    assert b.items.currentItem().data(Qt.ItemDataRole.UserRole) == lib.find("Heart").id
    assert b.details_title.text() == "Heart" and b.no_preset_btn.isVisibleTo(b)
    plain = _browser(qtbot, lib)
    assert not plain.no_preset_btn.isVisibleTo(plain)


def test_a_failed_delete_is_a_message_and_the_preset_stays(qtbot, tmp_path):
    lib = _lib(tmp_path)
    b = _browser(qtbot, lib)
    _select(b, "Heart")
    b._ask_delete = lambda p: True

    def refuse(p):
        raise PermissionError(13, "The file is in use")
    lib.delete = refuse
    b.delete_btn.click()
    assert "Heart" in b.warning.text() and "in use" in b.warning.text()
    assert "Heart" in _names(b) and not b.deleted_current


def test_a_disabled_preset_cannot_be_chosen_by_double_click(qtbot, tmp_path):
    b = _browser(qtbot, _lib(tmp_path), picture_type="broadband")
    item = next(b.items.item(i) for i in range(b.items.count())
                if b.items.item(i).text().startswith("M 8"))
    b.items.setCurrentItem(item)
    b.items.itemDoubleClicked.emit(item)
    assert b.chosen() is None and b.result() != b.DialogCode.Accepted


def test_details_name_what_was_left_out_and_the_data_kind(qtbot, tmp_path):
    lib = up.PresetLibrary(str(tmp_path / "p"))
    lib.save("Veil", STEPS, _jpeg(), target="NGC 6960", data_type="dualband",
             left_out=["Star Spikes"])
    b = _browser(qtbot, lib)
    b.items.setCurrentRow(0)
    assert b.details_left_out.text() == "Not included when saved: Star Spikes"
    assert b.details_meta.text().startswith("dual-band data · 2 steps · Nocturne ")


def test_sort_is_remembered_and_reported(qtbot, tmp_path):
    s, calls = Settings(), []
    b = _browser(qtbot, _lib(tmp_path), settings=s, on_settings_changed=lambda: calls.append(1))
    b.sort_box.setCurrentIndex(b.sort_box.findData("name"))
    assert s.preset_sort == "name" and calls == [1]
    b2 = _browser(qtbot, _lib(tmp_path / "z"), settings=s)
    assert b2.sort_box.currentData() == "name" and _names(b2) == ["Heart", "M 31", "M 8"]
