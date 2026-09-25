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

from tests.ui.test_main_window import _make_fits, _window

SIZES = [(1280, 720), (1280, 800), (1512, 982), (1920, 1080), (2560, 1440)]


def _row_rect(r) -> tuple:
    return (r.x(), r.y(), r.width(), r.height())


def _geometry(win) -> dict:
    def rect(w):
        tl = w.mapTo(win, QPoint(0, 0))
        return (tl.x(), tl.y(), w.width(), w.height())
    return {
        "window": (win.width(), win.height()),
        "canvas": rect(win.image_view),
        "next": rect(win._next_btn),
        "stepper": rect(win.stepper),
        # side_panel.py's own contract: "every zone except the step panel has
        # a FIXED height on every step" — the status slot's size (not just
        # the widgets around it) must itself be invariant. Without this key,
        # an un-fixed status_slot is invisible to this test: its scroll area
        # sibling has stretch factor 1 and silently absorbs the size change,
        # so canvas/next/stepper/window never move even though the fixed
        # zone contract is broken.
        "status_slot": rect(win._side.status_slot),
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
        "rows": tuple(
            (win.stepper.item(i).text(),
             _row_rect(win.stepper.visualItemRect(win.stepper.item(i))))
            for i in range(win.stepper.count())
        ),
    }


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

    win.jobs_indicator.notices.append({"kind": "done", "label": "M 33", "path": ""})
    win.jobs_indicator._refresh()
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
            yield "pending", _geometry(win)
            slider.setValue(v)
            qtbot.wait(120)
            _settle(qtbot)
            break


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_nothing_moves_across_steps_and_states(qtbot, tmp_path, size):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(*size)
    win.show()
    qtbot.waitExposed(win)
    _settle(qtbot)
    baseline = _geometry(win)
    # Every key — "rows" included — is compared against this ONE baseline,
    # taken on the first stage. A per-stage baseline for the rows once hid a
    # step list stuck at its 240 px floor that scrolled a different window of
    # rows into view on every step: the user's muscle memory is exactly what
    # moving rows break, so there is no stage change for which that is fine.
    # At every size here the whole list fits (Stepper.sizeHint asks for all
    # 17 rows; the activity box yields down to 72 px at 1280x720), so it must
    # have nothing to scroll either.
    assert win.stepper.verticalScrollBar().maximum() == 0, (
        f"step list scrolls at {size}: range "
        f"{win.stepper.verticalScrollBar().maximum()}, "
        f"height {win.stepper.height()} of {win.stepper.ideal_height()}")
    moved = []
    for index, stage in enumerate(list(win._stages)):
        if not stage.enabled:
            continue
        win._go_to(index, user_initiated=False)
        _settle(qtbot)
        for label, geo in _states(win, qtbot):
            for key in baseline:
                if geo[key] != baseline[key]:
                    moved.append(f"{stage.id}/{label}: {key} {baseline[key]} -> {geo[key]}")
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
