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


# --- review 2026-10-05: nothing prepared only on entry may be final ------------

def _replay(monkeypatch, base, option):
    """What export, batch and a recipe produce for this option."""
    monkeypatch.setattr("nocturne.steps.star_split.resolve_star_split",
                        lambda img, rc, runner=None: _layers(img)[:2])
    return SaturationStep().apply(base, option).data


def _counting(qtbot, tmp_path, monkeypatch, fail_first=False):
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")
    calls = {"split": 0}

    def split(self, base):
        calls["split"] += 1
        if fail_first and calls["split"] == 1:
            raise RuntimeError("boom")
        return _layers(base)
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", split)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._splits.clear()
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    return win, calls


def test_a_trim_under_the_step_prepares_again_and_apply_matches_export(qtbot, tmp_path, monkeypatch):
    win, calls = _counting(qtbot, tmp_path, monkeypatch)
    win._go_to_id("saturation")
    assert calls["split"] == 1

    class Trim:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def bounds(self): return (2, 20, 2, 20)
    monkeypatch.setattr(mw, "TrimDialog", Trim)
    win._trim()
    base = win._preview_base("saturation")
    assert not win._sat_ready(base), "fixture: the base changed under the step"
    win._panel.neb_slider.setValue(60)
    assert calls["split"] == 2, "the Nebula slider prepares the new base"
    assert win._sat_ready(base)
    win._apply_saturation(0.5, 0.6)
    assert np.array_equal(win.project.current().data, _replay(monkeypatch, base, (0.5, 0.6)))


def test_a_failed_entry_split_is_retried_and_apply_never_records_a_missing_boost(qtbot, tmp_path, monkeypatch):
    win, calls = _counting(qtbot, tmp_path, monkeypatch, fail_first=True)
    win._go_to_id("saturation")
    assert calls["split"] == 1 and win._sat_layers is None, "fixture: the entry split failed"
    base = win._preview_base("saturation")
    n = len(win.project.entries())
    # Apply straight away: refused (it would record a boost not in the picture),
    # and the split is started again.
    win._apply_saturation(0.5, 0.6)
    assert len(win.project.entries()) == n, "nothing committed without the boost"
    assert calls["split"] == 2 and win._sat_ready(base)
    win._apply_saturation(0.5, 0.6)
    assert np.array_equal(win.project.current().data, _replay(monkeypatch, base, (0.5, 0.6)))


def test_a_failed_entry_split_is_retried_by_the_nebula_slider(qtbot, tmp_path, monkeypatch):
    win, calls = _counting(qtbot, tmp_path, monkeypatch, fail_first=True)
    win._go_to_id("saturation")
    win._panel.neb_slider.setValue(60)
    assert calls["split"] == 2 and win._sat_ready(win._preview_base("saturation"))


def test_global_saturation_alone_needs_no_split(qtbot, tmp_path, monkeypatch):
    win, calls = _counting(qtbot, tmp_path, monkeypatch, fail_first=True)
    win._go_to_id("saturation")
    base = win._preview_base("saturation")
    win._apply_saturation(0.7, 0.0)
    assert calls["split"] == 1, "no retry for a step that does not boost"
    assert np.array_equal(win.project.current().data, _replay(monkeypatch, base, (0.7, 0.0)))


def test_a_rebuild_while_preparing_starts_no_second_split(qtbot, tmp_path, monkeypatch):
    """A project reopened at Saturation rebuilds the panel several times in a
    row; each rebuild started its own split (two StarNet2 runs at once)."""
    import threading
    win, calls = _counting(qtbot, tmp_path, monkeypatch)
    gate = threading.Event()

    def slow(self, base):
        calls["split"] += 1
        gate.wait(5)
        return _layers(base)
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", slow)
    win._async_enabled = True
    win._go_to_id("saturation")
    qtbot.wait(30)
    win._rebuild_panel()
    win._rebuild_panel()
    qtbot.wait(30)
    assert calls["split"] == 1 and len(win._running) == 1
    gate.set()
    qtbot.waitUntil(lambda: not win._running, timeout=5000)
    assert win._sat_ready(win._preview_base("saturation"))


def test_a_refused_apply_leaves_the_history_as_it_found_it(qtbot, tmp_path, monkeypatch):
    """Readiness was checked AFTER truncating: an existing Saturation commit
    vanished without a prompt and nothing replaced it (re-review 2026-10-05)."""
    win, calls = _counting(qtbot, tmp_path, monkeypatch)
    win._go_to_id("saturation")
    win._apply_saturation(0.7, 0.0)
    before = [(n, o) for n, o in win.project.entries()]
    assert before[-1][0] == "Saturation", "fixture"
    win._sat_layers = win._sat_mask = None            # the split is not ready now
    monkeypatch.setattr(win, "_prepare_saturation", lambda *a, **k: False)
    win._apply_saturation(0.5, 0.6)
    assert [(n, o) for n, o in win.project.entries()] == before


def test_a_mono_picture_never_names_the_last_pictures_star_tool(qtbot, tmp_path, monkeypatch):
    win, calls = _counting(qtbot, tmp_path, monkeypatch)
    win._go_to_id("saturation")
    assert win._sat_layers is not None, "fixture: the colour picture was prepared"
    win.open_image(AstroImage(np.full((32, 32), 0.3, np.float32), is_linear=False, metadata={}), "m")
    assert win._sat_layers is None and win._sat_mask is None
    assert "StarNet2" not in win._sat_log_option(0.5, 0.6)


def test_a_failed_split_is_retried_by_the_nebula_slider_only(qtbot, tmp_path, monkeypatch):
    """A broken StarX failed again on every touch of the step."""
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starx")
    calls = {"split": 0}

    def broken(self, base):
        calls["split"] += 1
        raise RuntimeError("StarXTerminator failed")
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", broken)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._splits.clear()
    win._go_to_id("saturation")
    assert calls["split"] == 1
    win._panel.neb_slider.setValue(40)
    assert calls["split"] == 2, "moving Nebula is a deliberate retry"
    for v in (55, 60, 65):
        win._panel.sat_slider.setValue(v)
    assert calls["split"] == 2, "the Saturation slider does not retry the split"
