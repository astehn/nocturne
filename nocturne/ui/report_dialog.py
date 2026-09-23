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

from PySide6.QtCore import QThreadPool
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
        self._sending = False
        self._sent = False
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
        # Shown only when a send has failed. The spec has required this route
        # from the start and it was wired to nothing: offline, the reporter got
        # "could not reach the server" and no way to the web form at all.
        self.fallback_btn = QPushButton("Open the web form instead")
        self.fallback_btn.setToolTip(
            "Opens nocturneastro.com with what you have typed. The diagnostic "
            "log is too large for a web link and will not travel with it.")
        self.fallback_btn.clicked.connect(self._use_fallback)
        self.fallback_btn.hide()
        buttons.addWidget(self.fallback_btn)
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
        # The failed command and its stderr. Shown because it is SENT — the
        # consent property is "you send what you see", and this field used to
        # travel without appearing here at all.
        failure = self._context.get("log")
        if failure:
            parts.append("--- the last thing that failed ---\n" + str(failure))
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
                               self._context.get("screen", ""), self._settings,
                               failure=_first_line(self._context.get("log", "")),
                               steps=_last_steps(self._session)),
            self._summary_ready, self._summary_failed)

    def _alive(self) -> bool:
        """Whether this dialog's C++ side still exists.

        A probe can take up to four tool timeouts and a send up to thirty
        seconds; quitting inside either window destroys the widget while the
        worker is still running, and its queued signal then lands on freed
        memory. That is the shape of the segfault that shipped in v0.38.0,
        reached by a different route — the QRunnable is fine here, the
        RECEIVER is gone.
        """
        from shiboken6 import isValid
        try:
            return isValid(self)
        except Exception:                         # noqa: BLE001 - see docstring
            return False

    def _summary_ready(self, text) -> None:
        if not self._alive():
            return
        self._summary = str(text or "")
        self._render_log()

    def _summary_failed(self, exc) -> None:
        if not self._alive():
            return
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

    def _use_fallback(self) -> None:
        self._on_fallback(self.problem.toPlainText().strip())

    def _on_fallback(self, problem: str) -> None:
        """Overridden per instance by a test, so it can watch this without
        opening a real browser."""
        _open_web_form(problem)

    def _refresh_send(self) -> None:
        """Enable Send when there is something to send AND nothing in flight.

        The in-flight half is not belt-and-braces. `textChanged` calls this on
        every keystroke, so without it pressing Send and then fixing a typo —
        the ordinary thing a person does — re-armed the button and filed the
        ticket twice, with no queue for the reporter to see it in.
        """
        if self._sending or self._sent:
            self.send_btn.setEnabled(False)
            return
        self.send_btn.setEnabled(bool(self.problem.toPlainText().strip()))

    def _log_to_send(self) -> str | None:
        if not self.include_log.isChecked():
            return None
        return self.log_view.toPlainText() or None

    def _send(self) -> None:
        if self._sending or self._sent:
            return
        self._sending = True
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
        if not self._alive():
            # The report still went out; only the dialog that asked for it is
            # gone. Nothing to update and nothing to apologise for.
            return
        ok, message = result
        self._sending = False
        self.status.setText(str(message))
        # Latched, not merely disabled: `textChanged` re-enables the button on
        # the next keystroke, so the flag is the only thing that holds. ONE
        # place decides whether Send is live — _refresh_send — because a second
        # setEnabled here was redundant, invisible to every test, and free to
        # disagree with it.
        self._sent = bool(ok)
        if ok:
            self.close_btn.setText("Done")
            self.fallback_btn.hide()
        else:
            self.fallback_btn.show()
        # On failure everything the person typed is still in the form. A report
        # that vanishes because the wifi dropped is worse than the handoff this
        # replaces.
        self._refresh_send()


def _session_age() -> float:
    """Seconds since this session STARTED — not since it was last written to.

    The difference is the whole feature. The first version stat'ed the log's
    mtime, which every step and every tool run updates, so a session hours old
    read as seconds old the moment anything happened in it — and the previous
    session was attached to almost every report.

    Unknown is infinity, never zero: "I do not know when this began" must not
    read as "it began just now".
    """
    started = getattr(sessionlog, "_started_at", None)
    if started is None:
        return float("inf")
    return max(0.0, time.monotonic() - started)


def _open_web_form(problem: str) -> None:
    """The browser handoff, as the fallback it now is.

    It cannot carry the diagnostic log — a URL is a hard ceiling, which is the
    whole reason the dialog exists — and the tooltip says so rather than
    letting somebody believe the log went with it.
    """
    from urllib.parse import urlencode

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    from ..core.update_check import SUPPORT_URL
    frag = urlencode({"problem": problem}) if problem else ""
    QDesktopServices.openUrl(QUrl(f"{SUPPORT_URL}#{frag}" if frag else SUPPORT_URL))


def _first_line(text: str) -> str:
    """The stderr line, for the summary block's "Failed at:".

    The whole diagnostic is several lines of command and traceback; the summary
    exists to be read in five seconds. `failure` and `steps` were dead
    parameters until this call site passed them — tested as if live, which a
    review caught.
    """
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("Command:", "Elapsed:", "stderr:")):
            return stripped
    return ""


def _last_steps(session: str, limit: int = 6) -> list[str]:
    """The last few steps, for the summary block's "Last steps:"."""
    steps = [ln.split("step  ", 1)[1] for ln in str(session or "").splitlines()
             if "step  " in ln]
    return steps[-limit:]
