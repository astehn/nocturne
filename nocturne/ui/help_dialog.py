from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from .. import APP_NAME
from . import help_content as hc
from .theme import ACCENT

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
        # Links are ours to follow: "help:<topic>#<anchor>" crosses topics (the
        # Glossary), "#<anchor>" stays on the page. Left to itself QTextBrowser
        # would try to load "help:glossary" as a file and show a blank page.
        self.viewer.setOpenLinks(False)
        self.viewer.anchorClicked.connect(self._follow)
        self.viewer.document().setDefaultStyleSheet(
            f"a {{ color: {ACCENT}; text-decoration: none; }}")

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

    def current_topic(self) -> str | None:
        """The topic on screen — its id, or None on a section header."""
        item = self.nav.currentItem()
        return item.data(_TOPIC_ROLE) if item is not None else None

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

    def _follow(self, url: QUrl) -> None:
        if url.scheme() == "help":
            if hc.topic(url.path()) is None:
                return
            self.show_topic(url.path())
        elif url.scheme() or url.path():
            return                        # nothing in the help links outside it
        if url.fragment():
            self._scroll_to(url.fragment())

    def _scroll_to(self, anchor: str) -> None:
        self.viewer.scrollToAnchor(anchor)

    def _render(self, t) -> None:
        if t is None:
            return
        self.viewer.setHtml(f"<h2>{t.title}</h2>{t.body}")
