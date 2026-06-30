import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.pipeline import path_stages  # noqa: E402
from seestar_processor.ui.step_panels import build_panel  # noqa: E402


def _stage(stage_id, dest="in_app"):
    return next(s for s in path_stages(dest) if s.id == stage_id)


def test_import_panel_has_open_and_meta(qtbot):
    clicked = []
    w = build_panel(_stage("load"), on_open=lambda: clicked.append(True))
    qtbot.addWidget(w)
    assert w.panel_kind == "import"
    assert hasattr(w, "meta_label")


def test_destination_buttons_emit_choice(qtbot):
    got = []
    w = build_panel(_stage("destination"), on_destination=got.append)
    qtbot.addWidget(w)
    w.external_btn.click()
    w.in_app_btn.click()
    assert got == ["external", "in_app"]


def test_crop_panel_controls_and_apply(qtbot):
    applied = []
    changed = []
    w = build_panel(_stage("crop"), on_crop_apply=lambda: applied.append(True),
                    on_crop_change=changed.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "crop"
    w.aspect_box.setCurrentText("1:1")
    assert changed[-1] == "1:1"
    w.rotate_btn.click()
    assert w.rotate == 90
    w.flip_h_btn.setChecked(True)
    w.apply_btn.click()
    assert applied == [True]
    assert w.flip_h_btn.isChecked() is True
    assert not hasattr(w, "margin_slider")  # margin removed; box covers it


def test_background_off_enables_apply_without_graxpert(qtbot):
    w = build_panel(_stage("background"), on_apply=lambda o: None, apply_enabled=False)
    qtbot.addWidget(w)
    w.option_box.setCurrentText("off")
    assert w.apply_btn.isEnabled() is True
    w.option_box.setCurrentText("light")
    assert w.apply_btn.isEnabled() is False
    assert w.disabled_note.isHidden() is False


def test_auto_panel_emits_color_settings_with_green(qtbot):
    from seestar_processor.core.color import ColorSettings
    got = []
    w = build_panel(_stage("color"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "auto"
    w.remove_green_check.setChecked(True)
    w.apply_btn.click()
    assert len(got) == 1 and isinstance(got[0], ColorSettings)
    assert got[0].remove_green is True


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


def test_saturation_panel_emits_amount(qtbot):
    got = []
    w = build_panel(_stage("saturation"), on_apply=got.append)
    qtbot.addWidget(w)
    w.sat_slider.setValue(50)
    w.apply_btn.click()
    assert got == [0.50]


def test_export_external_split_disabled_without_rcastro(qtbot):
    w = build_panel(_stage("export_external", "external"), apply_enabled=False)
    qtbot.addWidget(w)
    assert w.fmt_box.model().item(1).isEnabled() is False


def test_export_panel_formats(qtbot):
    got = []
    w = build_panel(_stage("export"), on_export=got.append)
    qtbot.addWidget(w)
    w.fmt_box.setCurrentText("PNG")
    w.export_btn.click()
    assert got == ["PNG"]
