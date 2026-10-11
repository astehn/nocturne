"""Auto Enhance presets in the window: the toolbar menu, the busy label, the
log lines, and failures shown in the warning channel."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton, QWidget  # noqa: E402

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
