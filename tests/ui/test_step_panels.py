import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton  # noqa: E402
from seestar_processor.ui.pipeline import PIPELINE  # noqa: E402
from seestar_processor.ui.step_panels import build_panel  # noqa: E402


def _stage(stage_id):
    return next(s for s in PIPELINE if s.id == stage_id)


def test_load_panel_has_open_button(qtbot):
    clicked = []
    w = build_panel(_stage("load"), on_open=lambda: clicked.append(True))
    qtbot.addWidget(w)
    assert w.panel_kind == "load"
    btn = w.findChild(QPushButton)
    btn.click()
    assert clicked == [True]


def test_process_panel_apply_passes_option(qtbot):
    got = []
    w = build_panel(_stage("background"), on_apply=got.append, option_default="Large")
    qtbot.addWidget(w)
    assert w.panel_kind == "process"
    assert w.option_box.currentText() == "Large"
    w.apply_btn.click()
    assert got == ["Large"]


def test_apply_disabled_when_requested(qtbot):
    w = build_panel(_stage("background"), on_apply=lambda o: None, apply_enabled=False)
    qtbot.addWidget(w)
    assert w.apply_btn.isEnabled() is False


def test_placeholder_panel(qtbot):
    w = build_panel(_stage("color"))
    qtbot.addWidget(w)
    assert w.panel_kind == "placeholder"


def test_crop_panel_emits_settings(qtbot):
    from seestar_processor.core.crop import CropSettings
    got = []
    w = build_panel(_stage("crop"), on_apply=got.append)
    qtbot.addWidget(w)
    assert w.panel_kind == "crop"
    w.aspect_box.setCurrentText("1:1")
    w.trim_box.setCurrentText("10%")
    w.rotate_box.setCurrentText("90°")
    w.flip_h_check.setChecked(True)
    w.apply_btn.click()
    assert len(got) == 1
    s = got[0]
    assert isinstance(s, CropSettings)
    assert s.aspect == "1:1" and s.trim == "10%" and s.rotate == 90
    assert s.flip_h is True and s.flip_v is False
