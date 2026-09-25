from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

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
