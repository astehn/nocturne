from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME
from . import help_content as hc

_TOPIC_ROLE = Qt.ItemDataRole.UserRole


class HelpDialog(QDialog):
    """Browsable help: section/topic list on the left, content on the right."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Help")
        self.setMinimumSize(760, 560)

        self.nav = QListWidget()
        self.nav.setObjectName("helpNav")
        self.nav.setMaximumWidth(240)
        for section in hc.SECTIONS:
            header = QListWidgetItem(section.title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)   # non-selectable header
            self.nav.addItem(header)
            for tid in section.topic_ids:
                t = hc.topic(tid)
                if t is None:
                    continue
                item = QListWidgetItem(f"   {t.title}")
                item.setData(_TOPIC_ROLE, tid)
                self.nav.addItem(item)
        self.nav.currentItemChanged.connect(self._on_row)

        self.viewer = QTextBrowser()
        self.viewer.setObjectName("helpBody")
        self.viewer.setOpenExternalLinks(False)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        top = QHBoxLayout()
        top.addWidget(self.nav)
        top.addWidget(self.viewer, 1)
        root = QVBoxLayout(self)
        root.addLayout(top, 1)
        root.addWidget(close_btn)

        self.show_topic("getting-started")

    def _on_row(self, current, _prev=None) -> None:
        if current is None:
            return
        tid = current.data(_TOPIC_ROLE)
        if tid:
            self._render(hc.topic(tid))

    def show_topic(self, topic_id: str) -> None:
        """Select the topic in the sidebar and render it; no-op for unknown ids."""
        t = hc.topic(topic_id)
        if t is None:
            return
        for i in range(self.nav.count()):
            if self.nav.item(i).data(_TOPIC_ROLE) == topic_id:
                self.nav.blockSignals(True)
                self.nav.setCurrentRow(i)
                self.nav.blockSignals(False)
                break
        self._render(t)

    def _render(self, t) -> None:
        if t is None:
            return
        self.viewer.setHtml(f"<h2>{t.title}</h2>{t.body}")
