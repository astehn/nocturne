"""The first-run question. Asked once, answered either way, never nagged.

Wording approved by Andreas 2026-09-17 — treat an edit as reopening a decision,
not as a typo fix. It shows the LITERAL payload, because "we only collect
anonymous usage data" is what every company says and none of them show you the
line.

Two buttons, equal weight, neither default. No pre-ticked box, no "Not now"
that means "ask me again tomorrow", no styling that makes yes the bright one.
An opt-in obtained by design pressure is not consent, and this audience — who
run Little Snitch and read release notes — would spot it and be right to.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .. import APP_NAME


class TelemetryConsentDialog(QDialog):
    def __init__(self, sample_payload: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Help me see if {APP_NAME} is being used?")
        self.setMinimumWidth(520)

        head = QLabel(f"Help me see if {APP_NAME} is being used?")
        head.setObjectName("consentHead")
        head.setWordWrap(True)

        body = QLabel(
            f"{APP_NAME} is a one-person project and I have no idea whether the "
            "people who download it actually use it. If you turn this on, "
            f"{APP_NAME} sends this, once a day:")
        body.setWordWrap(True)

        # Monospace, selectable: it is evidence, and evidence you can copy.
        payload = QLabel(sample_payload)
        payload.setObjectName("consentPayload")
        payload.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        payload.setWordWrap(True)

        tail = QLabel(
            "That is everything. The id is a random number for this installation "
            "that changes every month. Nothing about you, your machine or your "
            "images is sent, and your IP address is not stored.\n\n"
            "You can change this any time in Settings. — Andreas")
        tail.setWordWrap(True)

        no = QPushButton("No thanks")
        yes = QPushButton("Yes, send it")
        # Neither is `setDefault(True)` and neither is objectName("primary"):
        # Return does not answer this question for the user.
        no.clicked.connect(self.reject)
        yes.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(no)
        buttons.addWidget(yes)

        lay = QVBoxLayout(self)
        for w in (head, body, payload, tail):
            lay.addWidget(w)
        lay.addLayout(buttons)

        self.no_btn, self.yes_btn = no, yes
