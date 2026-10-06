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
        # The latest wins, now as at launch: three files opened together from
        # the Finder are three events, and loading each in turn only for the
        # last to replace them helps nobody.
        self._pending = path
        if self._window is not None:
            # After the event that carried it has returned: opening asks
            # questions (unsaved changes) and runs a nested loop of its own.
            QTimer.singleShot(0, self._window, self._deliver)

    def _deliver(self) -> None:
        path, self._pending = self._pending, None
        if path is not None and self._window is not None:
            self._window.open_requested(path)

    def attach(self, window) -> None:
        self._window = window
        if self._pending is not None:
            QTimer.singleShot(0, window, self._deliver)


def path_from_argv(argv: list[str]) -> str | None:
    """The first argument that is a file Nocturne opens (flags and their
    values are skipped by being neither)."""
    for arg in argv[1:]:
        if not arg.startswith("-") and os.path.isfile(arg) and file_kind(arg):
            return os.path.abspath(arg)
    return None
