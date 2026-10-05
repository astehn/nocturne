"""Saturation's Nebula slider was "sluggish and difficult" (Andreas, 2026-10-05).
Measured: every tick rebuilt the nebula mask — 0.9 s of a 1.2 s tick at 8.3 MP,
7.4 s of 8.3 s at 33 MP, on the UI thread — and the star split only started on
the first raise of the slider. Now both are prepared on entering the step, the
mask once, and the picture is unchanged: preview == Apply == export/batch."""
import numpy as np

import nocturne.core.saturation as sat
import nocturne.ui.main_window as mw
from nocturne.core.image import AstroImage
from nocturne.steps.saturation_step import SaturationStep
from tests.ui.test_main_window import _make_fits, _window


def _layers(base):
    rng = np.random.default_rng(1)
    stars = (rng.random(base.data.shape) * 0.05).astype(np.float32)
    return (AstroImage(np.clip(base.data * 0.9, 0, 1).astype(np.float32), is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}), "StarNet2")


def _at_saturation(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")
    calls = {"split": 0, "mask": 0}

    def split(self, base):
        calls["split"] += 1
        return _layers(base)
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", split)
    real_mask = sat._nebula_mask

    def counted(lum):
        calls["mask"] += 1
        return real_mask(lum)
    monkeypatch.setattr(sat, "_nebula_mask", counted)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._splits.clear()
    win._go_to_id("saturation")
    return win, calls


def test_entering_prepares_the_split_and_the_mask_once(qtbot, tmp_path, monkeypatch):
    win, calls = _at_saturation(qtbot, tmp_path, monkeypatch)
    assert calls == {"split": 1, "mask": 1}, "both prepared on entry, before any nudge"
    for v in (20, 40, 60, 80):
        win._on_sat_change(0.6, v / 100.0)
        win._render_saturation_preview()
    assert calls == {"split": 1, "mask": 1}, "no tick rebuilds the mask or re-splits"
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    win._go_to_id("curves")
    win._go_to_id("saturation")
    assert calls == {"split": 1, "mask": 1}, "a revisit reuses both"


def test_the_preview_equals_apply_equals_the_export_path(qtbot, tmp_path, monkeypatch):
    win, _ = _at_saturation(qtbot, tmp_path, monkeypatch)
    base = win._preview_base("saturation")
    win._on_sat_change(0.7, 0.6)
    preview = win._sat_result(base, 0.7, 0.6).data.copy()
    # The export/batch path builds the mask itself, from the same split.
    step = SaturationStep()
    monkeypatch.setattr("nocturne.steps.star_split.resolve_star_split",
                        lambda img, rc, runner=None: _layers(img)[:2])
    exported = step.apply(base, (0.7, 0.6)).data
    assert np.array_equal(preview, exported)
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    win._apply_saturation(0.7, 0.6)
    assert np.array_equal(win.project.current().data, preview)


def test_a_cached_split_still_builds_the_mask_once(qtbot, tmp_path, monkeypatch):
    """Arriving with the split already made (by De-green Stars, say): no second
    separation, and the wait is named for what it is."""
    labels = []
    win, calls = _at_saturation(qtbot, tmp_path, monkeypatch)
    win._go_to_id("curves")
    win._sat_layers = win._sat_mask = None            # as if never prepared here
    real = win._run_busy
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, done, label, err, **k: labels.append(label) or real(work, done, label, err, **k))
    win._go_to_id("saturation")
    assert calls["split"] == 1, "the cached split is reused"
    assert calls["mask"] == 2 and labels == ["Preparing nebula mask…"]


def test_mono_prepares_nothing(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")
    started = []
    win = _window(qtbot, tmp_path)
    win.open_image(AstroImage(np.full((32, 32), 0.3, np.float32), is_linear=False, metadata={}), "m")
    monkeypatch.setattr(win, "_run_busy", lambda *a, **k: started.append(a[2]))
    win._go_to_id("saturation")
    assert started == []
