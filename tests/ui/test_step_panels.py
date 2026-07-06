import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel  # noqa: E402
from seestar_processor.ui.pipeline import path_stages  # noqa: E402
from seestar_processor.ui.step_panels import build_panel  # noqa: E402


def test_panel_is_a_card(qtbot):
    stage = next(s for s in path_stages() if s.id == "stretch")
    panel = build_panel(stage)
    qtbot.addWidget(panel)
    assert panel.objectName() == "stepCard"


def test_panel_has_description_strip(qtbot):
    stage = next(s for s in path_stages() if s.id == "stretch")
    panel = build_panel(stage)
    qtbot.addWidget(panel)
    descs = [c for c in panel.findChildren(QLabel) if c.objectName() == "stepDesc"]
    assert descs, "panel has a stepDesc label"


def _stage(stage_id):
    return next(s for s in path_stages() if s.id == stage_id)


def test_import_panel_has_open_and_meta(qtbot):
    clicked = []
    w = build_panel(_stage("load"), on_open=lambda: clicked.append(True))
    qtbot.addWidget(w)
    assert w.panel_kind == "import"
    assert hasattr(w, "meta_label")


def test_crop_panel_immediate_buttons(qtbot):
    got = []
    w = build_panel(
        _stage("crop"),
        on_rotate=lambda: got.append("rotate"),
        on_flip_h=lambda: got.append("flip_h"),
        on_flip_v=lambda: got.append("flip_v"),
        on_crop_apply=lambda: got.append("crop"),
    )
    qtbot.addWidget(w)
    assert w.flip_h_btn.isCheckable() is False   # momentary, not sticky
    assert w.flip_v_btn.isCheckable() is False
    w.rotate_btn.click()
    w.flip_h_btn.click()
    w.flip_v_btn.click()
    w.apply_btn.click()
    assert got == ["rotate", "flip_h", "flip_v", "crop"]


def test_background_off_enables_apply_without_graxpert(qtbot):
    w = build_panel(_stage("background"), on_apply=lambda o: None, apply_enabled=False)
    qtbot.addWidget(w)
    w.option_box.setCurrentText("off")
    assert w.apply_btn.isEnabled() is True
    w.option_box.setCurrentText("light")
    assert w.apply_btn.isEnabled() is False
    assert w.disabled_note.isHidden() is False


def test_auto_panel_apply_color_has_no_green(qtbot):
    from seestar_processor.core.color import ColorSettings
    got = []
    w = build_panel(_stage("color"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "auto"
    assert not hasattr(w, "remove_green_check")
    w.apply_btn.click()
    assert len(got) == 1 and isinstance(got[0], ColorSettings)
    assert got[0].remove_green is False


def test_auto_panel_remove_green_button_invokes_callback(qtbot):
    calls = []
    w = build_panel(_stage("color"), on_remove_green=lambda: calls.append(True))
    qtbot.addWidget(w)
    w.remove_green_btn.click()
    assert calls == [True]


def test_levels_panel_emits_tuple(qtbot):
    got = []
    w = build_panel(_stage("levels"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "levels"
    w.black_slider.setValue(20)
    w.gamma_slider.setValue(150)
    w.white_slider.setValue(90)
    w.apply_btn.click()
    assert got == [(0.20, 1.50, 0.90)]


def test_star_reduction_gated_without_rcastro(qtbot):
    w = build_panel(_stage("star_reduction"), on_apply=lambda o: None, apply_enabled=False)
    qtbot.addWidget(w)
    assert w.panel_kind == "process"
    assert w.apply_btn.isEnabled() is False
    assert w.disabled_note.isHidden() is False


def test_stretch_panel_slider_emits_amount(qtbot):
    got = []
    w = build_panel(_stage("stretch"), on_apply=got.append)
    qtbot.addWidget(w)
    w.stretch_slider.setValue(70)
    w.apply_btn.click()
    assert got == [0.70]


def test_stretch_target_sets_slider(qtbot):
    w = build_panel(_stage("stretch"), on_apply=lambda v: None)
    qtbot.addWidget(w)
    w.target_box.setCurrentText("Nebula")
    assert w.stretch_slider.value() == 60
    w.target_box.setCurrentText("Galaxy")
    assert w.stretch_slider.value() == 40


def test_saturation_panel_default_is_native(qtbot):
    w = build_panel(_stage("saturation"))
    qtbot.addWidget(w)
    assert w.sat_slider.value() == 50


def test_saturation_panel_emits_amount(qtbot):
    got = []
    w = build_panel(_stage("saturation"), on_apply=got.append)
    qtbot.addWidget(w)
    w.sat_slider.setValue(50)
    w.apply_btn.click()
    assert got == [0.50]


def test_export_panel_split_disabled_without_rcastro(qtbot):
    w = build_panel(_stage("export"), split_enabled=False)
    qtbot.addWidget(w)
    assert w.fmt_box.count() == 4
    assert w.fmt_box.model().item(3).isEnabled() is False  # split needs RC-Astro


def test_export_panel_split_enabled_with_rcastro(qtbot):
    w = build_panel(_stage("export"), split_enabled=True)
    qtbot.addWidget(w)
    assert w.fmt_box.model().item(3).isEnabled() is True


def test_export_panel_formats(qtbot):
    got = []
    w = build_panel(_stage("export"), on_export=got.append)
    qtbot.addWidget(w)
    w.fmt_box.setCurrentText("PNG")
    w.export_btn.click()
    assert got == ["PNG"]


def test_sliders_are_reset_sliders_with_defaults(qtbot):
    from seestar_processor.ui.reset_slider import ResetSlider
    st = build_panel(_stage("stretch")); qtbot.addWidget(st)
    assert isinstance(st.stretch_slider, ResetSlider) and st.stretch_slider._default == 50
    lv = build_panel(_stage("levels")); qtbot.addWidget(lv)
    assert isinstance(lv.black_slider, ResetSlider) and lv.black_slider._default == 0
    assert isinstance(lv.gamma_slider, ResetSlider) and lv.gamma_slider._default == 100
    assert lv.gamma_slider.value() == 100           # 10-300 range, not clamped
    assert isinstance(lv.white_slider, ResetSlider) and lv.white_slider._default == 100
    sa = build_panel(_stage("saturation")); qtbot.addWidget(sa)
    assert isinstance(sa.sat_slider, ResetSlider) and sa.sat_slider._default == 50


def test_stretch_slider_double_click_resets(qtbot):
    from PySide6.QtCore import Qt
    st = build_panel(_stage("stretch")); qtbot.addWidget(st)
    st.stretch_slider.setValue(20)
    qtbot.mouseDClick(st.stretch_slider, Qt.MouseButton.LeftButton)
    assert st.stretch_slider.value() == 50


def test_stretch_panel_has_colourise_and_advanced(qtbot):
    cols, advs = [], []
    w = build_panel(_stage("stretch"),
                    on_colourise=lambda: cols.append(1),
                    on_palette_advanced=lambda: advs.append(1))
    qtbot.addWidget(w)
    assert hasattr(w, "colourise_btn") and hasattr(w, "advanced_btn")
    w.colourise_btn.click(); w.advanced_btn.click()
    assert cols == [1] and advs == [1]
    w.apply_btn.click()          # Apply Stretch still works (no crash)


def test_color_panel_has_narrowband_tip(qtbot):
    from PySide6.QtWidgets import QLabel
    w = build_panel(_stage("color"))
    qtbot.addWidget(w)
    texts = [c.text().lower() for c in w.findChildren(QLabel)]
    assert any("skip" in t and ("narrowband" in t or "dualband" in t) for t in texts)


def test_deconvolution_panel_emits_strength(qtbot):
    got = []
    w = build_panel(_stage("deconvolution"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "process"
    assert [w.option_box.itemText(i) for i in range(w.option_box.count())] == \
        ["light", "medium", "strong"]
    w.option_box.setCurrentText("strong")
    w.apply_btn.click()
    assert got == ["strong"]


def test_enhance_panel_buttons_invoke_callback(qtbot):
    ops = []
    w = build_panel(_stage("enhancements"), on_enhance=ops.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "enhance"
    w.boost_red_btn.click()
    w.darken_sky_btn.click()
    w.lighten_sky_btn.click()
    assert ops == ["Boost Red", "Darken Sky", "Lighten Sky"]
