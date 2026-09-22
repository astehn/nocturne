"""Report a problem, from inside Nocturne.

Replaces a browser handoff that could not carry a diagnostic log — a URL is a
hard ceiling, and the requirement is the opposite of a ceiling. Andreas,
2026-09-22: *"im alone in getting the support tickets and i need as much
valuable information as possible so that i can actually act on it."*

The consent property is KEPT, not traded away. Nothing leaves the machine until
Send is pressed, and unlike the URL-capped textarea it replaces, this can show
the reporter the whole log first. `site/support.html` is untouched and still
serves web-initiated reports, which send no log at all — a visitor cannot be
asked to find a file.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from ..core import sessionlog
from ..core.diagnostics import summary_block
from ..core.report import report_fields, send_report

# Below this, the session was almost certainly relaunched rather than worked
# in — which is the signature of a crash, and the whole reason two sessions are
# kept. Sixty seconds rather than five: the sequence is app dies, user stares
# at it, reopens, finds the menu item, and the useful session is still the
# previous one at a minute.
CRASH_WINDOW_SECONDS = 60.0

_TOPICS = [("problem", "A problem"), ("question", "A question"),
           ("removal", "Remove my data"), ("donation", "A donated file")]

_LOG_IN = ("This travels with your report: what Nocturne did, not what your "
           "computer is. You can read it below, and untick to leave it out.")
_LOG_OUT = ("The log will not be sent. Without it a problem may not be "
            "solvable — there is usually no way to ask you for more.")

# Attachments the server accepts; it checks magic bytes as well, so this is the
# file picker being helpful rather than the gate.
_FILTER = "Screenshot or log (*.png *.jpg *.jpeg *.txt *.log);;All files (*)"
_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
          "txt": "text/plain", "log": "text/plain"}


class ReportDialog(QDialog):
    def __init__(self, settings, context: dict, *, parent=None,
                 sender=send_report, session_reader=sessionlog.read_session,
                 previous_reader=sessionlog.read_previous, session_age=None,
                 summariser=summary_block, pool=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report a problem")
        self.setMinimumWidth(620)
        self._settings = settings
        self._context = dict(context)
        self._sender = sender
        self._pool = pool or QThreadPool.globalInstance()
        self._attachment: bytes | None = None
        self._attachment_name = ""
        self._summary = ""

        age = session_age() if session_age else _session_age()
        self._session = session_reader() or ""
        # The previous session only when this one is seconds old. An hour in it
        # is not evidence, it is noise in a ticket read by one person.
        self._previous = previous_reader() if age < CRASH_WINDOW_SECONDS else ""

        self._build()
        self._render_log()
        self._start_summary(summariser)

    # --- construction -------------------------------------------------------

    def _build(self) -> None:
        box = QVBoxLayout(self)

        self.topic_box = QComboBox()
        for value, label in _TOPICS:
            self.topic_box.addItem(label, value)
        box.addWidget(QLabel("What is this about?"))
        box.addWidget(self.topic_box)

        box.addWidget(QLabel("What went wrong?"))
        self.problem = QPlainTextEdit()
        self.problem.setPlaceholderText(
            "What you were doing, and what happened instead.")
        self.problem.setMinimumHeight(90)
        self.problem.textChanged.connect(self._refresh_send)
        box.addWidget(self.problem)

        box.addWidget(QLabel("Your email — optional, and the only way to get a reply"))
        self.email = QLineEdit()
        box.addWidget(self.email)

        self.include_log = QCheckBox("Send the diagnostic log")
        # Always on for an app-initiated report. A default-off box would
        # quietly return us to the round trips this exists to end.
        self.include_log.setChecked(True)
        self.include_log.toggled.connect(self._on_toggle_log)
        box.addWidget(self.include_log)

        self.log_note = QLabel(_LOG_IN)
        self.log_note.setWordWrap(True)
        self.log_note.setStyleSheet("color: #9aa0a6;")
        box.addWidget(self.log_note)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(160)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        box.addWidget(self.log_view)

        row = QHBoxLayout()
        self.attach_btn = QPushButton("Attach a screenshot…")
        self.attach_btn.clicked.connect(self._choose_attachment)
        self.attach_label = QLabel("")
        self.attach_label.setStyleSheet("color: #9aa0a6;")
        row.addWidget(self.attach_btn)
        row.addWidget(self.attach_label, 1)
        box.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        box.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        self.send_btn = QPushButton("Send report")
        self.send_btn.setDefault(True)
        self.send_btn.setEnabled(False)          # nothing to report yet
        self.send_btn.clicked.connect(self._send)
        buttons.addWidget(self.close_btn)
        buttons.addWidget(self.send_btn)
        box.addLayout(buttons)

    # --- the log pane -------------------------------------------------------

    def _render_log(self) -> None:
        parts = []
        if self._summary:
            parts.append(self._summary)
        if self._previous:
            parts.append("--- the session before this one ---\n" + self._previous)
        parts.append(self._session)
        self.log_view.setPlainText("\n".join(p for p in parts if p).strip())

    def _on_toggle_log(self, on: bool) -> None:
        self.log_note.setText(_LOG_IN if on else _LOG_OUT)
        self.log_view.setEnabled(on)

    # --- the summary, OFF the interface thread ------------------------------

    def _start_summary(self, summariser) -> None:
        """Probing four tools takes as long as the slowest one, and ASTAP's
        took SIXTY SECONDS when measured (2026-09-22). Building this inline
        would freeze the dialog on exactly the machines with the most to
        report, so it arrives late and the rest of the dialog does not wait.
        """
        from .worker import run_async
        run_async(
            self._pool,
            lambda: summariser(self._context.get("app_version", ""),
                               self._context.get("os", ""),
                               self._context.get("screen", ""), self._settings),
            self._summary_ready, self._summary_failed)

    def _summary_ready(self, text) -> None:
        self._summary = str(text or "")
        self._render_log()

    def _summary_failed(self, exc) -> None:
        # A probe is a nicety; the report is the point. Say nothing and carry
        # on rather than showing the reporter a failure that is not theirs.
        self._summary = ""
        self._render_log()

    # --- attachment ---------------------------------------------------------

    def _choose_attachment(self) -> None:
        # file_dialogs, not QFileDialog.getOpenFileName. The static helpers are
        # ALWAYS application-modal and strand on the wrong screen; a test in
        # tests/ui/test_file_dialogs.py fails the build for a new call site,
        # and it caught this one.
        from .file_dialogs import open_file
        path = open_file(self, "Attach a screenshot or file", "", _FILTER)
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                self._attachment = fh.read()
        except OSError as exc:
            self.status.setText(f"Could not read that file: {exc}")
            return
        import os
        self._attachment_name = os.path.basename(path)
        self.attach_label.setText(self._attachment_name)

    # --- sending ------------------------------------------------------------

    def _refresh_send(self) -> None:
        self.send_btn.setEnabled(bool(self.problem.toPlainText().strip()))

    def _log_to_send(self) -> str | None:
        if not self.include_log.isChecked():
            return None
        return self.log_view.toPlainText() or None

    def _send(self) -> None:
        self.send_btn.setEnabled(False)
        self.status.setText("Sending…")
        fields = report_fields(
            self.problem.toPlainText().strip(), self.email.text().strip(),
            self.topic_box.currentData(), self._context,
            diag_log=self._log_to_send())
        ext = self._attachment_name.rsplit(".", 1)[-1].lower()
        ctype = _TYPES.get(ext, "application/octet-stream")

        # run_async, NOT a hand-rolled QRunnable. One auto-deleted in C++ the
        # moment run() returned and the queued signal arrived pointing at freed
        # memory — that segfault shipped in v0.38.0. worker.py exists for
        # exactly this.
        from .worker import run_async
        run_async(
            self._pool,
            lambda: self._sender(fields, self._attachment,
                                 self._attachment_name, ctype),
            self._finish,
            lambda exc: self._finish((False, f"Could not send the report: {exc}")))

    def _finish(self, result) -> None:
        ok, message = result
        self.status.setText(str(message))
        if ok:
            # A second press would file it twice, and the reporter cannot see
            # the queue to know they did.
            self.send_btn.setEnabled(False)
            self.close_btn.setText("Done")
            return
        # Everything the person typed is still in the form. A report that
        # vanishes because the wifi dropped is worse than the handoff this
        # replaces.
        self._refresh_send()


def _session_age() -> float:
    """Seconds since this session's log was opened."""
    import os
    try:
        return max(0.0, time.time() - os.path.getmtime(sessionlog.session_path()))
    except OSError:
        return float("inf")
