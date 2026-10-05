"""Opening an image or a project while standing on a step that separates stars
started a separation for the NEW picture (Andreas, 2026-10-05: on Import,
"Separating stars…"). open_image and the project load rebuilt the panel for
the step the window was on BEFORE moving to where the new picture belongs."""
import pytest

import nocturne.ui.main_window as mw
from tests.ui.test_main_window import _make_fits, _window


@pytest.fixture
def splits(monkeypatch):
    seen = []
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")
    monkeypatch.setattr(mw.MainWindow, "_split_tagged",
                        lambda self, base: seen.append(base.data.shape) or (base, base, "StarNet2"))
    return seen


def _on(qtbot, tmp_path, monkeypatch, stage):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    win._go_to_id(stage)
    return win


@pytest.mark.parametrize("stage", ["saturation", "green_fringe", "star_reduction"])
def test_opening_an_image_on_a_split_step_separates_nothing(qtbot, tmp_path, monkeypatch, splits, stage):
    win = _on(qtbot, tmp_path, monkeypatch, stage)
    n = len(splits)
    (tmp_path / "b").mkdir()
    win.open_fits(_make_fits(tmp_path / "b"))
    assert win.current_stage_id() == "load"
    assert len(splits) == n, "nothing separates on Import"


@pytest.mark.parametrize("stage", ["saturation", "green_fringe", "star_reduction"])
def test_opening_a_project_on_a_split_step_separates_only_for_where_it_lands(
        qtbot, tmp_path, monkeypatch, splits, stage):
    from nocturne.history.project_store import save_project
    win = _on(qtbot, tmp_path, monkeypatch, stage)
    path = str(tmp_path / "p.nocturne")
    (tmp_path / "b").mkdir()
    other = _window(qtbot, tmp_path / "b")
    other.open_fits(_make_fits(tmp_path / "b"))
    other._go_to_id("stretch")
    other.apply_current({"amount": 0.3, "linked": True})
    save_project(other.project, path, source_label="b.fits")     # lands after Stretch
    n = len(splits)
    win._open_project(path)
    assert win.current_stage_id() not in ("saturation", "green_fringe", "star_reduction")
    assert len(splits) == n
