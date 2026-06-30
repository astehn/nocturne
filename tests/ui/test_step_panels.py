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


def test_destination_panel_emits_choice(qtbot):
    got = []
    w = build_panel(_stage("destination"), on_destination=got.append)
    qtbot.addWidget(w)
    w.external_radio.setChecked(True)
    assert got[-1] == "external"


def test_crop_panel_emits_margin(qtbot):
    got = []
    w = build_panel(_stage("crop"), on_apply=got.append)
    qtbot.addWidget(w)
    w.margin_slider.setValue(10)
    w.apply_btn.click()
    assert got == [0.10]


def test_process_panel_background_options(qtbot):
    got = []
    w = build_panel(_stage("background"), on_apply=got.append)
    qtbot.addWidget(w)
    assert [w.option_box.itemText(i) for i in range(w.option_box.count())] == \
        ["off", "light", "strong"]
    w.option_box.setCurrentText("strong")
    w.apply_btn.click()
    assert got == ["strong"]


def test_auto_panel_emits_none(qtbot):
    got = []
    w = build_panel(_stage("color"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "auto"
    w.apply_btn.click()
    assert got == [None]


def test_stretch_panel_presets(qtbot):
    got = []
    w = build_panel(_stage("stretch"), on_apply=got.append)
    qtbot.addWidget(w)
    w.option_box.setCurrentText("punchy")
    w.apply_btn.click()
    assert got == ["punchy"]


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
    assert w.panel_kind == "export_external"
    assert w.fmt_box.model().item(1).isEnabled() is False


def test_export_panel_formats(qtbot):
    got = []
    w = build_panel(_stage("export"), on_export=got.append)
    qtbot.addWidget(w)
    w.fmt_box.setCurrentText("PNG")
    w.export_btn.click()
    assert got == ["PNG"]
