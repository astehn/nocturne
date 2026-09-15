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
    # De-green Sky moved to its own stage — Color must carry none of it.
    assert not hasattr(w, "rg_slider")
    assert not hasattr(w, "remove_green_btn")
    w.apply_btn.click()
    assert len(got) == 1 and isinstance(got[0], ColorSettings)
    assert got[0].remove_green is False


def test_color_panel_apply_passes_method(qtbot):
    from nocturne.core.color import ColorSettings
    captured = {}
    w = build_panel(_stage("color"), on_apply=lambda opt: captured.setdefault("opt", opt))
    qtbot.addWidget(w)
    assert hasattr(w, "method_box")
    w.method_box.setCurrentText("Photometric (SPCC)")
    w.apply_btn.click()
    assert isinstance(captured["opt"], ColorSettings)
    assert captured["opt"].method == "photometric"
    # default selection -> sky
    w2 = build_panel(_stage("color"), on_apply=lambda opt: captured.__setitem__("opt2", opt))
    qtbot.addWidget(w2)
    w2.apply_btn.click()
    assert captured["opt2"].method == "sky"


def test_remove_green_panel_apply_button_passes_strength(qtbot):
    calls = []
    w = build_panel(_stage("remove_green"), on_remove_green=calls.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "remove_green"
    w.rg_slider.setValue(70)
    w.apply_btn.click()
    assert calls == [0.70]                    # button hands the slider strength through


def test_remove_green_panel_slider_previews_live(qtbot):
    changes = []
    w = build_panel(_stage("remove_green"), on_removegreen_change=changes.append)
    qtbot.addWidget(w)
    # the default lives in its own test; this one is about the live preview
    w.rg_slider.setValue(25)
    assert changes[-1] == 0.25                # slider drives the live preview


def test_levels_panel_emits_tuple(qtbot):
    got = []
    w = build_panel(_stage("levels"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "levels"
    w.black_slider.setValue(200)        # black runs 0-1000, the other two 0-100
    w.gamma_slider.setValue(150)
    w.white_slider.setValue(90)
    w.apply_btn.click()
    assert got == [(0.20, 1.50, 0.90)]


def test_black_point_slider_resolves_finer_than_a_hundredth(qtbot):
    """The black point is the only value Auto Levels sets, so it carries the step.

    At 100 steps its useful range (about 0-0.15) held roughly fifteen positions,
    and auto's own output was rounded away before the user saw it: 0.081 and
    0.085 both became 0.08. Andreas noticed the symptom — "it always does +5 on
    black point" — on values that really were adapting underneath.
    """
    got = []
    w = build_panel(_stage("levels"), on_apply=got.append)
    qtbot.addWidget(w)                           # own the widget; no app from a sibling test
    w.black_slider.setValue(81)                  # 0.081, a real auto_levels output
    w.apply_btn.click()
    assert got[0][0] == 0.081
    assert "0.081" in w.black_val.text()


def test_levels_panel_controls(qapp):
    from PySide6.QtWidgets import QCheckBox
    seen = {}
    w = build_panel(_stage("levels"),
                    on_levels_change=lambda b, g, wt: seen.setdefault("chg", (b, g, wt)),
                    on_levels_auto=lambda: seen.setdefault("auto", True))
    assert hasattr(w, "auto_btn")
    labels = " ".join(l.text() for l in w.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "Midtones" in labels and "(gamma)" not in labels
    w.black_slider.setValue(20)                 # fires on_levels_change + readout
    assert "chg" in seen
    assert w.black_val.text().strip() != ""
    w.auto_btn.click(); assert seen.get("auto") is True


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


def test_stretch_panel_emits_amount_AND_mechanism(qtbot):
    """A dict since 2026-09-14: the stretch carries its mechanism as well as its
    amount, and both have to reach the commit."""
    got = []
    w = build_panel(_stage("stretch"), on_apply=got.append)
    qtbot.addWidget(w)
    w.stretch_slider.setValue(70)
    w.apply_btn.click()
    assert got == [{"amount": 0.70, "linked": True}]

    got.clear()
    w.stretch_linked = False
    w.apply_btn.click()
    assert got == [{"amount": 0.70, "linked": False}]


def test_only_the_stretch_panel_emits_a_dict(qtbot):
    """That exact Apply line appears in three panels, and a bare string replace
    patched all three — Recover Core and Local Contrast started emitting a
    stretch dict and their Apply buttons raised AttributeError. They take a bare
    float and must keep taking one."""
    for kind, slider_attr in (("recover_core", "recover_slider"),
                              ("local_contrast", "lc_slider")):
        got = []
        w = build_panel(_stage(kind), on_apply=got.append)
        qtbot.addWidget(w)
        getattr(w, slider_attr).setValue(60)
        w.apply_btn.click()
        assert got == [0.60], (kind, got)


def test_stretch_has_no_target_dropdown(qtbot):
    """Deleted 2026-09-13. Four entries, three distinct values, two identical;
    "Auto" set the slider to the value it already had; and the binding was
    one-way, so the box went on reading "Nebula" over a value that was not
    Nebula's. Andreas: "they should be removed as it's clearly a UI thing".
    """
    w = build_panel(_stage("stretch"), on_apply=lambda v: None)
    qtbot.addWidget(w)
    assert not hasattr(w, "target_box")
    from PySide6.QtWidgets import QComboBox
    assert not w.findChildren(QComboBox), "nothing left to pick on this step"


def test_the_stretch_default_is_the_one_he_measured(qtbot):
    """30, from ladders of four of his own masters (2026-09-14): M16, M33 and
    IC1396A all wanted 0.10; M45 wanted 0.20-0.30 because at 0.10 "too much of
    the nebulosity is not visible".

    The default takes the most conservative answer deliberately. Losing faint
    signal is unrecoverable — too bright and you see noise and drag it down, too
    dark and you never learn what you missed — so the default must fail in the
    recoverable direction. Pinned because it is EVIDENCE, and a future edit that
    drifts it should have to come back and disagree with the evidence.
    """
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    w = build_panel(_stage("stretch"), on_apply=lambda v: None)
    qtbot.addWidget(w)
    assert STRETCH_DEFAULT == 30
    assert w.stretch_slider.value() == STRETCH_DEFAULT


def test_the_manual_default_is_not_harsher_than_the_automatic_one(qtbot):
    """Before 2026-09-14 the manual default was 0.43 while Auto Enhance used
    0.30 — the hand-driven path was MORE aggressive than the automatic one,
    which nobody would design deliberately. Asserted as an inequality rather
    than equality so the two may diverge for a reason, but never back the wrong
    way round."""
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    from nocturne.core.auto_enhance import AUTO_STRETCH_AMOUNT
    assert STRETCH_DEFAULT / 100.0 <= AUTO_STRETCH_AMOUNT + 1e-9, (
        f"manual default {STRETCH_DEFAULT/100:.2f} is harsher than Auto "
        f"Enhance's {AUTO_STRETCH_AMOUNT:.2f}")


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
    """on_export now carries the colour space as well as the format — every
    export is tagged, so the exporter has to know which space to declare."""
    got = []
    w = build_panel(_stage("export"), on_export=lambda f, s: got.append((f, s)))
    qtbot.addWidget(w)
    w.fmt_box.setCurrentText("PNG")
    w.export_btn.click()
    assert got == [("PNG", "sRGB")]


def test_sliders_are_reset_sliders_with_defaults(qtbot):
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    from nocturne.ui.reset_slider import ResetSlider
    st = build_panel(_stage("stretch")); qtbot.addWidget(st)
    assert isinstance(st.stretch_slider, ResetSlider) \
        and st.stretch_slider._default == STRETCH_DEFAULT
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
    from nocturne.ui.step_panels import STRETCH_DEFAULT
    st.stretch_slider.setValue(20)
    qtbot.mouseDClick(st.stretch_slider, Qt.MouseButton.LeftButton)
    assert st.stretch_slider.value() == STRETCH_DEFAULT


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
    # Reworded on 2026-09-14: the panel no longer explains away a cast it can
    # now offer an alternative to. It must still say this is unstretched data
    # and that the switch is a view, not a commitment.
    low = texts.lower()
    assert "unstretched" in low or "un-stretched" in low
    assert "commit" in low and "stretch" in low


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


def test_background_panel_explains_gradient_and_how_to_check_it(qapp):
    """The panel must point at the control that answers "did that go well?".
    It used to send you to Before/After, which shows the corrected image but not
    what was taken out of it — the case worth catching (the fit eating your
    object) looks merely a little flat there and is obvious in the model."""
    from PySide6.QtWidgets import QLabel
    w = build_panel(_stage("background"))
    texts = " ".join(l.text().lower() for l in w.findChildren(QLabel))
    assert "gradient" in texts
    assert "show what was removed" in texts, "the check is not named"
    assert "mid-grey" in texts, "mid-grey is the reading key; without it the view is unreadable"


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
    applied = {}
    w = build_panel(_stage("green_fringe"),
                    on_fringe_apply=lambda s: applied.__setitem__("s", s))
    qtbot.addWidget(w)
    assert w.panel_kind == "green_fringe"
    assert hasattr(w, "fringe_status")
    # NO control: Apply is the switch. Andreas, 2026-09-13 — "since its only a
    # one step process would it simply be enough to press apply... there is
    # nothing to choose."
    from PySide6.QtWidgets import QCheckBox, QSlider
    assert not w.findChildren(QCheckBox), "the step has nothing to choose"
    assert not w.findChildren(QSlider), "and no strength either"
    assert not hasattr(w, "fringe_toggle")
    # Apply starts disabled — main_window enables it once the (slow) split lands.
    assert w.apply_btn.isEnabled() is False
    w.apply_btn.setEnabled(True)
    w.apply_btn.click()
    assert applied.get("s") == 1.0, "Apply must perform the de-green, not nothing"


def test_green_removal_starts_at_zero(qtbot):
    """Measured 2026-08-15 on a real M 31 mosaic with no green in it: at
    strength 0.40 the stretched sky went from G/mean(R,B) 0.983 to 1.003, and at
    1.00 to 1.027. SCNR only clamps green where it EXCEEDS the red/blue average,
    which in clean data happens only in the noise — so it shaves the upper half
    of green's fluctuations, skews the distribution the stretch neutralises on,
    and makes the sky greener. A default that harms the common case is the wrong
    default, and the control is already labelled optional."""
    w = build_panel(_stage("remove_green"))
    qtbot.addWidget(w)
    assert w.rg_slider.value() == 0


def test_background_panel_offers_to_show_what_was_removed(qtbot):
    """A background model you cannot see is a step you have to take on trust.
    Seeing it is how a user tells a real gradient from the fit eating the faint
    outer parts of their object — which looks merely 'a bit flat' in the
    corrected image and is obvious in the model."""
    w = build_panel(_stage("background"))
    qtbot.addWidget(w)
    assert hasattr(w, "show_model_check")
    assert not w.show_model_check.isChecked()
    assert not w.show_model_check.isEnabled(), "nothing to show until it has run"


def test_the_show_model_toggle_reports_state(qtbot):
    seen = []
    w = build_panel(_stage("background"), on_show_model=seen.append)
    qtbot.addWidget(w)
    w.show_model_check.setEnabled(True)
    w.show_model_check.setChecked(True)
    assert seen == [True]
    w.show_model_check.setChecked(False)
    assert seen == [True, False]


def test_colour_tint_sliders_are_bipolar_and_centred(qtbot):
    """Centred at 0 with equal travel each way: this is a cast control, not a
    strength dial. Double-click resets, which ResetSlider gives us."""
    panel = build_panel(_stage("color"))
    qtbot.addWidget(panel)
    for name in ("tint_slider", "temp_slider"):
        sl = getattr(panel, name)
        assert sl.minimum() == -100 and sl.maximum() == 100, name
        assert sl.value() == 0, f"{name} must default to no change"


def test_colour_tint_has_its_own_apply_below_apply_color(qtbot):
    """Calibrate first, then nudge. The tint is committed by its OWN button.

    It was bundled into Apply Color at first, which meant the sliders could only
    take effect by re-running the calibration — so after applying Color they
    appeared dead. Its own button, placed after Apply Color, matches how the
    tool is actually used.
    """
    sent = []
    panel = build_panel(_stage("color"), apply_enabled=True,
                        on_apply_tint=lambda t, w: sent.append((t, w)))
    qtbot.addWidget(panel)
    panel.tint_slider.setValue(-40)
    panel.temp_slider.setValue(25)
    panel.apply_tint_btn.click()
    assert sent == [pytest.approx((-0.40, 0.25))]


def test_apply_color_no_longer_carries_the_tint(qtbot):
    """Apply Color must send calibration settings only, so pressing it does not
    silently re-apply or discard a tint the user set afterwards."""
    captured = []
    panel = build_panel(_stage("color"), apply_enabled=True,
                        on_apply=lambda opt: captured.append(opt))
    qtbot.addWidget(panel)
    panel.tint_slider.setValue(-80)
    panel.apply_btn.click()
    assert captured and not hasattr(captured[-1], "tint")


def test_zero_tint_is_bit_identical(qtbot):
    """A user who never touches the sliders must get exactly the old behaviour.

    Assert-UNCHANGED, not 'close enough': a gain of 0.999 would pass a tolerance
    test while recolouring every image ever processed.
    """
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.tint_step import TintStep
    rng = np.random.default_rng(4)
    data = (rng.random((24, 24, 3)) * 0.4 + 0.05).astype(np.float32)
    out = TintStep().apply(AstroImage(data.copy(), is_linear=True, metadata={}), (0.0, 0.0))
    assert np.array_equal(out.data, data)


def test_reset_step_sits_below_the_compare_hint_behind_a_rule(qtbot):
    """Moved 2026-09-13. It sat directly under Apply, where Andreas read it as
    part of the tool: "now they risk reading like they are part of the tool".
    It is recovery, not a parameter.

    Asserted by ORDER in the layout rather than by pixel position, which is the
    part that carries the meaning: whatever the step's controls are, Reset comes
    after the step's own affordances and after a divider.
    """
    from PySide6.QtWidgets import QFrame
    w = build_panel(_stage("stretch"), on_apply=lambda v: None,
                    on_reset_step=lambda: None)
    qtbot.addWidget(w)
    lay = w.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count())]

    i_apply = order.index(w.apply_btn)
    i_hint = order.index(w.compare_hint)
    i_reset = order.index(w.reset_step_btn)
    rules = [x for x in order if isinstance(x, QFrame) and x.objectName() == "panelRule"]
    assert rules, "no divider separates Reset from the tool"
    i_rule = order.index(rules[-1])

    assert i_apply < i_hint < i_rule < i_reset, (
        "Reset must come after Apply, after the compare hint, and after a rule")


def test_import_and_export_have_no_reset_and_no_stray_rule(qtbot):
    """Neither can reset — Import has nothing committed and the toolbar Reset
    owns that; Export commits nothing. The divider must not appear on its own."""
    from PySide6.QtWidgets import QFrame
    for sid in ("load", "export"):
        w = build_panel(_stage(sid))
        qtbot.addWidget(w)
        assert w.reset_step_btn is None, sid
        lay = w.layout()
        rules = [lay.itemAt(i).widget() for i in range(lay.count())]
        assert not [r for r in rules
                    if isinstance(r, QFrame) and r.objectName() == "panelRule"], (
            f"{sid}: a divider with nothing under it")
