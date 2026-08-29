from __future__ import annotations

import os

from astropy.io import fits
from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ..core.combine import OFFSET_TOLERANCE_PX, align_to, combine_gases, measure_offset
from ..core.fits_io import _parse_metadata, load_mono_master
from ..settings import start_dir
from . import file_dialogs
from .worker import run_async

BLURB = (
    "Builds a two-gas master from a Ha file and an OIII file — the pair the "
    "Ha/OIII extractor can write, or channels from anywhere else. The result is "
    "linear, Ha in red and OIII in green and blue, so process it like any other "
    "stack and reach for <b>Narrowband</b> after the stretch to set the palette."
)


class _Signals(QObject):
    checked = Signal(float, float)
    failed = Signal(str)


def _picker_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit)
    btn = QPushButton("Browse…")
    btn.clicked.connect(on_browse)
    lay.addWidget(btn)
    return row


class CombineDialog(QDialog):
    def __init__(self, settings, parent=None, on_master=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Combine Ha + OIII")
        self.setMinimumWidth(560)
        self._settings = settings
        self._on_master = on_master
        self._busy = False
        self._shift = (0.0, 0.0)
        self._pool = QThreadPool.globalInstance()
        self._loader = load_mono_master          # injectable for tests

        self.blurb = QLabel(BLURB)
        self.blurb.setWordWrap(True)
        self.blurb.setObjectName("stepDesc")

        self.ha_edit = QLineEdit()
        self.ha_edit.setToolTip(
            "A stacked Ha frame — a mono FITS. The Ha/OIII extractor writes one "
            "when 'Also write separate Ha and OIII files' is ticked.")
        self.oiii_edit = QLineEdit()
        self.oiii_edit.setToolTip(
            "A stacked OIII frame, the same size as the Ha one.")
        for edit in (self.ha_edit, self.oiii_edit):
            edit.editingFinished.connect(self.check_alignment)

        self.balance_slider = QSlider(Qt.Orientation.Horizontal)
        self.balance_slider.setRange(0, 100)
        self.balance_slider.setValue(100)
        self.balance_slider.setToolTip(
            "How far to lift OIII toward Ha, while the data is still linear. At "
            "100% the two sit level, which is what the extractor's own colour "
            "master contains. At 0% OIII stays as faint as it really is — the "
            "true ratio, which nothing downstream can recover once it is gone.")
        self.balance_label = QLabel("matched to Ha")
        self.balance_slider.valueChanged.connect(self._on_balance)

        self.align_check = QCheckBox("Align OIII to Ha before combining")
        self.align_check.setChecked(True)
        self.align_note = QLabel("")
        self.align_note.setWordWrap(True)
        self.align_row = QWidget()
        row = QHBoxLayout(self.align_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.align_check)
        row.addStretch(1)
        self.align_row.setVisible(False)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        self._signals = _Signals()
        self._signals.checked.connect(self._on_checked)
        self._signals.failed.connect(self._on_failed)

        form = QFormLayout()
        form.addRow("Ha", _picker_row(self.ha_edit,
                                      lambda: self._browse(self.ha_edit, "Ha")))
        form.addRow("OIII", _picker_row(self.oiii_edit,
                                        lambda: self._browse(self.oiii_edit, "OIII")))
        bal = QHBoxLayout()
        bal.addWidget(self.balance_slider)
        bal.addWidget(self.balance_label)
        bal_wrap = QWidget()
        bal_wrap.setLayout(bal)
        form.addRow("Balance", bal_wrap)
        form.addRow("", self.align_row)

        self._go = QPushButton("Combine")
        self._go.setObjectName("primary")
        self._go.clicked.connect(self.run)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self._go)
        buttons.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.blurb)
        root.addLayout(form)
        root.addWidget(self.align_note)
        root.addStretch(1)
        root.addWidget(self.status)
        root.addLayout(buttons)

    # --- helpers ---
    def _browse(self, edit: QLineEdit, gas: str) -> None:
        path = file_dialogs.open_file(self, f"{gas} frame",
                                      start_dir(self._settings.base_dir),
                                      "FITS (*.fits *.fit *.fts)")
        if path:
            edit.setText(path)
            self.check_alignment()

    def _on_balance(self, value: int) -> None:
        self.balance_label.setText(
            "matched to Ha" if value == 100
            else "as measured" if value == 0 else f"{value}% toward Ha")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._go.setEnabled(not busy)

    def _paths(self) -> tuple:
        return self.ha_edit.text().strip(), self.oiii_edit.text().strip()

    # --- alignment ---
    def check_alignment(self) -> None:
        """Measure how far apart the two are, as soon as both are chosen.

        Silent under half a pixel — every pair the extractor writes is aligned,
        and a warning nobody needs teaches people to ignore warnings.
        """
        ha_path, oiii_path = self._paths()
        if self._busy or not (ha_path and oiii_path) or ha_path == oiii_path:
            return
        loader = self._loader
        self._set_busy(True)

        def work():
            ha, oiii = loader(ha_path), loader(oiii_path)
            if ha.shape != oiii.shape:
                raise ValueError(f"Ha is {ha.shape[1]}x{ha.shape[0]} but "
                                 f"OIII is {oiii.shape[1]}x{oiii.shape[0]}")
            return measure_offset(ha, oiii)

        run_async(self._pool, work,
                  lambda s: self._signals.checked.emit(s[0], s[1]),
                  lambda exc: self._signals.failed.emit(str(exc)))

    def _on_checked(self, dy: float, dx: float) -> None:
        self._set_busy(False)
        self._shift = (dy, dx)
        far = max(abs(dy), abs(dx))
        if far < OFFSET_TOLERANCE_PX:
            self.align_row.setVisible(False)
            self.align_note.setText("")
            self.status.setText("Ready.")
            return
        self.align_check.setChecked(True)
        self.align_row.setVisible(True)
        self.align_note.setText(
            f"These two are offset by {far:.1f} px. Stars will show colour "
            "fringes if they are combined as they are.")
        self.status.setText(f"Offset {far:.1f} px.")

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.align_row.setVisible(False)
        self.status.setText(message)

    # --- run ---
    def run(self) -> None:
        if self._busy:
            self.status.setText("Please wait — still working…")
            return
        ha_path, oiii_path = self._paths()
        if not (ha_path and oiii_path):
            self.status.setText("Pick a Ha file and an OIII file.")
            return
        if os.path.abspath(ha_path) == os.path.abspath(oiii_path):
            self.status.setText("Ha and OIII are the same file — pick two.")
            return
        loader = self._loader
        balance = self.balance_slider.value() / 100.0
        align = self.align_check.isChecked() and self.align_row.isVisible()
        shift = self._shift
        self.status.setText("Combining…")
        self._set_busy(True)

        def work():
            ha, oiii = loader(ha_path), loader(oiii_path)
            if ha.shape != oiii.shape:
                raise ValueError(f"Ha is {ha.shape[1]}x{ha.shape[0]} but "
                                 f"OIII is {oiii.shape[1]}x{oiii.shape[0]} — "
                                 "they must match")
            if align:
                oiii = align_to(oiii, shift)
            # Provenance rides along from the Ha file: a combined master must be
            # able to name its camera and filter like any other (see 535f156).
            h, w = ha.shape
            meta = _parse_metadata(fits.getheader(ha_path), h, w)
            return combine_gases(ha, oiii, balance, metadata=meta)

        run_async(self._pool, work, self._on_done,
                  lambda exc: self._signals.failed.emit(str(exc)))

    def _on_done(self, image) -> None:
        self._set_busy(False)
        self.status.setText("Done.")
        if self._on_master is not None:
            self._on_master(image)
        self.accept()
