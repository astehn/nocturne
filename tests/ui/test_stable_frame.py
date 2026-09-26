"""The frame does not move. Within one window size, the canvas, the step list
and Next stay put on every step and in every state, and the window never
changes size — only a user resize may move them.

Andreas' 20 screenshots (2026-09-25) showed Next moving 718→755 px from
Import to Crop, 718→739 when "Not applied yet" appeared, and the window
itself growing ~115 px on Curves and never shrinking back. Spec:
docs/superpowers/specs/2026-09-25-stable-frame-design.md.

Offscreen is fine here: this asserts INVARIANCE, not absolute text widths.
"""
import pytest
from PySide6.QtCore import QPoint

from nocturne.stacking.stacker import StackOptions
from nocturne.ui.job_queue import JobQueue, StackJob
from tests.ui.test_main_window import _make_fits, _window

SIZES = [(1280, 720), (1280, 800), (1512, 982), (1920, 1080), (2560, 1440)]


class _FakeProc:
    returncode = None
    pid = 0


def _row_rect(r) -> tuple:
    return (r.x(), r.y(), r.width(), r.height())


def _geometry(win) -> dict:
    def rect(w):
        tl = w.mapTo(win, QPoint(0, 0))
        return (tl.x(), tl.y(), w.width(), w.height())
    return {
        "window": (win.width(), win.height()),
        "canvas": rect(win.image_view),
        # Visible too: a hidden widget keeps its last rect, so a rect alone
        # cannot see Next vanishing on Export (spec §2.8: it stays, disabled).
        "next": (rect(win._next_btn), win._next_btn.isVisible()),
        "stepper": rect(win.stepper),
        # side_panel.py's own contract: "every zone except the step panel has
        # a FIXED height on every step" — the status slot's size (not just
        # the widgets around it) must itself be invariant. Without this key,
        # an un-fixed status_slot is invisible to this test: its scroll area
        # sibling has stretch factor 1 and silently absorbs the size change,
        # so canvas/next/stepper/window never move even though the fixed
        # zone contract is broken.
        "status_slot": rect(win._side.status_slot),
        # The pinned zones of the consistent-panels template: the step's
        # title + description above the scroll, and the one action row below
        # it. Muscle memory again — Apply is in the same place on every step.
        "header_slot": rect(win._side.header_slot),
        "action_row": rect(win._side.action_slot),
        # Where the step's own controls actually begin on screen: the top of
        # the scroll VIEWPORT, not the description box's bottom edge or the
        # current panel's first control. The viewport boundary is the one
        # thing every stage shares — some panels' first control is a special
        # case (Import has no controls at all when nothing is open elsewhere,
        # Enhancements builds a grid, not a plain widget) — and it is what
        # visibly changes if the fixed header above it grows or shrinks, which
        # is exactly what a `desc_box` that follows its text would do: the
        # viewport is laid out immediately below header_slot in the same
        # QVBoxLayout (side_panel.py), so a taller header pushes it down.
        "controls_top": win._side.scroll.viewport().mapTo(win, QPoint(0, 0)).y(),
        # The jobs indicator, at the right end of the toolbar row in its own
        # bar: fixed there whatever it says, and always present (blank and
        # invisible while idle, never hidden).
        "jobs_indicator": (rect(win.jobs_indicator), win.jobs_indicator.isVisible()),
        # `_disabled_stages`' own contract (main_window.py): a stage the
        # current mode can't use stays LISTED and disabled so "the rows below
        # it never move" — the user's actual complaint was ROWS shifting
        # (Colour inserted -> everything below it moves down), not a row
        # count. A count, or the stepper's own rect (clamped to a 240px
        # floor by `ideal_height()` for any list longer than a handful of
        # rows, so it can't tell 17 rows from 18 apart either), both pass
        # silently under a reorder or a reflow that keeps the same number of
        # rows. Reading every row's own label and on-screen rect back is the
        # only check that catches a row moving, being replaced, or two rows
        # swapping.
        # The toolbar is muscle memory too. The jobs indicator heads it, so
        # an indicator that appears, or whose width follows its text, shifts
        # every button after it sideways — Open Image went x 16 -> 137 -> 219
        # by label length and jittered on every percent tick.
        "toolbar": tuple(
            (a.text(), win._toolbar.widgetForAction(a).mapTo(win, QPoint(0, 0)).x(),
             win._toolbar.widgetForAction(a).width())
            for a in win._toolbar.actions()
            if win._toolbar.widgetForAction(a) is not None
            and win._toolbar.widgetForAction(a).isVisible()
        ),
        "rows": tuple(
            (win.stepper.item(i).text(),
             _row_rect(win.stepper.visualItemRect(win.stepper.item(i))))
            for i in range(win.stepper.count())
        ),
    }


def _assert_every_row_shows(win, size):
    st = win.stepper
    last = st.visualItemRect(st.item(st.count() - 1))
    assert last.bottom() < st.viewport().height(), (
        f"{size}: last row ends at {last.bottom()}, viewport {st.viewport().height()}")
    assert st.verticalScrollBar().maximum() == 0


def _settle(qtbot):
    """A bare `qtbot.wait(20)` lets a deferred relayout land AFTER the read:
    Qt delivers a posted LayoutRequest on its own next pass through the event
    loop, not synchronously with whatever triggered it, so a single wait can
    race a resize that hasn't happened yet — the geometry read comes back
    looking stable when a broken layout just hasn't gotten around to moving
    it. Pump the queue on both sides of the wait so a LayoutRequest posted
    either before or during the wait is actually delivered before the caller
    reads geometry, and chain a second wait+pump in case delivering the first
    one posts another (a resize event can itself trigger a further layout
    pass). 20ms per pump keeps five sizes x many stages x many states in the
    same ballpark as before; this is about ordering, not raw duration.
    """
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    qtbot.wait(20)
    QApplication.processEvents()
    qtbot.wait(20)
    QApplication.processEvents()


def _states(win, qtbot):
    """Yield (label, geometry) for every state the spec names, on the
    CURRENT stage. Each state is undone before the next."""
    yield "arrived", _geometry(win)
    win._show_warning("RC-Astro failed — " + "a long wrapping message " * 12)
    _settle(qtbot)
    yield "warning", _geometry(win)
    win._clear_warning()
    win._set_busy(True, "Separating stars")
    win._show_busy_visuals()
    win._set_progress("", 3, 10)
    _settle(qtbot)
    yield "busy", _geometry(win)
    win._set_busy(False)
    win._toggle_help()
    _settle(qtbot)
    yield "help toggled", _geometry(win)
    win._toggle_help()
    _settle(qtbot)

    # A real job through the real queue (its process faked by the test):
    # the indicator's text changes on every percent tick, then becomes the
    # done notice, and none of it may move a toolbar button.
    q = win._job_queue
    job = StackJob("Andromeda Galaxy", StackOptions("average", 2.5, ["a", "b"], "/tmp/x.fits"))
    q.enqueue(job)
    for pct in (3, 42, 100):
        q.progress.emit(job, pct, "")
        _settle(qtbot)
        yield f"job running {pct}%", _geometry(win)
    q.finished.emit(job, {"output": ""})
    job.state = "done"; q._running = None; q.changed.emit()
    _settle(qtbot)
    yield "job notice", _geometry(win)
    win.jobs_indicator.notices.clear()
    win.jobs_indicator._refresh()

    for name in ("black_slider", "stretch_slider", "sat_slider",
                 "recover_slider", "rg_slider", "fringe_slider"):
        slider = getattr(win._panel, name, None)
        if slider is not None:
            v = slider.value()
            slider.setValue(v + 1 if v < slider.maximum() else v - 1)
            qtbot.wait(120)      # past the 90 ms preview debounce
            _settle(qtbot)
            # The state must really BE pending, through the same ApplyButton
            # the user presses — not just a label this generator happens to
            # attach to whatever geometry it read.
            btn = win._panel.apply_btn
            assert btn is not None and btn.state() == "pending", (
                f"{win.current_stage_id()}: moving {name} did not drive "
                f"Apply to pending (state={btn.state() if btn else None!r})")
            yield "pending", _geometry(win)
            slider.setValue(v)
            qtbot.wait(120)
            _settle(qtbot)
            break


def _with_linear_denoise(monkeypatch):
    """Andreas' machine has the Nocturne NR model installed, which adds the
    Linear Denoise step: 18 rows where the suite (conftest hides the model)
    sees 17. `_included_stages` asks `usable_external_models` at call time."""
    import nocturne.core.denoise_model as dm
    monkeypatch.setattr(dm, "usable_external_models",
                        lambda: [("v10", "/nonexistent/nocturne-nr-v10.onnx")])


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_nothing_moves_across_steps_and_states(qtbot, tmp_path, monkeypatch, size):
    _prove_nothing_moves(qtbot, tmp_path, monkeypatch, size, expect_rows=17)


def test_nothing_moves_with_linear_denoise_installed(qtbot, tmp_path, monkeypatch):
    _with_linear_denoise(monkeypatch)
    _prove_nothing_moves(qtbot, tmp_path, monkeypatch, (1280, 800), expect_rows=18)


def _prove_nothing_moves(qtbot, tmp_path, monkeypatch, size, expect_rows):
    monkeypatch.setattr(JobQueue, "_spawn", lambda self, job: _FakeProc())
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(*size)
    win.show()
    qtbot.waitExposed(win)
    _settle(qtbot)
    baseline = _geometry(win)
    assert win.stepper.count() == expect_rows, "precondition: the rows under test"
    # Every key — "rows" included — is compared against this ONE baseline,
    # taken on the first stage. A per-stage baseline for the rows once hid a
    # step list stuck at its 240 px floor that scrolled a different window of
    # rows into view on every step: the user's muscle memory is exactly what
    # moving rows break, so there is no stage change for which that is fine.
    # At every size here the whole list fits (Stepper.sizeHint asks for all
    # 17 rows; the activity box yields down to 72 px at 1280x720), so it must
    # have nothing to scroll either.
    _assert_every_row_shows(win, size)
    assert win.stepper.verticalScrollBar().maximum() == 0, (
        f"step list scrolls at {size}: range "
        f"{win.stepper.verticalScrollBar().maximum()}, "
        f"height {win.stepper.height()} of {win.stepper.ideal_height()}")
    moved = []
    resets = {}     # Reset step's rect on every step that has one
    for index, stage in enumerate(list(win._stages)):
        if not stage.enabled:
            continue
        win._go_to(index, user_initiated=False)
        _settle(qtbot)
        reset = win._panel.reset_step_btn
        if reset is not None:
            tl = reset.mapTo(win, QPoint(0, 0))
            resets[stage.id] = (tl.x(), tl.y(), reset.width(), reset.height())
        for label, geo in _states(win, qtbot):
            for key in baseline:
                if geo[key] != baseline[key]:
                    moved.append(f"{stage.id}/{label}: {key} {baseline[key]} -> {geo[key]}")
    # Reset step never moves between steps — including Enhancements, which
    # has no main action to its left.
    assert "enhancements" in resets and "levels" in resets, "precondition"
    assert len(set(resets.values())) == 1, resets
    # The linked toggle, pinned to one enabled stage in BOTH modes, so a row
    # moving here is the toggle's doing and not a stage change's.
    pinned = next(i for i, s in enumerate(win._stages) if s.id == "stretch")
    win._go_to(pinned, user_initiated=False)
    _settle(qtbot)
    for linked in (False, True):
        win._set_view_linked(linked)
        _settle(qtbot)
        assert win._stage == pinned, f"linked={linked} moved the current stage"
        geo = _geometry(win)
        for key in baseline:
            if geo[key] != baseline[key]:
                moved.append(f"linked={linked}: {key} {baseline[key]} -> {geo[key]}")
    assert not moved, "\n".join(moved[:40])


@pytest.mark.parametrize("size,denoise", [((1280, 800), False), ((1512, 982), False),
                                          ((1920, 1080), False), ((1280, 800), True)],
                         ids=["1280x800", "1512x982", "1920x1080", "1280x800-linear-denoise"])
def test_every_step_shows_under_the_real_stylesheet(qtbot, tmp_path, monkeypatch, size, denoise):
    """The suite runs WITHOUT the app stylesheet, whose 8 px list padding is
    exactly what a 32-px-rows-plus-1-px-frame height missed: offscreen it
    fitted, in Andreas' real window "Export" was cut off behind a scrollbar.
    So this one applies the stylesheet (restored afterwards)."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        if denoise:
            _with_linear_denoise(monkeypatch)
        win = _window(qtbot, tmp_path)
        win.open_fits(_make_fits(tmp_path))
        win.resize(*size)
        win.show()
        qtbot.waitExposed(win)
        _settle(qtbot)
        assert win.stepper.count() == (18 if denoise else 17), "precondition"
        assert any(s.id == "ai_denoise" for s in win._stages) == denoise
        _assert_every_row_shows(win, size)
    finally:
        app.setStyleSheet(before)


def test_the_activity_box_gives_up_all_its_room_before_the_step_list(qtbot, tmp_path):
    """Andreas, 2026-09-25: "if something should scroll in the left column it
    should be the activity log." At 1280x680 the left column is 584 px: the
    whole list (546) plus the activity header fits, the old 71 px activity
    floor did not — the list scrolled while the activity box kept two lines."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1280, 680)
    win.show()
    qtbot.waitExposed(win)
    _settle(qtbot)
    assert win.height() == 680, "precondition: the window really is this short"
    assert win.stepper.verticalScrollBar().maximum() == 0
    assert win.stepper.height() == win.stepper.ideal_height()
    assert 0 <= win.activity.view.height() < 44


# --- the pinned action area (consistent panels, Task 4) --------------------

def _y(win, w):
    return w.mapTo(win, QPoint(0, 0)).y()


def test_every_step_hands_its_own_apply_and_reset_to_the_pinned_slot(qtbot, tmp_path):
    """Apply and Reset step live in the side panel's action slot, in the same
    place on every step (Andreas, 2026-09-25: "about muscle memory again").
    Each step's OWN buttons — not a previous step's left behind — and the slot
    keeps one height whether a step has an Apply, a plain Export…, or none."""
    from PySide6.QtWidgets import QLabel, QPushButton
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1280, 800)
    win.show()
    qtbot.waitExposed(win)
    _settle(qtbot)
    slot = win._side.action_slot
    base_h, base_y = slot.height(), _y(win, slot)
    assert base_h > 0, "the slot was never given its height"
    controls_y = _y(win, win._panel.controls.parentWidget())
    seen = []
    for index, stage in enumerate(list(win._stages)):
        if not stage.enabled:
            continue
        win._go_to(index, user_initiated=False)
        _settle(qtbot)
        p = win._panel
        mine = [b for b in (p.primary_action, p.reset_step_btn) if b is not None]
        for b in mine:
            assert slot.isAncestorOf(b), f"{stage.id}: {b.text()} is not pinned"
            assert b.isVisible(), f"{stage.id}: {b.text()} is not shown"
        in_slot = [b for b in slot.findChildren(QPushButton)]
        assert sorted(map(id, in_slot)) == sorted(map(id, mine)), (
            f"{stage.id}: slot holds {[b.text() for b in in_slot]}")
        assert (slot.height(), _y(win, slot)) == (base_h, base_y), stage.id
        # Controls start at the same height on every step (fixed description).
        assert _y(win, p.controls.parentWidget()) == controls_y, stage.id
        # A FREE stepDesc label at the box's real width: the fixed-height
        # box's own heightForWidth is clamped to its minimum (42 vs 36 under
        # the stylesheet), so asking the box itself false-fails.
        d = p.desc_box
        free = QLabel(d.text()); free.setObjectName("stepDesc"); free.setWordWrap(True)
        free.setParent(d.parentWidget()); free.hide(); free.ensurePolished()
        assert free.heightForWidth(d.width()) <= d.height(), (
            f"{stage.id}: description overflows its two lines at {d.width()} px")
        free.deleteLater()
        seen.append(stage.id)
    assert {"load", "crop", "curves", "enhancements", "export"} <= set(seen)


def test_a_tall_step_scrolls_its_controls_while_apply_stays_put(qtbot, tmp_path):
    """Review Focus 1: a step taller than its zone at 1280x800 scrolls its
    controls; Apply and Reset stay visible and do not move. Under the real
    stylesheet, which is also where the slot's measured height must equal what
    its real contents ask for. Colour, not Curves: since 2026-09-26 Curves at
    this size hides its inline editor and no longer scrolls (measured: Colour
    150 px over its zone)."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = _window(qtbot, tmp_path)
        win.open_fits(_make_fits(tmp_path))
        win.resize(1280, 800)
        win.show()
        qtbot.waitExposed(win)
        win._go_to_id("color", user_initiated=False)
        _settle(qtbot)
        slot = win._side.action_slot
        assert slot.height() == slot.layout().sizeHint().height(), (
            "the measured slot height is not what Apply + rule + Reset need")
        bar = win._side.scroll.verticalScrollBar()
        assert bar.maximum() > 0, "precondition: Colour must be taller than its zone"
        apply_btn, reset = win._panel.apply_btn, win._panel.reset_step_btn
        editor = win._panel.method_box     # the first control: it scrolls
        # Spec §3: the title and description are fixed ABOVE the scroll too.
        title_widgets = (win._panel.help_link.parentWidget(), win._panel.desc_box)
        pinned = (apply_btn, reset) + title_widgets
        before_geo = [(_y(win, b), b.height()) for b in pinned]
        editor_y = _y(win, editor)
        bar.setValue(bar.maximum())
        _settle(qtbot)
        assert _y(win, editor) < editor_y, "precondition: the controls really scrolled"
        assert [(_y(win, b), b.height()) for b in pinned] == before_geo
        for b in pinned:
            assert b.isVisible()
            assert 0 <= _y(win, b) and _y(win, b) + b.height() <= win.height()
        assert not win._side.scroll.isAncestorOf(win._panel.desc_box)
    finally:
        app.setStyleSheet(before)


# --- "one row + histogram" (Andreas, 2026-09-25) ----------------------------

def _themed_window(qtbot, tmp_path, size, monkeypatch=None):
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    QApplication.instance().setStyleSheet(build_stylesheet())
    if monkeypatch is not None:
        _with_linear_denoise(monkeypatch)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(*size)
    win.show()
    qtbot.waitExposed(win)
    _settle(qtbot)
    return win


@pytest.fixture
def restore_stylesheet():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    before = app.styleSheet()
    yield
    app.setStyleSheet(before)


def test_the_step_zone_keeps_mains_room_at_1280x800(qtbot, tmp_path, restore_stylesheet):
    """The pinned title, description and action row came out of the step zone
    (they used to scroll inside it), so the histogram pays for them: at
    1280x800 the step zone must still have the 208 px it had on main, with
    the histogram no shorter than its readable floor."""
    from nocturne.ui.histogram_view import HIST_FLOOR_H
    from nocturne.ui.side_panel import SCROLL_COMFORT_H
    win = _themed_window(qtbot, tmp_path, (1280, 800))
    assert win._side.scroll.height() >= SCROLL_COMFORT_H == 208
    assert win.histogram_view.height() >= HIST_FLOOR_H


def test_the_histogram_yields_before_the_step_zone(qtbot, tmp_path, restore_stylesheet):
    """Shrinking the window takes height from the histogram first, down to
    its floor; only then from the step zone. Growing gives it back in the
    same order: the step zone to 208 first, the histogram to its natural
    240 next, and the step zone everything after that."""
    from nocturne.ui.histogram_view import HIST_FLOOR_H, HIST_NATURAL_H
    from nocturne.ui.side_panel import SCROLL_COMFORT_H
    win = _themed_window(qtbot, tmp_path, (1280, 1080))
    seen = []
    for h in range(1080, 689, -10):
        win.resize(1280, h)
        _settle(qtbot)
        hist, zone = win.histogram_view.height(), win._side.scroll.height()
        seen.append((h, hist, zone))
        assert HIST_FLOOR_H <= hist <= HIST_NATURAL_H, seen[-1]
        if hist > HIST_FLOOR_H:
            assert zone >= SCROLL_COMFORT_H, f"the histogram kept room the step zone needed: {seen[-1]}"
        if zone > SCROLL_COMFORT_H:
            assert hist == HIST_NATURAL_H, f"the step zone grew before the histogram: {seen[-1]}"
    hists = [x[1] for x in seen]
    assert max(hists) == HIST_NATURAL_H and min(hists) == HIST_FLOOR_H, "precondition: both ends reached"


def test_the_window_minimum_fits_a_720_screen_under_the_stylesheet(
        qtbot, tmp_path, monkeypatch, restore_stylesheet):
    """test_window_geometry measures the bare style; this is his real theme,
    with Linear Denoise installed (the longest step list)."""
    from nocturne.ui.main_window import MIN_WINDOW
    win = _themed_window(qtbot, tmp_path, (1280, 800), monkeypatch=monkeypatch)
    assert win.minimumSizeHint().height() <= MIN_WINDOW[1] <= 690
    # Also from a big window, where the histogram sits at its natural 240:
    # the minimum must count it at its floor, or the window could never be
    # made small again once it had been large.
    win.resize(1920, 1080)
    _settle(qtbot)
    assert win.histogram_view.height() == 240, "precondition"
    assert win.minimumSizeHint().height() <= MIN_WINDOW[1]


def _apply_stage_ids():
    from nocturne.ui.pipeline import path_stages
    return [s.id for s in path_stages(include=frozenset({"ai_denoise"}))
            if s.id not in ("load", "enhancements", "export")]


def test_every_apply_label_fits_beside_reset(qtbot, tmp_path, monkeypatch, restore_stylesheet):
    """One row: Apply shares its width with Reset step. Every stage's
    "Apply <step>" must still fit — the bold centred label and the status
    line below it, in every state — at the real right-column width under the
    real stylesheet."""
    from nocturne.ui.apply_button import ApplyButton
    from PySide6.QtGui import QFontMetrics
    win = _themed_window(qtbot, tmp_path, (1280, 800), monkeypatch=monkeypatch)
    checked = []
    for sid in _apply_stage_ids():
        win._go_to_id(sid, user_initiated=False)
        _settle(qtbot)
        btn = win._panel.primary_action
        assert isinstance(btn, ApplyButton), sid
        assert win._side.action_slot.isAncestorOf(win._panel.reset_step_btn), sid
        for state in ("pending", "not_run", "applied", "no_change"):
            btn.set_state(state)
            # The fonts paintEvent draws with (Review Focus 2). The text is
            # centred in the whole rect, but a label touching the rounded
            # edge still reads as clipped: keep a 14 px margin each side.
            bold, small = btn._fonts()
            room = btn.width() - 2 * 14
            assert QFontMetrics(bold).horizontalAdvance(btn.label_text()) <= room, (
                f"{btn.label_text()!r} ({state}) clips at {btn.width()} px")
            assert QFontMetrics(small).horizontalAdvance(btn.status_text()) <= room, (
                f"{btn.status_text()!r} ({state}) clips at {btn.width()} px")
        checked.append(sid)
    assert "ai_denoise" in checked and "green_fringe" in checked and "deconvolution" in checked


def test_plate_solve_opens_below_the_controls(qtbot, tmp_path):
    """Ruling R7: the Plate Solve panel sits BELOW the step's controls in the
    scroll, so opening it never moves where the controls start."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1280, 800)
    win.show()
    qtbot.waitExposed(win)
    win._go_to_id("levels", user_initiated=False)
    _settle(qtbot)
    first = win._panel.controls.itemAt(0).widget()
    assert first is win._panel.auto_btn, "precondition: Levels starts with Auto"
    closed_y = _y(win, first)
    win.solve_panel.setVisible(True)
    _settle(qtbot)
    assert win.solve_panel.isVisibleTo(win), "precondition: the solve panel is open"
    assert _y(win, first) == closed_y
    body = win._side.body_layout
    assert body.indexOf(win.solve_panel) > body.indexOf(win._side.panel)
