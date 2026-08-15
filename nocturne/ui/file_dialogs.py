"""File dialogs that open where the user is looking.

macOS places an APPLICATION-modal panel on the screen that owns the menu bar.
With Nocturne on a second monitor the Open/Save panel therefore appears on the
primary display; if the window is also fullscreen, the panel lands on a
different Space entirely. It has the modal session, so every click elsewhere
just beeps, and the app looks hung — the user's only apparent option is to force
quit and lose the session. Confirmed 2026-08-15 by sampling a hung process:

    QFileDialog::getExistingDirectory -> QDialog::exec()
      -> -[NSSavePanel runModal] -> -[NSApplication runModalForWindow:]

waiting for an event nobody could see. Cmd+Period cancelled it.

A dialog that belongs to a window should be a SHEET, attached to that window —
it cannot then wander to another screen or Space. Qt presents a native panel as
a sheet when the dialog is WINDOW-modal and has a parent, so this is the native
macOS behaviour rather than a workaround. The static QFileDialog.getXxx helpers
are always application-modal, which is why they cannot be used here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog


def _prepare(parent, caption: str, directory: str, filters: str) -> QFileDialog:
    dlg = QFileDialog(parent, caption, directory, filters)
    # The whole point: window-modal, so Qt attaches it to the parent window.
    # Without a parent Qt falls back to application-modal, which is the bug.
    dlg.setWindowModality(Qt.WindowModality.WindowModal if parent is not None
                          else Qt.WindowModality.ApplicationModal)
    return dlg


def _first_selected(dlg: QFileDialog) -> str:
    files = dlg.selectedFiles()
    return files[0] if files else ""


def choose_folder(parent, caption: str, directory: str = "") -> str:
    """A directory, or "" if cancelled. Mirrors QFileDialog.getExistingDirectory."""
    dlg = _prepare(parent, caption, directory, "")
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    return _first_selected(dlg) if dlg.exec() else ""


def open_file(parent, caption: str, directory: str = "", filters: str = "") -> str:
    """An existing file, or "" if cancelled. Mirrors getOpenFileName()[0]."""
    dlg = _prepare(parent, caption, directory, filters)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    return _first_selected(dlg) if dlg.exec() else ""


def save_file(parent, caption: str, directory: str = "", filters: str = "",
              selected_filter: str = "") -> tuple[str, str]:
    """(path, chosen filter), or ("", "") if cancelled. Mirrors getSaveFileName,
    including the selected-filter argument, because the export path uses it to
    open on the format the user picked in the app."""
    dlg = _prepare(parent, caption, directory, filters)
    dlg.setFileMode(QFileDialog.FileMode.AnyFile)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    if selected_filter:
        dlg.selectNameFilter(selected_filter)
    if not dlg.exec():
        return "", ""
    return _first_selected(dlg), dlg.selectedNameFilter()
