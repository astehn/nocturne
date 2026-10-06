"""Files the system asks Nocturne to open: a Finder double-click, "Open With",
a file dropped on the Dock icon (macOS sends these as QFileOpenEvent), or a
path on the command line (both platforms).

macOS can send the request before the window exists — a double-click on a
project when Nocturne is not running starts the app AND asks it to open the
file — so requests are held until the window is attached. Only the last one
is kept: Nocturne shows one picture at a time.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QTimer

from .file_drop import file_kind


class OpenRequests(QObject):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._window = None
        self._pending: str | None = None
        app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if path:
                self.request(path)
                return True
        return False

    def request(self, path: str) -> None:
        if self._window is None:
            self._pending = path
            return
        # After the event that carried it has returned: opening asks questions
        # (unsaved changes) and runs a nested loop of its own.
        win = self._window
        QTimer.singleShot(0, win, lambda: win.open_requested(path))

    def attach(self, window) -> None:
        self._window = window
        if self._pending is not None:
            path, self._pending = self._pending, None
            self.request(path)


def path_from_argv(argv: list[str]) -> str | None:
    """The first argument that is a file Nocturne opens (flags and their
    values are skipped by being neither)."""
    for arg in argv[1:]:
        if not arg.startswith("-") and os.path.isfile(arg) and file_kind(arg):
            return os.path.abspath(arg)
    return None
