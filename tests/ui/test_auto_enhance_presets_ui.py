"""Auto Enhance presets in the window: the toolbar menu, the busy label, the
log lines, and failures shown in the warning channel."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton, QWidget  # noqa: E402

from tests.fake_tool import fake_tool
from tests.ui.test_main_window import _crop, _make_fits, _window  # noqa: E402


def _spy_presets(win, monkeypatch):
    seen = []
    real = win._auto_enhance
    monkeypatch.setattr(win, "_auto_enhance", lambda p="natural": seen.append(p) or real(p))
    return seen


def _entries(win):
    return {a.text(): a for a in win._auto_menu.actions()}


def _open(win):
    win._auto_menu.aboutToShow.emit()       # what the arrow does before it pops up


def test_the_menu_offers_three_presets_in_order(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    assert [a.text() for a in win._auto_menu.actions()] == ["Natural", "Vivid", "Gold and blue"]
    assert win._auto_enhance_act.menu() is win._auto_menu
    btn = win._toolbar.widgetForAction(win._auto_enhance_act)
    assert btn.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup


def test_the_click_still_runs_natural(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    seen = []
    real = mw.build_auto_plan
    monkeypatch.setattr(mw, "build_auto_plan",
                        lambda *a, **k: seen.append(k.get("preset")) or real(*a, **k))
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._toolbar.widgetForAction(win._auto_enhance_act).click()
    assert seen == ["natural"]


@pytest.mark.parametrize("text,preset,card", [("Natural", "natural", "L"),
                                              ("Vivid", "vivid", "L"),
                                              ("Gold and blue", "gold_blue", "LP")])
def test_each_menu_entry_runs_its_preset(qtbot, tmp_path, text, preset, card):
    import nocturne.ui.main_window as mw
    seen = []
    real = mw.build_auto_plan
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card=card))
    _crop(win)
    mw_build = lambda *a, **k: seen.append(k.get("preset")) or real(*a, **k)  # noqa: E731
    orig, mw.build_auto_plan = mw.build_auto_plan, mw_build
    try:
        _open(win)
        _entries(win)[text].trigger()
    finally:
        mw.build_auto_plan = orig
    assert seen == [preset]
    assert len(win.project.entries()) > 3


def test_gold_and_blue_is_disabled_on_broadband(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="IRCUT"))
    _crop(win)
    _open(win)
    gb = _entries(win)["Gold and blue"]
    assert not gb.isEnabled()
    assert gb.toolTip() == "For dual-band (LP filter) data"
    assert win._auto_menu.toolTipsVisible()
    assert _entries(win)["Natural"].isEnabled() and _entries(win)["Vivid"].isEnabled()


def test_gold_and_blue_is_enabled_on_lp_data_and_re_evaluated_each_open(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="LP"))
    _crop(win)
    _open(win)
    assert _entries(win)["Gold and blue"].isEnabled()
    # A different image opens: the next time the menu opens, it says so.
    (tmp_path / "b").mkdir()
    win.open_fits(_make_fits(tmp_path / "b", filter_card="IRCUT"))
    _crop(win)
    _open(win)
    assert not _entries(win)["Gold and blue"].isEnabled()


def test_gold_and_blue_is_disabled_with_no_image(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    _open(win)
    assert not _entries(win)["Gold and blue"].isEnabled()


def test_no_image_a_menu_entry_opens_one_and_carries_its_preset(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    carried = []

    def choose():
        carried.append(win._after_open)
    monkeypatch.setattr(win, "_choose_fits", choose)
    seen = _spy_presets(win, monkeypatch)
    win._auto_enhance("vivid")
    assert seen == ["vivid"] and carried and carried[0] is not None
    carried[0]()                             # the image arrived: carry on
    assert seen == ["vivid", "vivid"]


def test_busy_label_names_the_preset(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    labels = []
    real = win._run_busy
    monkeypatch.setattr(win, "_run_busy",
                        lambda work, on_result, label, *a, **k:
                        labels.append(label) or real(work, on_result, label, *a, **k))
    win._auto_enhance("vivid")
    assert labels == ["Auto-enhancing (Vivid)…"]


def test_progress_label_keeps_the_preset(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win._auto_preset_name = "Vivid"
    win._on_auto_progress(3, 9, "Stretch")
    assert win._busy_label_text == "Auto-enhancing (Vivid) — Stretch (3/9)…"


def test_every_log_line_names_the_preset_and_noise_its_engine(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    before = win.log_panel.text()
    win._auto_enhance("vivid")
    new = win.log_panel.text()[len(before):]
    lines = [ln for ln in new.splitlines() if "Auto Enhance" in ln]
    n_steps = len(win.project.entries()) - 1           # less the user's crop
    assert len(lines) == n_steps, new
    assert all(ln.endswith("— Auto Enhance (Vivid)") for ln in lines), lines
    noise = [ln for ln in lines if "Noise Reduction" in ln]
    assert noise and "(strong (built-in))" in noise[0], noise


def test_summary_names_preset_count_and_what_was_left_out(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    n = len(win.project.entries()) - 1
    assert f"Auto-enhanced (Natural) — {n} steps." in out, out
    assert "Background and Deconvolution were left out" in out, out
    assert "Install GraXpert" not in out          # denoise no longer uses it
    assert win._warning.text() == ""               # nothing failed


def test_a_failed_stage_is_a_warning_and_the_others_still_record(qtbot, tmp_path, monkeypatch):
    from nocturne.steps.local_contrast import LocalContrastStep

    def boom(self, img, option):
        raise RuntimeError("tool exploded\nsecond line")
    monkeypatch.setattr(LocalContrastStep, "apply", boom)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance("vivid")
    names = [n for n, _o in win.project.entries()]
    assert "Local Contrast" not in names
    assert names[-1] == "Star Reduction"           # the stage after it still ran
    done = len(names) - 1
    assert win._warning.text() == (f"Auto Enhance (Vivid): {done} of {done + 1} steps "
                                   "— Local Contrast failed: tool exploded")


def test_several_failures_are_named_together(qtbot, tmp_path, monkeypatch):
    from nocturne.steps.local_contrast import LocalContrastStep
    from nocturne.steps.star_reduction import StarReductionStep

    def boom(self, img, option):
        raise RuntimeError("no")
    monkeypatch.setattr(LocalContrastStep, "apply", boom)
    monkeypatch.setattr(StarReductionStep, "apply", boom)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance()
    w = win._warning.text()
    assert w.startswith("Auto Enhance (Natural): ")
    assert "Local Contrast and Star Reduction failed" in w, w


def test_a_colour_fallback_message_reaches_the_summary(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.settings.astap_path = "/bin/echo"   # photometric planned; the solve cannot work
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    assert "used sky balance" in out, out


# --- the overflow menu ---------------------------------------------------

def test_overflow_mirrors_a_tools_menu_as_a_submenu(qtbot):
    """A tool with a menu that leaves the bar keeps its menu in More."""
    from nocturne.ui.toolbar_overflow import ToolbarOverflow
    host = QWidget()
    qtbot.addWidget(host)
    tb = QToolBar(host)
    act = tb.addAction("Auto Enhance")
    menu = QMenu(tb)
    for t in ("Natural", "Vivid", "Gold and blue"):
        menu.addAction(t)
    act.setMenu(menu)
    more = QToolButton()
    more_act = tb.addWidget(more)
    ov = ToolbarOverflow(tb, [act], more, more_act, budget=lambda: 0, watch=host)
    proxy = ov.proxy_for(act)
    assert proxy.menu() is menu
    assert [a.text() for a in proxy.menu().actions()] == ["Natural", "Vivid", "Gold and blue"]


def test_auto_enhance_never_leaves_the_bar(qtbot, tmp_path):
    """Why the overflow has no Auto Enhance entry of its own: it is in the
    never-leave set (toolbar_overflow's docstring), so its arrow is always on
    the bar. Should that change, the mirror above carries the menu across."""
    win = _window(qtbot, tmp_path)
    win.resize(400, 600)
    win._overflow.relayout()
    assert win._auto_enhance_act in win._toolbar.actions()
    assert win._auto_enhance_act not in win._overflow._proxy


def test_the_overflow_measures_the_arrow(qtbot, tmp_path):
    """The bar is made to fit by measuring tools off the bar on a probe; a
    probe without the arrow priced Auto Enhance 16 px short."""
    from PySide6.QtCore import Qt
    win = _window(qtbot, tmp_path)
    win.resize(1800, 800)
    win.show()
    qtbot.wait(20)
    ov, act = win._overflow, win._auto_enhance_act
    w = win._toolbar.widgetForAction(act)
    text = win._toolbar.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly
    real = w.sizeHint().width()
    w.setVisible(False)                    # forces the probe
    try:
        probed = ov._width(act, text)
    finally:
        w.setVisible(True)
    assert probed == real


# --- whole-branch review fixes -------------------------------------------

def test_the_menu_check_reads_metadata_not_the_frame(qtbot, tmp_path, monkeypatch):
    """Every opening of the menu asks whether the image is dual-band; through
    project.current() that reloaded the full frame on the UI thread each time."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="LP"))
    _crop(win)
    loads = []
    real = win.project.current
    monkeypatch.setattr(win.project, "current", lambda: loads.append(1) or real())
    _open(win)
    assert loads == []
    assert _entries(win)["Gold and blue"].isEnabled()


def _session_lines(monkeypatch):
    from nocturne.core import sessionlog
    lines = []
    monkeypatch.setattr(sessionlog, "write", lambda line: lines.append(line))
    return lines


def test_every_stage_reaches_the_session_log(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    lines = _session_lines(monkeypatch)
    win._auto_enhance("vivid")
    steps = [ln for ln in lines if ln.startswith("step  ")]
    names = [n for n, _o in win.project.entries()][1:]
    assert len(steps) == len(names), lines
    assert all(ln.endswith("— Auto Enhance (Vivid)") for ln in steps), steps
    assert [ln[len("step  "):].split(" (")[0].split(" —")[0] for ln in steps] == names
    assert any(ln.startswith("step  Noise Reduction (strong (built-in))") for ln in steps), steps


def test_a_failed_stage_is_an_error_in_the_session_log_with_the_whole_message(
        qtbot, tmp_path, monkeypatch):
    from nocturne.steps.local_contrast import LocalContrastStep

    def boom(self, img, option):
        raise RuntimeError("tool exploded\nsecond line of the trace")
    monkeypatch.setattr(LocalContrastStep, "apply", boom)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    lines = _session_lines(monkeypatch)
    win._auto_enhance("vivid")
    errors = [ln for ln in lines if ln.startswith("ERROR ")]
    assert len(errors) == 1, lines
    assert errors[0].startswith("ERROR Auto Enhance (Vivid): Local Contrast failed\n")
    assert "RuntimeError: tool exploded\nsecond line of the trace" in errors[0]
    # The warning keeps the short reason.
    assert win._warning.text().endswith("Local Contrast failed: tool exploded")


def test_gold_and_blue_on_broadband_changes_nothing(qtbot, tmp_path, monkeypatch):
    """Reached only if the image changes under an open menu — but then nothing
    may be discarded: the warning, and the history exactly as it was."""
    from PySide6.QtWidgets import QMessageBox
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path, filter_card="IRCUT"))
    _crop(win)
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Yes)
    win._auto_enhance("natural")                      # processing beyond the crop
    asked.clear()
    entries, position = list(win.project.entries()), win.project.position
    assert len(entries) > 2
    win._auto_enhance("gold_blue")
    assert win._warning.text() == "Gold and blue is for dual-band (LP filter) data."
    assert list(win.project.entries()) == entries
    assert win.project.position == position
    assert asked == []


def test_the_left_out_sentence_is_the_plan_that_ran(qtbot, tmp_path, monkeypatch):
    """Settings can change while the chain runs (minutes, with external tools);
    the summary describes the plan that was built, not the settings now."""
    exe = tmp_path / "graxpert"
    exe = fake_tool(exe, "#!/bin/sh\n")
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    _crop(win)
    real = win._run_busy

    def run_busy(work, on_result, *a, **k):
        win.settings.graxpert_path = str(exe)         # set up mid-run
        return real(work, on_result, *a, **k)
    monkeypatch.setattr(win, "_run_busy", run_busy)
    win._auto_enhance()
    out = win.output_panel.toPlainText()
    assert "Background and Deconvolution were left out: GraXpert and RC-Astro aren't set up." \
        in out, out
    assert "Background" not in [n for n, _o in win.project.entries()]
