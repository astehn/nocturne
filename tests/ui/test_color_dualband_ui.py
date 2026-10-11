"""What the window says when photometric colour steps aside on dual-band data."""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.color import ColorSettings  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.steps.color import DUALBAND_MESSAGE  # noqa: E402

from tests.ui.test_main_window import _crop, _make_fits, _window  # noqa: E402


def test_auto_enhance_on_lp_data_says_it_stepped_aside(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.astap_path = "/bin/echo"      # photometric is planned; LP never solves
    win.open_fits(_make_fits(tmp_path, filter_card="LP"))
    _crop(win)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    assert "Auto-enhanced" in out and DUALBAND_MESSAGE in out, out


def test_auto_enhance_with_sky_balance_says_nothing_about_dual_band(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)            # no ASTAP: the plan asks for sky, nothing steps aside
    win.open_fits(_make_fits(tmp_path, filter_card="LP"))
    _crop(win)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    assert "Auto-enhanced" in out and DUALBAND_MESSAGE not in out


def test_busy_label_does_not_promise_a_calibration_that_will_step_aside(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    lp = AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True, metadata={"filter": "LP"})
    ir = AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True, metadata={"filter": "IRCUT"})
    photometric = ColorSettings(method="photometric")
    assert win._busy_label_for("color", photometric, lp) == "Balancing colour on the sky…"
    assert win._busy_label_for("color", photometric, ir) == "Calibrating colour…"
    assert win._busy_label_for("color", photometric) == "Calibrating colour…"
