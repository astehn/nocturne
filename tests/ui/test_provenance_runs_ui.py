"""Auto Enhance and a user preset name themselves beside every step they apply,
and the Provenance report the window opens says so (2026-10-17)."""
import pytest
pytest.importorskip("PySide6")

from nocturne.core.provenance import AUTO_ENHANCE, PRESET, run_origin  # noqa: E402
from tests.ui.test_main_window import _crop, _make_fits, _window  # noqa: E402
from tests.ui.test_preset_apply import _box, _choose, _setup  # noqa: E402


def _shown_report(win, monkeypatch) -> str:
    import nocturne.ui.main_window as mw
    seen = []

    class _Dialog:
        def __init__(self, report, *a, **k):
            seen.append(report)

        def exec(self):
            return 0
    monkeypatch.setattr(mw, "ProvenanceDialog", _Dialog)
    win._show_provenance()
    return seen[0]


def test_a_preset_names_itself_on_each_step_and_in_the_report(qtbot, tmp_path, monkeypatch):
    win, p = _setup(qtbot, tmp_path, name="Lagoon HOO")
    _choose(win, p)
    _box(win)
    win._apply_crop()
    names = [n for n, _ in win.project.entries()]
    assert names == ["Crop", "Stretch", "Levels", "Local Contrast", "Vibrance"]
    assert win.project.origins() == [None] + [run_origin(PRESET, "Lagoon HOO")] * 4
    report = _shown_report(win, monkeypatch)
    assert "_Steps 2–5 — from preset ‘Lagoon HOO’_" in report
    # A hand step after the run carries nothing.
    win._enhance("Soft Glow")
    assert win.project.entries()[-1][0] == "Soft Glow"
    assert win.project.origins()[-1] is None


def test_auto_enhance_names_its_preset_on_each_step(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance("vivid")
    entries = win.project.entries()
    assert entries[0][0] == "Crop" and len(entries) > 2
    assert win.project.origins() == [None] + [run_origin(AUTO_ENHANCE, "Vivid")] * (
        len(entries) - 1)
    report = _shown_report(win, monkeypatch)
    assert f"_Steps 2–{len(entries)} — applied by Auto Enhance (Vivid)_" in report
