from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..settings import (TOOL_CANDIDATES, Settings, astap_valid, is_tool,
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
        # Kept so result_settings can AMEND it. It used to build a fresh
        # Settings() from the fields on this form, which silently reset every
        # field the form does not show — measured 2026-09-17: opening Settings
        # and pressing OK discarded the user's plate preset, their saved plate
        # looks, the recent-projects list, help_expanded and annotation_density.
        # Six kinds of state, lost to a dialog they may have opened to read a
        # path. A new setting added anywhere else in the app would join them.
        self._settings = settings
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

        self.check_updates = QCheckBox("Check for a new version at startup")
        self.check_updates.setChecked(settings.check_updates)
        self.check_updates.setToolTip(
            "Asks github.com whether a newer Nocturne has been released. Your IP "
            "address reaches GitHub as part of that request, as it does for any "
            "web request. Nothing about you or your images is sent, and Nocturne "
            "itself receives nothing.")

        # The consent dialog promises "you can change this any time in Settings",
        # so this box is part of that promise, not a nicety. A checkbox, though
        # the setting has THREE values: "unset" only exists until the question is
        # answered, and ticking or unticking here is an answer either way.
        self.telemetry = QCheckBox("Count my use of Nocturne (once a day, anonymously)")
        self.telemetry.setChecked(settings.telemetry == "on")
        self.telemetry.setToolTip(
            "Sends {\"event\": \"daily\", \"version\": …, \"id\": …} once a day. "
            "The id is a random number for this installation that changes every "
            "month. No IP address is stored and nothing about your images is sent.")

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
        for edit in (self._gx, self._rc, self._astap):
            edit.textChanged.connect(self._refresh_status)
        self._refresh_status()
        form.addRow("", self.rescan_btn)
        form.addRow("", self.rescan_result)
        form.addRow("Handle (for shares)", self._handle)
        form.addRow("Preferred denoise engine", self.denoise_box)
        form.addRow("", self.check_updates)
        form.addRow("", self.telemetry)
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

    def _refresh_status(self) -> None:
        """Say where each tool stands the moment the dialog opens.

        The three status chips used to live on the toolbar, permanently, for a
        question you answer once during setup. This is where the paths are, so
        this is where the answer belongs — but it has to be there without
        pressing Test three times, or moving it would just hide it.

        Cheap check only (executable, not run): Test is what actually runs the
        program, and this fires on every keystroke.
        """
        for edit, label, name in ((self._gx, self._gx_result, "GraXpert"),
                                  (self._rc, self._rc_result, "RC-Astro"),
                                  (self._astap, self._astap_result, "ASTAP")):
            path = edit.text().strip()
            if not path:
                label.setText('<span style="color:#6b6f76">Not set — optional</span>'
                              if name != "GraXpert" else
                              '<span style="color:#6b6f76">Not set</span>')
            elif is_tool(path):
                label.setText(f'<span style="color:#3fb950">✓</span> {name} found')
            else:
                label.setText('<span style="color:#f85149">✗</span> Set, but cannot be '
                              'run — moved, renamed, or not a program')

    def _test_graxpert(self) -> None:
        self._show_result(self._gx_result, self._gx.text(), ["-v"])

    def _test_rcastro(self) -> None:
        self._show_result(self._rc_result, self._rc.text(), ["--no-banner", "--help"])

    def _test_astap(self) -> None:
        ok = astap_valid(Settings(astap_path=self._astap.text().strip()))
        self._astap_result.setText("✓ Found ASTAP" if ok else "✗ Not found")

    def result_settings(self) -> Settings:
        """The settings this dialog was given, with THIS FORM's fields changed.

        `replace`, not a new Settings: anything not on this form must survive
        untouched. tests/ui/test_settings_dialog.py captures the whole dataclass
        before and asserts field-by-field that only these changed.
        """
        import dataclasses
        return dataclasses.replace(
            self._settings,
            graxpert_path=self._gx.text().strip(),
            rcastro_path=self._rc.text().strip(),
            astap_path=self._astap.text().strip(),
            base_dir=self._dir.text().strip(),
            denoise_engine=("graxpert" if self.denoise_box.currentText() == "GraXpert"
                            else "rcastro"),
            handle=self._handle.text().strip(),
            check_updates=self.check_updates.isChecked(),
            telemetry=("on" if self.telemetry.isChecked() else "off"),
        )
