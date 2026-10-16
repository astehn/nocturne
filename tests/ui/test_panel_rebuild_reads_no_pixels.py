"""A panel rebuild reads no picture: the Crop panel loaded the whole image
twice for its width and height, and Stretch loaded it once for one boolean —
on the UI thread, ~0.3 s a load on a 33 MP drizzle (2026-10-16). Project keeps
both per state (shape_at, is_linear_at)."""
import numpy as np
from astropy.io import fits

from nocturne.history.project import Project
from tests.ui.test_main_window import _make_fits, _window


def _wide_fits(tmp_path):
    """Not square, so a swapped width and height cannot pass."""
    p = tmp_path / "wide.fits"
    fits.PrimaryHDU((np.random.rand(3, 20, 32) * 1000).astype(np.uint16)).writeto(str(p))
    return str(p)


def _count_loads(monkeypatch):
    calls = []
    real = Project._load

    def spy(self, index):
        calls.append(index)
        return real(self, index)
    monkeypatch.setattr(Project, "_load", spy)
    return calls


def test_the_crop_panels_picture_ratio_reads_no_pixels(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_wide_fits(tmp_path))
    win._go_to_id("crop")
    expected = 32 / 20
    calls = _count_loads(monkeypatch)
    assert win._picture_ratio() == expected
    assert calls == []


def test_the_stretch_controls_sync_reads_no_pixels(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    visual = getattr(win._panel, "visual_btn", None)
    assert visual is not None
    calls = _count_loads(monkeypatch)
    win._sync_step_controls()
    assert calls == []
    assert visual.isEnabled()           # still linear: the picker is offered
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("stretch")
    calls.clear()
    win._sync_step_controls()
    assert calls == []
    assert not win._panel.visual_btn.isEnabled()   # stretched: no second stretch
