""""How this works ↗" for the tool windows (Narrowband, Share, Trim …).

The steps' link opens the main window's help window, but a tool window runs
modally, and a modal dialog blocks every window that is not its own child —
so the main help window would sit there unscrollable. This link owns a help
window parented to the TOOL window instead: usable while the tool is open,
closed with it. It opens where the main help window was last left (the
geometry lives in the main window's settings, reached up the parent chain).
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QDialog, QLabel

from .help_dialog import HelpDialog
from .theme import ACCENT


def _geometry_owner(widget):
    """The window that keeps the help window's size and place (MainWindow)."""
    w = widget.parentWidget() if widget is not None else None
    while w is not None:
        if hasattr(w, "remember_help_geometry"):
            return w
        w = w.parentWidget()
    return None


class HelpLink(QLabel):
    """A link that opens, and pressed again closes, the help at `topic_id`."""

    def __init__(self, topic_id: str, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._topic_id = topic_id
        self._dialog = dialog
        self._help: HelpDialog | None = None
        style = f'style="color:{ACCENT}; text-decoration:none"'
        self.setText(f'<a href="#" {style}>How this works ↗</a>')
        self.setToolTip("Open or close the help for this tool, in its own window")
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.linkActivated.connect(lambda _: self.toggle())
        # A Tool child of the dialog is not hidden with it; close it ourselves.
        dialog.finished.connect(lambda _r: self._close_help())

    def help_window(self) -> HelpDialog | None:
        h = self._help
        return h if h is not None and shiboken6.isValid(h) else None

    def toggle(self) -> None:
        h = self.help_window()
        if h is not None and h.isVisible():
            self._close_help()
        else:
            self._open_help()

    def _open_help(self) -> None:
        h = self.help_window()
        if h is None:
            h = HelpDialog(self._dialog)
            h.setModal(False)
            h.setWindowFlag(Qt.WindowType.Tool, True)
            owner = _geometry_owner(self._dialog)
            hexed = owner.help_geometry() if owner is not None else ""
            if hexed:
                h.restoreGeometry(QByteArray.fromHex(hexed.encode()))
            h.finished.connect(lambda _r: self._remember())
            self._help = h
        h.show_topic(self._topic_id)
        h.show()
        h.raise_()
        h.activateWindow()

    def _close_help(self) -> None:
        h = self.help_window()
        if h is not None and h.isVisible():
            h.reject()                    # finished() remembers its place

    def _remember(self) -> None:
        h = self.help_window()
        owner = _geometry_owner(self._dialog)
        if h is not None and owner is not None:
            owner.remember_help_geometry(h)
