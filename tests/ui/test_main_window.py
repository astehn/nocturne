import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def _make_fits(tmp_path):
    arr = (np.random.rand(3, 24, 24) * 1000).astype(np.uint16)
    p = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    return win


def test_open_fits_stays_on_import_with_metadata(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    assert win.project is not None
    assert win.current_stage_id() == "load"
    assert win._panel.panel_kind == "import"
    assert "24x24" in win._panel.meta_label.text()


def test_default_in_app_path_navigation(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    seq = ["destination", "crop", "background", "color", "stretch",
           "saturation", "noise_sharpen", "export"]
    for sid in seq:
        win.go_next()
        assert win.current_stage_id() == sid
    win.go_next()  # clamp
    assert win.current_stage_id() == "export"


def test_external_destination_changes_tail(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("destination")
    win.set_destination("external")
    ids = [s.id for s in win._stages]
    assert ids[-1] == "export_external"
    assert "saturation" not in ids
    win.go_next()
    assert win.current_stage_id() == "crop"


def test_apply_stretch_maps_preset_and_sets_nonlinear(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current("punchy")
    assert win.project.current().is_linear is False
    assert win.project.entries()[-1][0] == "Stretch"


def test_apply_color_with_none_option(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("color")
    win.apply_current(None)  # auto panel emits None
    assert win.project.entries()[-1][0] == "Color"


def test_apply_crop_with_params_changes_dimensions(qtbot, tmp_path):
    from seestar_processor.core.crop import CropParams
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("crop")
    win.apply_current(CropParams(bounds=(4, 20, 4, 20)))
    h, w, _ = win.project.current().data.shape
    assert (h, w) == (16, 16)


def test_step_for_types(qtbot, tmp_path):
    from seestar_processor.steps.crop import CropStep
    from seestar_processor.steps.saturation_step import SaturationStep
    from seestar_processor.steps.noise_sharpen import NoiseSharpenStep
    win = _window(qtbot, tmp_path)
    assert isinstance(win._step_for("crop"), CropStep)
    assert isinstance(win._step_for("saturation"), SaturationStep)
    assert isinstance(win._step_for("noise_sharpen"), NoiseSharpenStep)


def test_export_external_panel_split_gated(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("destination")
    win.set_destination("external")
    win._go_to_id("export_external")
    # no RC-Astro configured -> split (item 1) disabled
    assert win._panel.fmt_box.model().item(1).isEnabled() is False
