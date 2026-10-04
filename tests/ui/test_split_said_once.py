"""A step-entry star split is announced ONCE — in the right column, beside its
ring — not also inside the step's panel (consistency audit C5, 2026-09-25;
still live 2026-10-04, when the right column gained the ring)."""
import pytest

from tests.ui.test_main_window import _make_fits, _window


def _capture_busy(win, monkeypatch):
    seen = []
    monkeypatch.setattr(win, "_run_busy", lambda work, done, label, err, **kw: seen.append(label))
    return seen


def _stretched(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current(0.5)
    return win


def test_saturation(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("saturation")
    seen = _capture_busy(win, monkeypatch)
    win._on_sat_change(0.5, 0.6)
    assert seen == ["Separating stars…"], "fixture: a split was started"
    assert "Separating stars" not in win._panel.neb_status.text()


@pytest.mark.parametrize("stage,status", [("star_reduction", "sr_status"),
                                          ("green_fringe", "fringe_status")])
def test_entering_a_step_that_splits(qtbot, tmp_path, monkeypatch, stage, status):
    win = _stretched(qtbot, tmp_path)
    seen = _capture_busy(win, monkeypatch)
    win._splits.clear()
    win._go_to_id(stage)
    assert seen and seen[-1] in ("Separating stars…", "Building star mask…"), "fixture: work started"
    assert seen[-1] not in getattr(win._panel, status).text()
