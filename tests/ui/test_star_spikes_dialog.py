import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.star_spikes_dialog import StarSpikesDialog  # noqa: E402


def _img():
    # a bright dot on a dark field so detection finds a star
    a = np.zeros((64, 64, 3), np.float32)
    a[20, 40] = 1.0
    a[19:22, 39:42] = 0.9
    return AstroImage(a, is_linear=False)


def test_dialog_builds_and_detects(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    assert d.length_slider.value() == 0
    assert d.intensity_slider.value() == 100  # full strength by default
    assert d.stars_slider.value() == 6
    assert len(d._stars) >= 1                 # detected on construction


def test_intensity_slider_dims_the_spikes(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.length_slider.setValue(80)
    d._render_preview()
    full = d.result().data.copy()
    d.intensity_slider.setValue(40)
    d._render_preview()
    dimmed = d.result().data
    # same spikes, fainter — less deviation from the base than at full strength
    base = d._base.data
    assert np.abs(dimmed - base).sum() < np.abs(full - base).sum()
    assert not np.allclose(dimmed, base)      # still visibly present


def test_slider_change_renders_preview(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.length_slider.setValue(60)
    d._render_preview()
    assert d.preview.has_image()
    # length 0 -> result is the untouched base; length > 0 -> changed
    changed = d.result().data
    assert not np.allclose(changed, d._base.data)


def test_apply_calls_back_with_result(qtbot):
    got = []
    d = StarSpikesDialog(_img(), on_apply=got.append)
    qtbot.addWidget(d)
    d.length_slider.setValue(50)
    d._render_preview()
    d.apply_btn.click()
    assert got and isinstance(got[0], AstroImage)
    assert got[0].data.shape == (64, 64, 3)
