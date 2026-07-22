import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel  # noqa: E402
from nocturne.ui.pipeline import path_stages  # noqa: E402
from nocturne.ui.step_panels import build_panel  # noqa: E402


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
    assert w.apply_btn.isEnabled() is False      # off until the crop box is shown
    w.rotate_btn.click()
    w.flip_h_btn.click()
    w.flip_v_btn.click()
    w.apply_btn.setEnabled(True)                  # main_window enables on cropBoxShown
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
    from nocturne.core.color import ColorSettings
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


def test_levels_panel_controls(qapp):
    from PySide6.QtWidgets import QCheckBox
    seen = {}
    w = build_panel(_stage("levels"),
                    on_levels_change=lambda b, g, wt: seen.setdefault("chg", (b, g, wt)),
                    on_levels_auto=lambda: seen.setdefault("auto", True),
                    on_levels_clipping=lambda c: seen.setdefault("clip", c))
    assert hasattr(w, "auto_btn") and hasattr(w, "clip_check")
    labels = " ".join(l.text() for l in w.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "Midtones" in labels and "(gamma)" not in labels
    w.black_slider.setValue(20)                 # fires on_levels_change + readout
    assert "chg" in seen
    assert w.black_val.text().strip() != ""
    w.auto_btn.click(); assert seen.get("auto") is True
    w.clip_check.setChecked(True); assert seen.get("clip") is True


def test_stretch_panel_has_live_preview_readout(qtbot):
    seen = {}
    w = build_panel(_stage("stretch"),
                    on_stretch_change=lambda a: seen.__setitem__("amt", a))
    qtbot.addWidget(w)
    assert hasattr(w, "stretch_slider")
    assert hasattr(w, "stretch_val")
    w.stretch_slider.setValue(70)
    assert w.stretch_val.text().strip() == "0.70"   # numeric readout tracks the slider
    assert seen.get("amt") == 0.70                   # live-preview hook fires


def test_star_reduction_panel_has_slider_disabled_initially(qtbot):
    w = build_panel(_stage("star_reduction"))
    qtbot.addWidget(w)
    assert w.panel_kind == "star_reduction"
    assert hasattr(w, "sr_slider")
    assert hasattr(w, "sr_val")
    assert hasattr(w, "sr_status")
    assert w.sr_slider.value() == 0
    assert w.sr_val.text().strip() == "0.00"
    # Slider + Apply start disabled — main_window enables them once the split lands.
    assert w.sr_slider.isEnabled() is False
    assert w.apply_btn.isEnabled() is False


def test_star_reduction_slider_emits_amount(qtbot):
    seen = {}
    w = build_panel(_stage("star_reduction"),
                    on_sr_change=lambda a: seen.__setitem__("amt", a))
    qtbot.addWidget(w)
    w.sr_slider.setEnabled(True)  # simulate main_window enabling after the split
    w.sr_slider.setValue(80)
    assert w.sr_val.text().strip() == "0.80"
    assert seen.get("amt") == 0.80


def test_star_reduction_apply_emits_amount(qtbot):
    got = []
    w = build_panel(_stage("star_reduction"), on_sr_apply=got.append)
    qtbot.addWidget(w)
    w.apply_btn.setEnabled(True)
    w.sr_slider.setValue(50)
    w.apply_btn.click()
    assert got == [0.50]


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
    w = build_panel(_stage("saturation"), on_sat_apply=lambda a, n: got.append((a, n)))
    qtbot.addWidget(w)
    w.sat_slider.setValue(50)
    w.apply_btn.click()
    assert got == [(0.50, 0.0)]


def test_saturation_panel_has_nebula_boost(qtbot):
    changed, applied = [], []
    w = build_panel(_stage("saturation"),
                    on_sat_change=lambda a, n: changed.append((a, n)),
                    on_sat_apply=lambda a, n: applied.append((a, n)))
    qtbot.addWidget(w)
    assert w.panel_kind == "saturation"
    for attr in ("sat_slider", "sat_val", "neb_slider", "neb_val", "neb_status", "apply_btn"):
        assert hasattr(w, attr)
    assert w.sat_slider.value() == 50          # native default
    assert w.neb_slider.value() == 0           # off default
    w.neb_slider.setValue(60)
    assert changed[-1] == (0.50, 0.60)         # (amount, nebula)
    assert w.neb_val.text().strip() == "0.60"
    w.apply_btn.click()
    assert applied[-1] == (0.50, 0.60)


def test_local_contrast_panel_default_is_off(qtbot):
    w = build_panel(_stage("local_contrast"))
    qtbot.addWidget(w)
    assert w.panel_kind == "local_contrast"
    assert w.lc_slider.value() == 0


def test_local_contrast_panel_emits_amount(qtbot):
    got = []
    w = build_panel(_stage("local_contrast"), on_apply=got.append)
    qtbot.addWidget(w)
    w.lc_slider.setValue(60)
    w.apply_btn.click()
    assert got == [0.60]


def test_local_contrast_panel_has_readout_and_live_change(qapp):
    seen = {}
    w = build_panel(_stage("local_contrast"),
                    on_lc_change=lambda a: seen.__setitem__("amt", a))
    assert hasattr(w, "lc_val")
    assert w.lc_val.text().strip() == "0.00"       # default slider 0 -> 0.00
    w.lc_slider.setValue(80)                        # fires readout + on_lc_change
    assert w.lc_val.text().strip() == "0.80"
    assert seen.get("amt") == 0.80


def test_recover_core_panel_has_live_preview_readout(qtbot):
    seen = {}
    w = build_panel(_stage("recover_core"),
                    on_recover_change=lambda a: seen.__setitem__("amt", a))
    qtbot.addWidget(w)
    assert w.panel_kind == "recover_core"
    assert hasattr(w, "recover_slider")
    assert hasattr(w, "recover_val")
    assert w.recover_slider.value() == 0          # default off
    assert w.recover_val.text().strip() == "0.00"
    w.recover_slider.setValue(60)
    assert w.recover_val.text().strip() == "0.60"  # readout tracks the slider
    assert seen.get("amt") == 0.60                 # live-preview hook fires


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
    from nocturne.ui.reset_slider import ResetSlider
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


def test_import_panel_meta_label_is_rich_text(qtbot):
    from PySide6.QtCore import Qt
    from nocturne.ui.step_panels import build_panel
    from nocturne.ui.pipeline import path_stages
    stage = next(s for s in path_stages() if s.kind == "import")
    w = build_panel(stage)
    qtbot.addWidget(w)
    assert w.meta_label.textFormat() == Qt.TextFormat.RichText


def test_crop_panel_has_guides_combo(qapp):
    seen = []
    w = build_panel(_stage("crop"), on_guides_change=lambda k: seen.append(k))
    assert hasattr(w, "guides_box")
    items = [w.guides_box.itemText(i) for i in range(w.guides_box.count())]
    assert items == ["None", "Rule of thirds", "Center cross"]
    w.guides_box.setCurrentText("Rule of thirds")
    assert seen and seen[-1] == "thirds"


def test_import_panel_has_linear_preview_note(qapp):
    w = build_panel(_stage("load"))
    from PySide6.QtWidgets import QLabel
    texts = " ".join(l.text() for l in w.findChildren(QLabel))
    assert "histogram" in texts.lower() or "un-stretched" in texts.lower()


def test_crop_panel_labels_and_grouping_polish(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton
    w = build_panel(_stage("crop"))

    btn_texts = [b.text() for b in w.findChildren(QPushButton)]
    assert any("↻" in t for t in btn_texts)

    label_texts = [l.text().lower() for l in w.findChildren(QLabel)]
    assert any("apply instantly" in t for t in label_texts)


def test_process_panel_preselects_default_option(qapp):
    w = build_panel(_stage("background"), option_default="light")
    assert w.option_box.currentText() == "light"   # not "off"


def test_background_panel_explains_gradient(qapp):
    from PySide6.QtWidgets import QLabel
    w = build_panel(_stage("background"))
    texts = " ".join(l.text().lower() for l in w.findChildren(QLabel))
    assert "gradient" in texts and "before/after" in texts


def test_curves_panel_has_editor_and_presets(qtbot):
    changed, presets = [], []
    w = build_panel(_stage("curves"),
                    on_curve_change=changed.append,
                    on_curve_preset=presets.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "curves"
    assert hasattr(w, "curve_editor")
    assert hasattr(w, "reset_btn") and hasattr(w, "add_contrast_btn")
    # editor edits route to on_curve_change
    w.curve_editor.add_point(0.5, 0.7)
    assert changed and changed[-1][-1] == (1.0, 1.0)   # emitted a point list
    # preset buttons route to on_curve_preset with the right kind
    w.reset_btn.click()
    w.add_contrast_btn.click()
    assert presets == ["reset", "add_contrast"]


def test_noise_engine_dropdown_shown_when_both_installed(qtbot):
    captured = []
    w = build_panel(_stage("noise_sharpen"), on_apply=captured.append,
                    denoise_engine_choices=["Default", "RC-Astro", "GraXpert"],
                    denoise_default_engine="rcastro")
    qtbot.addWidget(w)
    assert hasattr(w, "engine_box")
    w.engine_box.setCurrentText("GraXpert")
    w.option_box.setCurrentText("strong")
    w.apply_btn.click()
    assert captured == [{"engine": "graxpert", "level": "strong"}]


def test_noise_default_choice_uses_setting(qtbot):
    captured = []
    w = build_panel(_stage("noise_sharpen"), on_apply=captured.append,
                    denoise_engine_choices=["Default", "RC-Astro", "GraXpert"],
                    denoise_default_engine="graxpert")
    qtbot.addWidget(w)
    # "Default" resolves to the passed default engine
    w.engine_box.setCurrentText("Default")
    w.option_box.setCurrentText("medium")
    w.apply_btn.click()
    assert captured == [{"engine": "graxpert", "level": "medium"}]


def test_noise_no_dropdown_when_not_both_installed(qtbot):
    captured = []
    w = build_panel(_stage("noise_sharpen"), on_apply=captured.append,
                    denoise_engine_choices=None, denoise_default_engine="rcastro")
    qtbot.addWidget(w)
    assert not hasattr(w, "engine_box")
    w.option_box.setCurrentText("light")
    w.apply_btn.click()
    assert captured == [{"engine": "rcastro", "level": "light"}]


def test_green_fringe_panel_gated_and_wired(qtbot):
    changed, applied = {}, {}
    w = build_panel(_stage("green_fringe"),
                    on_fringe_change=lambda s: changed.__setitem__("s", s),
                    on_fringe_apply=lambda s: applied.__setitem__("s", s))
    qtbot.addWidget(w)
    assert w.panel_kind == "green_fringe"
    assert hasattr(w, "fringe_status") and hasattr(w, "fringe_slider")
    # slider + Apply start disabled (main_window enables once the split lands)
    assert w.fringe_slider.isEnabled() is False
    assert w.apply_btn.isEnabled() is False
    w.fringe_slider.setEnabled(True)
    w.fringe_slider.setValue(60)
    assert w.fringe_val.text().strip() == "0.60"
    assert changed.get("s") == 0.60
    w.apply_btn.setEnabled(True)
    w.apply_btn.click()
    assert applied.get("s") == 0.60
