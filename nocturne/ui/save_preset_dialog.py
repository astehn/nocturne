"""Save as Preset… — name the look, see what it will carry, and what it won't.

The preview is the picture as it stands, so the library shows what the preset
made rather than a description of it. Left-out steps are named here, at save
time, because this is the only moment the user can still do something about it
(re-run Star Spikes, say) — on apply it is too late to learn the look is partial.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget,
                               QMessageBox, QVBoxLayout)

from ..recipe import PRESET_ONLY_STAGES
from ..user_presets import MAX_NAME
from .theme import WARNING

_NEVER_SAVED = "Crop, rotate, flip and Trim belong to this picture and are not saved."
_NOTHING = "Nothing to save yet — every step so far belongs to this picture."
_PREVIEW_EDGE = 320
_MIN_WIDTH = 380


def _fit_name(name: str) -> str:
    """A long FITS target cut at a word, not mid-word by setMaxLength."""
    name = name.strip()
    if len(name) <= MAX_NAME:
        return name
    cut = name[:MAX_NAME + 1]
    head = cut.rsplit(None, 1)[0] if " " in cut.strip() else ""
    return (head or name[:MAX_NAME]).strip()


def _left_out_line(name: str) -> str:
    # A preset-only step is left out only when it predates recording its values.
    if name in PRESET_ONLY_STAGES:
        return f"Not included: {name} (saved before its settings were recorded)."
    return f"Not included: {name} — a preset cannot replay it."


class SavePresetDialog(QDialog):
    def __init__(self, preview: bytes, default_name: str, step_names: list[str],
                 left_out: list[str], existing: Callable[[str], bool], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save as Preset")
        self.setMinimumWidth(_MIN_WIDTH)
        self._existing = existing
        self._has_steps = bool(step_names)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = QPixmap()
        self.preview_pixmap: QPixmap | None = None
        if preview and pm.loadFromData(preview, "JPG"):
            # Scaled in device pixels, then tagged: sharp on a Retina screen.
            dpr = self.devicePixelRatioF()
            edge = round(_PREVIEW_EDGE * dpr)
            pm = pm.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.preview_pixmap = pm     # QLabel.pixmap() re-renders at the label's own ratio
            self.preview_label.setPixmap(pm)
        else:
            self.preview_label.hide()

        self.name_edit = QLineEdit(_fit_name(default_name))
        self.name_edit.setPlaceholderText("Name, e.g. the target")
        self.name_edit.setMaxLength(MAX_NAME)

        self.steps_list = QListWidget()
        self.steps_list.addItems(step_names)
        self.steps_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.steps_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        never = QLabel(_NEVER_SAVED)
        never.setObjectName("stepExplainer")
        never.setWordWrap(True)

        self.empty_label = QLabel(_NOTHING)
        self.empty_label.setObjectName("emptyNote")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(not self._has_steps)

        self.left_out_label = QLabel("\n".join(_left_out_line(n) for n in left_out))
        self.left_out_label.setWordWrap(True)
        self.left_out_label.setStyleSheet(f"color: {WARNING};")
        self.left_out_label.setVisible(bool(left_out))

        # Why the last Save did not land; the dialog comes back with it shown.
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {WARNING};")
        self.error_label.hide()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.preview_label)
        lay.addWidget(QLabel("Name"))
        lay.addWidget(self.name_edit)
        lay.addWidget(QLabel("Steps"))
        lay.addWidget(self.steps_list)
        lay.addWidget(self.empty_label)
        lay.addWidget(self.left_out_label)
        lay.addWidget(never)
        lay.addWidget(self.error_label)
        lay.addWidget(buttons)

        self.name_edit.textChanged.connect(self._sync)
        self._sync()

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def chosen_name(self) -> str:
        return self.name_edit.text().strip()

    def _sync(self) -> None:
        self.save_btn.setEnabled(self._has_steps and bool(self.chosen_name()))

    def _ask_replace(self, name: str) -> bool:
        resp = QMessageBox.question(
            self, "Save as Preset",
            f"A preset called “{name}” already exists. Replace it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return resp == QMessageBox.StandardButton.Yes

    def _on_save(self) -> None:
        if not self.save_btn.isEnabled():
            return
        name = self.chosen_name()
        if self._existing(name) and not self._ask_replace(name):
            return
        self.accept()
