"""Starless Levels opens its window first and splits inside it, like Narrowband,
and reuses a split the session already has (2026-10-04 spec R4).

The real modal `.exec()` would block a headless run for ever, so it is patched
to show the dialog, wait for its layers, act, and close — the dialog's own
split path still runs for real, on the pool, through `_split_tagged`.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog
from tests.ui.test_main_window import _stretched_window


def _fake_split(win, monkeypatch):
    """Count every split. StarNet2 is not installed in tests, so the fake
    stands in for the engine — same shape and tag contract as `_split_tagged`."""
    calls = []

    def _tagged(img):
        calls.append(1)
        h, w = img.data.shape[:2]
        starless = AstroImage(np.full((h, w, 3), 0.3, np.float32), is_linear=False)
        stars = np.zeros((h, w, 3), np.float32)
        stars[h // 2, w // 2] = 0.9
        return starless, AstroImage(stars, is_linear=False), "StarNet2"

    monkeypatch.setattr(win, "_split_tagged", _tagged)
    return calls


def _patch_exec(qtbot, monkeypatch, win, apply=False):
    """Record what the window looked like while the dialog was up."""
    seen = []

    def fake_exec(self):
        rec = {"layers_at_exec": self.has_layers(), "busy": [win._busy]}
        self.show()
        qtbot.waitUntil(self.has_layers, timeout=5000)
        rec["busy"].append(win._busy)
        if apply:
            self.handles.set_range(0.1, 0.8)
            self.ok_btn.click()
        else:
            self.reject()
        rec["busy"].append(win._busy)
        seen.append(rec)
        return self.result()

    monkeypatch.setattr(StarlessLevelsDialog, "exec", fake_exec)
    return seen


def test_the_window_opens_before_the_split_finishes(qtbot, tmp_path, monkeypatch):
    win = _stretched_window(qtbot, tmp_path)
    calls = _fake_split(win, monkeypatch)
    seen = _patch_exec(qtbot, monkeypatch, win)
    win._open_starless_levels()
    assert len(seen) == 1
    assert seen[0]["layers_at_exec"] is False, \
        "the dialog only appeared once the split was done — it split first again"
    assert len(calls) == 1


def test_a_second_open_does_not_split_again(qtbot, tmp_path, monkeypatch):
    """Captured as a count and asserted UNCHANGED across the second open."""
    win = _stretched_window(qtbot, tmp_path)
    calls = _fake_split(win, monkeypatch)
    seen = _patch_exec(qtbot, monkeypatch, win)
    win._open_starless_levels()
    assert len(seen) == 1
    after_first = len(calls)
    assert after_first == 1, "the first open did not split at all"
    win._open_starless_levels()
    assert len(seen) == 2, "the second open never reached the dialog"
    assert len(calls) == after_first, "the second open split the same pixels again"
    assert seen[1]["layers_at_exec"] is True, "the cached split was not handed in"


def test_a_split_another_tool_made_is_reused(qtbot, tmp_path, monkeypatch):
    win = _stretched_window(qtbot, tmp_path)
    calls = _fake_split(win, monkeypatch)
    base = win.project.current()
    sl, st, _ = win._split_tagged(base)
    win._remember_split(base, sl, st, "StarX")
    before = len(calls)
    seen = _patch_exec(qtbot, monkeypatch, win, apply=True)
    win._open_starless_levels()
    assert len(calls) == before
    assert seen[0]["layers_at_exec"] is True
    # The log names the engine that really made the split it used.
    text = win.log_panel.toPlainText() if not hasattr(win.log_panel, "entries") \
        else "\n".join(win.log_panel.entries())
    assert "(StarX)" in text, text


def test_applying_still_records_the_step(qtbot, tmp_path, monkeypatch):
    """Guards the old silent no-op: `_busy` still True while `.exec()` ran made
    `_apply_starless_levels`'s own guard swallow the result."""
    win = _stretched_window(qtbot, tmp_path)
    _fake_split(win, monkeypatch)
    seen = _patch_exec(qtbot, monkeypatch, win, apply=True)
    entries_before = [name for name, _ in win.project.entries()]
    win._open_starless_levels()
    assert len(seen) == 1
    entries_after = [name for name, _ in win.project.entries()]
    assert entries_after[:len(entries_before)] == entries_before
    assert entries_after[len(entries_before):] == ["Starless Levels"]
    assert win.project.entries()[-1][1] == pytest.approx((0.1, 0.8))
    text = win.log_panel.toPlainText() if not hasattr(win.log_panel, "entries") \
        else "\n".join(win.log_panel.entries())
    assert "(StarNet2)" in text, text


def test_no_right_column_busy_for_the_split(qtbot, tmp_path, monkeypatch):
    """The split runs inside the dialog, never through `_run_busy`."""
    win = _stretched_window(qtbot, tmp_path)
    _fake_split(win, monkeypatch)
    ran_busy = []
    real = win._run_busy
    monkeypatch.setattr(win, "_run_busy",
                        lambda *a, **k: (ran_busy.append(a), real(*a, **k))[1])
    seen = _patch_exec(qtbot, monkeypatch, win, apply=True)
    win._open_starless_levels()
    assert len(seen) == 1
    assert seen[0]["busy"] == [False, False, False]
    assert ran_busy == []
