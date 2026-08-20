from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..settings import (TOOL_CANDIDATES, Settings, astap_valid,
                        detect_tool_paths, resolve_binary)
from ..tools.probe import probe_binary
from . import file_dialogs


# Where to download each external tool (shown as a link next to its path row).
DOWNLOAD_URLS = {
    "graxpert": "https://graxpert.com",
    "rcastro": "https://www.rc-astro.com",
    "astap": "https://www.hnsky.org/astap.htm",
}


def _path_row(edit: QLineEdit, on_test, result: QLabel,
              download_url: str | None = None, caption: str = "Locate tool") -> QWidget:
    row = QWidget()
    outer = QVBoxLayout(row)
    outer.setContentsMargins(0, 0, 0, 0)
    line = QHBoxLayout()
    line.addWidget(edit)
    browse = QPushButton("Browse…")
    # The caption is REQUIRED by open_file. Omitting it raised inside the slot,
    # where Qt prints to stderr and the button just looks dead — which is how
    # this survived from 2026-08-15 into five releases.
    browse.clicked.connect(
        lambda: edit.setText(file_dialogs.open_file(row, caption) or edit.text())
    )
    test = QPushButton("Test")
    test.clicked.connect(on_test)
    line.addWidget(browse)
    line.addWidget(test)
    if download_url:
        link = QLabel(f'<a href="{download_url}">Download&nbsp;↗</a>')
        link.setOpenExternalLinks(True)      # opens in the user's browser
        line.addWidget(link)
    outer.addLayout(line)
    outer.addWidget(result)
    return row


def _folder_row(edit: QLineEdit) -> QWidget:
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.addWidget(edit)
    browse = QPushButton("Browse…")
    browse.clicked.connect(
        lambda: edit.setText(
            file_dialogs.choose_folder(row, "Default image folder") or edit.text())
    )
    line.addWidget(browse)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._probe_runner = None  # injectable for tests
        self._dir = QLineEdit(settings.base_dir)
        self._gx = QLineEdit(settings.graxpert_path)
        self._rc = QLineEdit(settings.rcastro_path)
        self._astap = QLineEdit(settings.astap_path)
        self._handle = QLineEdit(settings.handle)
        self._handle.setPlaceholderText("@yourhandle — shown on shared images")
        self._gx_result = QLabel("")
        self._rc_result = QLabel("")
        self._astap_result = QLabel("")
        self._gx_result.setWordWrap(True)
        self._rc_result.setWordWrap(True)
        self.denoise_box = QComboBox()
        self.denoise_box.addItems(["RC-Astro", "GraXpert"])
        self.denoise_box.setCurrentText(
            "GraXpert" if settings.denoise_engine == "graxpert" else "RC-Astro")

        self.rescan_btn = QPushButton("Rescan for installed apps")
        self.rescan_btn.clicked.connect(self._rescan)
        self.rescan_result = QLabel("")
        self.rescan_result.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("Default folder", _folder_row(self._dir))
        form.addRow("GraXpert (required)",
                    _path_row(self._gx, self._test_graxpert, self._gx_result,
                              DOWNLOAD_URLS["graxpert"],
                              "Select GraXpert.app (or its executable)"))
        form.addRow("RC-Astro (optional)",
                    _path_row(self._rc, self._test_rcastro, self._rc_result,
                              DOWNLOAD_URLS["rcastro"],
                              "Select the rc-astro command (RC-Astro/CLI/rc-astro)"))
        form.addRow("ASTAP (optional)",
                    _path_row(self._astap, self._test_astap, self._astap_result,
                              DOWNLOAD_URLS["astap"],
                              "Select ASTAP.app (or its executable)"))
        form.addRow("", self.rescan_btn)
        form.addRow("", self.rescan_result)
        form.addRow("Handle (for shares)", self._handle)
        form.addRow("Preferred denoise engine", self.denoise_box)
        note = QLabel("RC-Astro unlocks BlurX / NoiseX / StarX and the starless+stars export. "
                      "ASTAP adds plate-solving — install it and its D05 star database "
                      "(from the ASTAP page) for target identification and annotation.")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _rescan(self) -> None:
        """Look again, and repair anything broken.

        Reads the LINE EDITS rather than the saved settings, so it acts on what
        the user is looking at — including a path they have just fumbled and not
        yet saved, which is the case this button exists for. `replace_invalid`
        lets it overwrite a path that does not resolve; a working custom path is
        still left alone.
        """
        fields = {"graxpert_path": self._gx, "rcastro_path": self._rc,
                  "astap_path": self._astap}
        current = Settings(**{k: e.text().strip() for k, e in fields.items()})
        found = detect_tool_paths(current, TOOL_CANDIDATES, replace_invalid=True)
        for key, value in found.items():
            fields[key].setText(value)
        if found:
            names = {"graxpert_path": "GraXpert", "rcastro_path": "RC-Astro",
                     "astap_path": "ASTAP"}
            self.rescan_result.setText(
                "✓ Found " + ", ".join(names[k] for k in sorted(found)))
        else:
            configured = [e.text().strip() for e in fields.values() if e.text().strip()]
            self.rescan_result.setText(
                "Everything already set up." if len(configured) == len(fields)
                else "Nothing found in the usual places — use Browse… if a tool "
                     "is installed somewhere else.")

    def _show_result(self, label: QLabel, path: str, args: list[str]) -> None:
        if not path.strip():
            label.setText("✗ No path set")
            return
        ok, msg = probe_binary(resolve_binary(path.strip()), args, runner=self._probe_runner)
        label.setText(("✓ " if ok else "✗ ") + msg)

    def _test_graxpert(self) -> None:
        self._show_result(self._gx_result, self._gx.text(), ["-v"])

    def _test_rcastro(self) -> None:
        self._show_result(self._rc_result, self._rc.text(), ["--no-banner", "--help"])

    def _test_astap(self) -> None:
        ok = astap_valid(Settings(astap_path=self._astap.text().strip()))
        self._astap_result.setText("✓ Found ASTAP" if ok else "✗ Not found")

    def result_settings(self) -> Settings:
        return Settings(
            graxpert_path=self._gx.text().strip(),
            rcastro_path=self._rc.text().strip(),
            astap_path=self._astap.text().strip(),
            base_dir=self._dir.text().strip(),
            denoise_engine=("graxpert" if self.denoise_box.currentText() == "GraXpert"
                            else "rcastro"),
            handle=self._handle.text().strip(),
        )
