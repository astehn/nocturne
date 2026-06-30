import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from seestar_processor.ui.main_window import MainWindow  # noqa: E402


def test_open_and_stretch_updates_preview(qtbot, tmp_path):
    # synthetic Seestar-like color FITS
    arr = (np.random.rand(3, 32, 32) * 1000).astype(np.uint16)
    fpath = tmp_path / "stack.fits"
    fits.PrimaryHDU(arr).writeto(str(fpath))

    win = MainWindow(settings_path=str(tmp_path / "settings.json"))
    qtbot.addWidget(win)
    win.open_fits(str(fpath))
    assert win.project is not None
    assert win.project.current().is_linear is True

    win.apply_step(win.stretch_step, "Medium")
    assert win.project.current().is_linear is False
    assert win.preview_label.pixmap() is not None
