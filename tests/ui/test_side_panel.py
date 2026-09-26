import shiboken6
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from nocturne.ui.side_panel import CLIP_SLOT_H, LINEAR_CLIP_TEXT, STATUS_SLOT_H, SidePanel


def _side(qtbot, h=700):
    s = SidePanel(width=400)
    qtbot.addWidget(s)
    s.resize(400, h)
    s.show()
    qtbot.waitExposed(s)
    return s


def _y(s, w):
    return w.mapTo(s, QPoint(0, 0)).y()


def _tall_panel(n=60):
    w = QWidget(); lay = QVBoxLayout(w)
    for i in range(n):
        lay.addWidget(QLabel(f"row {i}"))
    return w


def test_nav_is_the_last_item(qtbot):
    s = _side(qtbot)
    last = s.layout_.itemAt(s.layout_.count() - 1).layout()
    assert s.next_btn in [last.itemAt(i).widget() for i in range(last.count())]


def test_a_tall_panel_scrolls_instead_of_growing_anything(qtbot):
    s = _side(qtbot)
    y_next, h_min = _y(s, s.next_btn), s.minimumSizeHint().height()
    s.set_panel(_tall_panel(200))
    qtbot.wait(20)
    assert _y(s, s.next_btn) == y_next
    assert s.minimumSizeHint().height() == h_min      # the window can never be pushed taller
    assert s.scroll.verticalScrollBar().maximum() > 0


def test_the_status_slot_is_reserved_and_fixed(qtbot):
    s = _side(qtbot)
    y_next, y_scroll_h = _y(s, s.next_btn), s.scroll.height()
    assert s.status_slot.height() == STATUS_SLOT_H     # present while empty
    s.warning.setText("RC-Astro failed — " + "a very long message " * 40)
    s.busy_label.setText("Separating stars…"); s.progress.show(); s.cancel_btn.show()
    qtbot.wait(20)
    assert s.status_slot.height() == STATUS_SLOT_H
    assert _y(s, s.next_btn) == y_next and s.scroll.height() == y_scroll_h


def test_the_clipping_slot_keeps_its_height_before_and_after_stretch(qtbot):
    s = _side(qtbot)
    y_scroll = _y(s, s.scroll)
    s.set_clipping(None)
    assert s.clip_line.text() == LINEAR_CLIP_TEXT
    qtbot.wait(20)
    assert _y(s, s.scroll) == y_scroll
    s.set_clipping("⚠ 0.0% red blown · 7.5% blue crushed " * 3, tooltip="t")
    qtbot.wait(20)
    assert _y(s, s.scroll) == y_scroll
    assert s.clip_slot.height() == CLIP_SLOT_H


def test_set_panel_replaces_in_place(qtbot):
    s = _side(qtbot)
    a, b = QLabel("a"), QLabel("b")
    s.set_panel(a)
    s.set_panel(b)
    assert s.panel is b
    assert a.parent() is None


def test_a_long_warning_elides_instead_of_overflowing(qtbot):
    s = _side(qtbot)
    h_before = s.status_slot.height()
    full = "RC-Astro failed — " + "a very long message " * 40
    s.warning.setText(full)
    qtbot.wait(20)
    displayed = QLabel.text(s.warning)          # the raw QLabel text underneath
    assert displayed.endswith("…")
    assert displayed != full and len(displayed) < len(full)
    assert s.warning.text() == full             # our override: the FULL value survives
    assert s.warning.toolTip() == full
    assert s.status_slot.height() == h_before   # elision, not growth, absorbs the length


def test_a_short_warning_shows_unchanged(qtbot):
    s = _side(qtbot)
    s.warning.setText("Done.")
    qtbot.wait(20)
    assert QLabel.text(s.warning) == "Done."
    assert s.warning.text() == "Done."


def test_the_action_slot_is_fixed_and_outside_the_scroll(qtbot):
    from PySide6.QtWidgets import QPushButton
    s = _side(qtbot)
    s.set_action_height(120)
    apply_b, reset_b = QPushButton("Apply X"), QPushButton("Reset step")
    s.set_actions(apply_b, reset_b)
    qtbot.wait(20)
    y_slot, y_next = _y(s, s.action_slot), _y(s, s.next_btn)
    s.set_panel(_tall_panel(200)); qtbot.wait(20)
    assert _y(s, s.action_slot) == y_slot and _y(s, s.next_btn) == y_next
    assert s.action_slot.height() == 120
    assert apply_b.isVisible() and s.scroll.isAncestorOf(apply_b) is False


def test_an_empty_action_slot_keeps_its_height(qtbot):
    s = _side(qtbot); s.set_action_height(120)
    s.set_actions(None, None); qtbot.wait(20)
    assert s.action_slot.height() == 120


def test_replacing_the_actions_destroys_the_old_widgets(qtbot):
    # R3: set_actions used to setParent(None) the outgoing widgets. Once a
    # widget has been added to action_slot's layout, the slot is its parent —
    # setParent(None) then leaves it owned by nobody, so it is never deleted.
    # Every step change would leak the previous step's Apply/Reset buttons.
    s = _side(qtbot)
    old_apply, old_reset = QPushButton("Apply X"), QPushButton("Reset step")
    s.set_actions(old_apply, old_reset)
    qtbot.wait(20)
    new_apply, new_reset = QPushButton("Apply Y"), QPushButton("Reset step")
    s.set_actions(new_apply, new_reset)
    qtbot.wait(20)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(old_apply)
    assert not shiboken6.isValid(old_reset)
    assert new_apply.isVisible() and new_reset.isVisible()


def test_set_actions_twice_with_the_same_widgets_keeps_them_alive(qtbot):
    s = _side(qtbot)
    apply_b, reset_b = QPushButton("Apply X"), QPushButton("Reset step")
    s.set_actions(apply_b, reset_b)
    qtbot.wait(20)
    s.set_actions(apply_b, reset_b)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(apply_b) and shiboken6.isValid(reset_b)
    assert apply_b.isVisible() and reset_b.isVisible()


def test_the_header_is_fixed_above_the_scroll(qtbot):
    s = _side(qtbot)
    head = QLabel("Curves")
    s.set_header(head)
    qtbot.wait(20)
    y_head = _y(s, head)
    s.set_panel(_tall_panel(200)); qtbot.wait(20)
    s.scroll.verticalScrollBar().setValue(s.scroll.verticalScrollBar().maximum())
    qtbot.wait(20)
    assert _y(s, head) == y_head and head.isVisible()
    assert not s.scroll.isAncestorOf(head)
    frame = s.step_frame.layout()
    assert 0 <= frame.indexOf(s.header_slot) < frame.indexOf(s.scroll)


def test_replacing_the_header_destroys_the_old_one(qtbot):
    s = _side(qtbot)
    old, new = QLabel("Levels"), QLabel("Curves")
    s.set_header(old); qtbot.wait(20)
    s.set_header(new); qtbot.wait(20)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(old)
    assert new.isVisible()
    s.set_header(new)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(new) and new.isVisible()


def test_reset_keeps_its_place_with_or_without_a_main_action(qtbot):
    """One row: Apply stretches on the left, Reset step sits at the right at
    its own size — and stays exactly there on a step with no main action
    (Enhancements)."""
    s = _side(qtbot); s.set_action_height(50)
    apply_b, reset_b = QPushButton("Apply Levels"), QPushButton("Reset step")
    s.set_actions(apply_b, reset_b); qtbot.wait(20)
    with_apply = reset_b.mapTo(s, QPoint(0, 0)), reset_b.size()
    assert apply_b.geometry().right() < reset_b.geometry().left()
    assert reset_b.width() == reset_b.sizeHint().width()
    reset2 = QPushButton("Reset step")
    s.set_actions(None, reset2); qtbot.wait(20)
    assert (reset2.mapTo(s, QPoint(0, 0)), reset2.size()) == with_apply


def test_the_histogram_gives_up_height_first(qtbot):
    from nocturne.ui.histogram_view import HIST_FLOOR_H, HIST_NATURAL_H, HistogramView
    from nocturne.ui.side_panel import SCROLL_COMFORT_H
    s = _side(qtbot, h=900)
    hist = HistogramView()
    s.set_histogram(hist)
    qtbot.wait(20)
    assert hist.height() == HIST_NATURAL_H and s.scroll.height() > SCROLL_COMFORT_H
    for h in (700, 650, 600, 560, 500, 440):
        s.resize(400, h); qtbot.wait(20)
        if hist.height() > HIST_FLOOR_H:
            assert s.scroll.height() >= SCROLL_COMFORT_H, (h, hist.height(), s.scroll.height())
    assert hist.height() == HIST_FLOOR_H and s.scroll.height() < SCROLL_COMFORT_H
    # The column's minimum counts the histogram at its floor, not at the
    # height it happens to have now.
    s.resize(400, 900); qtbot.wait(20)
    assert hist.height() == HIST_NATURAL_H
    lo = s.minimumSizeHint().height()
    s.resize(400, 500); qtbot.wait(20)
    assert s.minimumSizeHint().height() == lo


def test_a_replaced_header_stops_painting_at_once(qtbot):
    """Inside the transparent step frame, an outgoing header still visible
    until its deferred delete lands painted the old step's title through the
    new one's (seen in a render, 2026-09-25). Hidden at once, before any
    event is processed."""
    s = _side(qtbot)
    old, new = QLabel("Import"), QLabel("Levels")
    s.set_header(old); qtbot.wait(20)
    old_apply = QPushButton("Apply Crop")
    s.set_actions(old_apply, None); qtbot.wait(20)
    s.set_header(new)
    s.set_actions(QPushButton("Apply Levels"), None)
    assert old.isHidden() and old_apply.isHidden()
