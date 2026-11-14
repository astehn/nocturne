"""The Background step's Paint mask… route, wired into MainWindow."""
import numpy as np

from nocturne.recipe import serialize_option
from nocturne.ui import background_paint_dialog as bpd
from nocturne.ui import main_window as mw
from nocturne.ui.main_window import STEP_NAME, _PrecomputedStep
from tests.ui.test_main_window import _make_fits, _window

PAINTED = {"method": "painted", "amount": "strong",
           "strokes": [{"kind": "sky", "radius": 3.0,
                        "points": [[2.0, 2.0], [20.0, 2.0], [20.0, 20.0]]}]}


def _at_background(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("background")
    return win


def _dialog_applies(monkeypatch, option, seen=None):
    """exec() answers as if the user painted `option` and pressed Apply.
    `seen` collects the option each dialog was SEEDED with."""
    real_init = bpd.BackgroundPaintDialog.__init__

    def init(self, base, option=None, parent=None, on_apply=None):
        if seen is not None:
            seen.append(option)
        real_init(self, base, option, parent, on_apply)
    monkeypatch.setattr(bpd.BackgroundPaintDialog, "__init__", init)
    monkeypatch.setattr(bpd.BackgroundPaintDialog, "exec",
                        lambda self: self._on_apply(option) or 1)


def _dialog_cancels(monkeypatch, seen):
    monkeypatch.setattr(bpd.BackgroundPaintDialog, "exec",
                        lambda self: seen.append(self) or 0)


def test_paint_button_enabled_without_graxpert(qtbot, tmp_path):
    win = _at_background(qtbot, tmp_path)
    assert win._panel.apply_btn.isEnabled() is False      # no GraXpert in tests
    assert win._panel.paint_btn.isEnabled() is True


def test_paint_dialog_apply_commits_a_painted_entry(qtbot, tmp_path, monkeypatch):
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    name, opt = win.project.entries()[-1]
    assert name == STEP_NAME["background"]
    assert opt["method"] == "painted" and opt["strokes"] == PAINTED["strokes"]
    saved = serialize_option("background", opt, project=True)
    assert saved["strokes"] == PAINTED["strokes"]
    assert "Background (strong, painted)" in win.log_panel.text()
    assert win._step_state("background") == "applied"
    assert win._has_pending() is False
    assert win._panel.show_model_check.isEnabled() is True


def test_the_dialog_opens_on_the_pre_background_image(qtbot, tmp_path, monkeypatch):
    """Revisiting after a commit: the editor must see what the step will run on,
    not the image with the old Background already in it."""
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    bases = []
    monkeypatch.setattr(bpd.BackgroundPaintDialog, "exec",
                        lambda self: bases.append(self._base) or 0)
    win._panel.paint_btn.click()
    i = [n for n, _ in win.project.entries()].index(STEP_NAME["background"])
    assert np.array_equal(bases[0].data, win.project.state_at(i).data)
    assert not np.array_equal(bases[0].data, win.project.current().data)


def test_reopening_painted_step_seeds_dialog(qtbot, tmp_path, monkeypatch):
    win = _at_background(qtbot, tmp_path)
    seen = []
    _dialog_applies(monkeypatch, PAINTED, seen)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    win._go_to_id("color")
    win._go_to_id("background")
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    assert seen[0] is None                       # nothing painted yet
    assert seen[1]["strokes"] == PAINTED["strokes"]


def test_a_graxpert_commit_seeds_nothing(qtbot, tmp_path, monkeypatch):
    win = _at_background(qtbot, tmp_path)
    win.project.run_step(_PrecomputedStep(STEP_NAME["background"],
                                          win.project.current().copy()), "strong")
    win._go_to_id("color")
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "strong"
    seen = []
    _dialog_applies(monkeypatch, PAINTED, seen)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    assert seen == [None]


def test_old_off_project_opens_background_panel(qtbot, tmp_path):
    """"off" recorded nothing; such a project (and an "off" applied by an old
    path) opens the panel as an unapplied Background."""
    win = _at_background(qtbot, tmp_path)
    win.apply_current("off")                      # the branch stays, for safety
    assert STEP_NAME["background"] not in [n for n, _ in win.project.entries()]
    win._go_to_id("color")
    win._go_to_id("background")
    box = win._panel.option_box
    assert [box.itemText(i) for i in range(box.count())] == ["light", "strong"]
    assert win._panel.paint_btn.isEnabled() is True


def test_cancelling_the_dialog_changes_nothing(qtbot, tmp_path, monkeypatch):
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    before = list(win.project.entries())
    cur = win.project.current().data.copy()
    opened = []
    _dialog_cancels(monkeypatch, opened)
    win._panel.paint_btn.click()
    assert opened, "the dialog did not open"
    assert win.project.entries() == before
    assert np.array_equal(win.project.current().data, cur)


def test_later_work_is_asked_about_before_the_dialog_opens(qtbot, tmp_path, monkeypatch):
    """Ask once, up front — not after ten minutes of painting — and Cancel there
    opens nothing and discards nothing. Applying then does not ask again."""
    win = _at_background(qtbot, tmp_path)
    win.project.run_step(_PrecomputedStep(STEP_NAME["stretch"],
                                          win.project.current().copy()), 0.3)
    before = list(win.project.entries())
    asked = []
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: asked.append(names) or False)
    opened = []
    _dialog_cancels(monkeypatch, opened)
    win._panel.paint_btn.click()
    assert len(asked) == 1 and opened == []
    assert win.project.entries() == before

    asked.clear()
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: asked.append(names) or True)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    assert len(asked) == 1, "asked again on Apply"
    assert [n for n, _ in win.project.entries()][-1] == STEP_NAME["background"]
    assert STEP_NAME["stretch"] not in [n for n, _ in win.project.entries()]


def test_painted_route_skips_the_uncovered_frame_warning(qtbot, tmp_path, monkeypatch):
    """The painted fit masks black borders itself; the warning is GraXpert's."""
    import nocturne.core.crop as crop
    monkeypatch.setattr(crop, "uncovered_fraction", lambda img: 0.5)
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    assert "empty" not in win._warning.text()
    assert "empty" not in win.activity.text()


def test_the_commit_lands_on_the_worker_thread_too(qtbot, tmp_path, monkeypatch):
    """`_window` runs steps synchronously; the shipped app does not, and the
    dialog closes while the worker is still running."""
    win = _at_background(qtbot, tmp_path)
    win._async_enabled = True
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy and win.project.entries()
                    and win.project.entries()[-1][0] == STEP_NAME["background"],
                    timeout=10000)
    assert "Background (strong, painted)" in win.log_panel.text()
    assert win._step_state("background") == "applied"
    assert win._has_pending() is False


ALL_NEBULA = [{"kind": "nebula", "radius": 1e5, "points": [[0.0, 0.0]]}]


def _paint_and_press_apply(qtbot, monkeypatch, strokes, log):
    """exec() runs the REAL editor's Apply: strokes set, Apply pressed, and the
    fit allowed to land before exec returns what the dialog ended as."""
    def exec_(self):
        log.append(self)
        self._strokes = [dict(s) for s in strokes]
        self.apply_btn.click()
        qtbot.waitUntil(lambda: self.result() == self.DialogCode.Accepted
                        or "Too little sky" in self.status.text(), timeout=20000)
        return int(self.result() == self.DialogCode.Accepted)
    monkeypatch.setattr(bpd.BackgroundPaintDialog, "exec", exec_)


def test_a_failed_paint_apply_keeps_history_pixels_and_the_dialog(qtbot, tmp_path, monkeypatch):
    """All nebula: the fit fails. It used to close the editor and truncate
    first, losing the old Background and every later step."""
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, PAINTED)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    win.project.run_step(_PrecomputedStep(STEP_NAME["stretch"],
                                          win.project.current().copy()), 0.3)
    before = list(win.project.entries())
    cur = win.project.current().data.copy()
    monkeypatch.setattr(mw.MainWindow, "_ask_truncation",
                        lambda self, names, label, verb, **kw: True)
    opened = []
    _paint_and_press_apply(qtbot, monkeypatch, ALL_NEBULA, opened)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    assert opened, "the dialog did not open"
    assert win.project.entries() == before
    assert np.array_equal(win.project.current().data, cur)
    dlg = opened[0]
    assert "Too little sky" in dlg.status.text()
    assert dlg.result() != dlg.DialogCode.Accepted and not getattr(dlg, "_closed", False)


def test_a_paint_apply_commits_the_editors_own_result(qtbot, tmp_path, monkeypatch):
    """The fit runs once, in the editor; the window commits that image."""
    import nocturne.core.painted_background as pb
    real, calls = pb.apply_painted, []
    monkeypatch.setattr(pb, "apply_painted", lambda *a: calls.append(1) or real(*a))
    win = _at_background(qtbot, tmp_path)
    base = win.project.current().data.copy()
    opened = []
    _paint_and_press_apply(qtbot, monkeypatch, PAINTED["strokes"], opened)
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    name, opt = win.project.entries()[-1]
    assert name == STEP_NAME["background"] and opt == opened[0].option()
    assert len(calls) == 1
    from nocturne.core.image import AstroImage
    from nocturne.steps.background import BackgroundStep
    want = BackgroundStep(None).apply(AstroImage(base), opt)
    assert np.array_equal(win.project.current().data, want.data)
    assert "Background (strong, painted)" in win.log_panel.text()


def test_the_paint_dialog_is_deleted_after_it_closes(qtbot, tmp_path, monkeypatch):
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    win = _at_background(qtbot, tmp_path)
    opened = []
    _dialog_cancels(monkeypatch, opened)
    win._panel.paint_btn.click()
    assert opened
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert not shiboken6.isValid(opened[0])


def test_a_revisited_painted_light_reads_light(qtbot, tmp_path, monkeypatch):
    win = _at_background(qtbot, tmp_path)
    _dialog_applies(monkeypatch, dict(PAINTED, amount="light"))
    win._panel.paint_btn.click()
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)
    win._go_to_id("color")
    win._go_to_id("background")
    assert win._panel.option_box.currentText() == "light"
    assert win._has_pending() is False
