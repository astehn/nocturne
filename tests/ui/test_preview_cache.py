"""Recover Core and Local Contrast recomputed the whole effect on every slider
tick — 6.7 s and 0.9 s on a 33 MP drizzled master, almost all of it a blur
(resp. CLAHE) of luminance that the slider does not change (measured
2026-10-06). The preview now computes that once per base. The picture must not
move: preview == Apply == the export/batch path, and a new base computes it
again."""
import numpy as np
import pytest

import nocturne.ui.main_window as mw
from nocturne.core.image import AstroImage
from nocturne.steps.local_contrast import LocalContrastStep
from nocturne.steps.recover_core import RecoverCoreStep
from tests.ui.test_main_window import _make_fits, _window

# stage id, prepare name in main_window, cache attribute, tick, render, step
_STEPS = [
    ("recover_core", "recover_prepare", "_recover_prep",
     "_on_recover_change", "_render_recover_preview", RecoverCoreStep),
    ("local_contrast", "lc_prepare", "_lc_prep",
     "_on_lc_change", "_render_lc_preview", LocalContrastStep),
]


def _bright_fits(tmp_path):
    """Bright enough after the stretch that Recover Core's highlight mask bites."""
    from astropy.io import fits
    rng = np.random.default_rng(3)
    arr = (rng.random((3, 40, 56)) * 1000).astype(np.uint16)
    arr[:, 10:30, 15:45] += 3000
    p = tmp_path / "bright.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _at(qtbot, tmp_path, monkeypatch, spec):
    stage, prep_name, _attr, *_ = spec
    calls = []
    real = getattr(mw, prep_name)

    def counted(img):
        calls.append(img.data.shape)
        return real(img)
    monkeypatch.setattr(mw, prep_name, counted)
    win = _window(qtbot, tmp_path)
    win.open_fits(_bright_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.6, "linked": True})
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    win._go_to_id(stage)
    return win, calls


def _tick(win, spec, amount):
    _s, _p, _a, on_change, render, _step = spec
    getattr(win, on_change)(amount)
    getattr(win, render)()
    return win._displayed.data.copy()


@pytest.mark.parametrize("spec", _STEPS, ids=[s[0] for s in _STEPS])
def test_ticks_prepare_once_per_base(qtbot, tmp_path, monkeypatch, spec):
    win, calls = _at(qtbot, tmp_path, monkeypatch, spec)
    _tick(win, spec, 0.0)
    assert calls == [], "a no-op preview needs nothing prepared"
    for amount in (0.2, 0.5, 0.8, 1.0):
        _tick(win, spec, amount)
    assert len(calls) == 1, "four ticks on one base prepare once"
    slot = win._prep_slots[_ATTR[spec[0]]]
    assert slot.held is not None
    win._go_to_id("curves")
    # Left behind, it held ~266 MB at 33 MP for nobody (review 2026-10-06).
    assert slot.held is None and slot.token is None, "leaving the step drops it"
    win._go_to_id(spec[0])
    _tick(win, spec, 0.4)
    assert len(calls) == 2, "a revisit prepares again"
    assert slot.held is not None


_ATTR = {"recover_core": "_recover_prep", "local_contrast": "_lc_prep"}


@pytest.mark.parametrize("spec", _STEPS, ids=[s[0] for s in _STEPS])
def test_preview_equals_apply_equals_the_export_path(qtbot, tmp_path, monkeypatch, spec):
    win, _calls = _at(qtbot, tmp_path, monkeypatch, spec)
    stage, *_rest, step_cls = spec
    base = win._preview_base(stage)
    for amount in (0.0, 0.2, 0.5, 1.0):
        preview = _tick(win, spec, amount)
        assert np.array_equal(preview, step_cls().apply(base, amount).data), amount
    assert not np.array_equal(preview, base.data), "fixture: the effect changes pixels"
    win.apply_current(0.5)
    assert np.array_equal(win.project.current().data,
                          step_cls().apply(base, 0.5).data)


@pytest.mark.parametrize("spec", _STEPS, ids=[s[0] for s in _STEPS])
def test_a_trim_under_the_step_prepares_again(qtbot, tmp_path, monkeypatch, spec):
    win, calls = _at(qtbot, tmp_path, monkeypatch, spec)
    stage, _p, attr, *_rest, step_cls = spec
    _tick(win, spec, 0.5)
    held = getattr(win, attr)
    assert held is not None and len(calls) == 1

    class Trim:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def bounds(self): return (2, 30, 3, 40)
    monkeypatch.setattr(mw, "TrimDialog", Trim)
    win._trim()
    win._go_to_id(stage)
    base = win._preview_base(stage)
    assert base.data.shape[:2] != (40, 56), "fixture: the base changed under the step"
    preview = _tick(win, spec, 0.5)
    assert len(calls) == 2 and calls[-1] == base.data.shape
    assert getattr(win, attr)[0] == win._sr_sig(base) != held[0]
    assert np.array_equal(preview, step_cls().apply(base, 0.5).data)


@pytest.mark.parametrize("spec", _STEPS, ids=[s[0] for s in _STEPS])
def test_an_earlier_step_reapplied_prepares_again(qtbot, tmp_path, monkeypatch, spec):
    """Same shape, different pixels: only the signature can tell them apart."""
    win, calls = _at(qtbot, tmp_path, monkeypatch, spec)
    stage, _p, attr, *_rest, step_cls = spec
    _tick(win, spec, 0.5)
    held = getattr(win, attr)
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id(stage)
    base = win._preview_base(stage)
    assert win._sr_sig(base) != held[0], "fixture: the base changed"
    preview = _tick(win, spec, 0.5)
    assert len(calls) == 2
    assert np.array_equal(preview, step_cls().apply(base, 0.5).data)


@pytest.mark.parametrize("spec", _STEPS, ids=[s[0] for s in _STEPS])
def test_a_new_image_drops_the_prepared_arrays(qtbot, tmp_path, monkeypatch, spec):
    win, calls = _at(qtbot, tmp_path, monkeypatch, spec)
    attr = spec[2]
    _tick(win, spec, 0.5)
    assert getattr(win, attr) is not None
    win.open_image(AstroImage(np.full((32, 32, 3), 0.7, np.float32),
                              is_linear=False, metadata={}), "next")
    assert getattr(win, attr) is None, "a full-size array outlived its picture"
