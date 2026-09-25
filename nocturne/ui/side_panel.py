"""The right column as fixed zones around one scrolling middle.

Every zone except the step panel has a FIXED height on every step, and the
step panel scrolls inside itself — so the panel's top edge and Next never
move, and no step can push the window taller. Before this, the column grew
with its tallest content: Curves grew the whole window ~115 px and it never
shrank back, and the busy/warning lines grew upward and moved everything
above them (Andreas' screenshots, 2026-09-25; spec §4.2).

The status slot is reserved even when empty — his call: ~64 px is the price
of nothing ever changing, where the alternative would have covered Apply and
Reset whenever something ran.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

STATUS_SLOT_H = 64
CLIP_SLOT_H = 40
LINEAR_CLIP_TEXT = "Clipping is shown once the image is stretched."


def _elided_label(object_name: str = "") -> QLabel:
    lab = QLabel("")
    if object_name:
        lab.setObjectName(object_name)
    lab.setWordWrap(True)
    # Ignored vertically: the text may be any length, the slot may not grow.
    lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
    return lab


class SidePanel(QWidget):
    def __init__(self, width: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(width)
        self.layout_ = QVBoxLayout(self)

        # histogram + info strip (MainWindow adds its widgets here)
        self.histogram_zone = QVBoxLayout()
        self.layout_.addLayout(self.histogram_zone)

        # clipping slot — fixed height, always present
        self.clip_slot = QWidget()
        self.clip_slot.setFixedHeight(CLIP_SLOT_H)
        clip_lay = QVBoxLayout(self.clip_slot)
        clip_lay.setContentsMargins(0, 0, 0, 0)
        clip_lay.setSpacing(2)
        self.clip_line = _elided_label("importMeta")
        self.clip_check = QCheckBox("Show clipping")
        clip_lay.addWidget(self.clip_line, 1)
        clip_lay.addWidget(self.clip_check)
        self.layout_.addWidget(self.clip_slot)

        # the one flexible zone
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(0)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = QWidget()
        self.body_layout.addWidget(self.panel)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(body)
        self.layout_.addWidget(self.scroll, 1)

        # status slot — fixed height, reserved while empty
        self.status_slot = QWidget()
        self.status_slot.setFixedHeight(STATUS_SLOT_H)
        st = QVBoxLayout(self.status_slot)
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(2)
        self.peek_label = _elided_label()
        self.peek_label.setStyleSheet("color: #9aa0a6;")
        self.busy_label = _elided_label()
        self.busy_label.setStyleSheet("color: #9aa0a6;")
        self.progress = QProgressBar()
        self.progress.hide()
        busy_row = QHBoxLayout()
        self.elapsed_label = QLabel("")
        self.elapsed_label.setStyleSheet("color: #9aa0a6;")
        self.elapsed_label.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        busy_row.addWidget(self.elapsed_label)
        busy_row.addStretch(1)
        busy_row.addWidget(self.cancel_btn)
        self.warning = _elided_label("warning")
        self.warning.setStyleSheet("color: #ff6b6b;")
        diag_row = QHBoxLayout()
        self.details_btn = QPushButton("Show details")
        self.details_btn.setFlat(True)
        self.details_btn.hide()
        self.copy_log_btn = QPushButton("Copy log")
        self.copy_log_btn.setFlat(True)
        self.copy_log_btn.hide()
        diag_row.addWidget(self.details_btn)
        diag_row.addWidget(self.copy_log_btn)
        diag_row.addStretch(1)
        for w in (self.peek_label, self.busy_label, self.progress):
            st.addWidget(w)
        st.addLayout(busy_row)
        st.addWidget(self.warning, 1)
        st.addLayout(diag_row)
        self.layout_.addWidget(self.status_slot)

        # nav — the LAST item (flush-nav invariant)
        nav = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.next_btn = QPushButton("Next →")
        self.next_btn.setObjectName("nav")
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        self.layout_.addLayout(nav)

    def set_panel(self, new: QWidget) -> None:
        self.body_layout.replaceWidget(self.panel, new)
        self.panel.setParent(None)
        self.panel.deleteLater()
        self.panel = new

    def set_clipping(self, text: str | None, tooltip: str = "") -> None:
        """None = linear. The slot keeps its height either way, so the panel
        below does not jump when the image passes Stretch."""
        if text is None:
            self.clip_line.setText(LINEAR_CLIP_TEXT)
            self.clip_line.setToolTip("")
            self.clip_line.setEnabled(False)
            self.clip_check.setEnabled(False)
        else:
            self.clip_line.setText(text)
            self.clip_line.setToolTip(tooltip)
            self.clip_line.setEnabled(True)
            self.clip_check.setEnabled(True)
