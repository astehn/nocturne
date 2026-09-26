from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ..settings import (TOOL_CANDIDATES, Settings, astap_valid, is_tool,
                        detect_tool_paths, resolve_binary)
from ..tools.probe import probe_binary
from . import file_dialogs
from .theme import ACCENT


# The longest path a default install gives (RC-Astro's CLI on macOS): the
# path boxes are sized to show it whole.
_TYPICAL_PATH = "/Applications/RC-Astro/CLI/rc-astro"

# Where to download each external tool (shown as a link next to its path row).
DOWNLOAD_URLS = {
    "graxpert": "https://graxpert.com",
    "rcastro": "https://www.rc-astro.com",
    "astap": "https://www.hnsky.org/astap.htm",
    # The CLI page, not the homepage: the homepage links no downloads, and
    # the site also ships a PixInsight module that Nocturne cannot drive.
    # Sending someone to the wrong one of those two is a support email.
    "starnet": "https://starnetastro.com/cli-tools/starnet/",
}


def _path_row(edit: QLineEdit, on_test, result: QLabel,
              download_url: str | None = None, caption: str = "Locate tool") -> QWidget:
    row = QWidget()
    outer = QVBoxLayout(row)
    outer.setContentsMargins(0, 0, 0, 0)
    line = QHBoxLayout()
    line.addWidget(edit, 1)     # its minimum width: SettingsDialog._fit_path_boxes
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
        # The app's accent, not Qt's default #0000ff, which is near-invisible
        # on the dark dialog.
        link = QLabel(f'<a href="{download_url}" style="color:{ACCENT}; '
                      f'text-decoration:none">Download&nbsp;↗</a>')
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
        self._starnet = QLineEdit(settings.starnet_path)
        self._handle = QLineEdit(settings.handle)
        self._handle.setPlaceholderText("@yourhandle — shown on shared images")
        self._gx_result = QLabel("")
        self._rc_result = QLabel("")
        self._astap_result = QLabel("")
        self._starnet_result = QLabel("")
        self._starnet_result.setWordWrap(True)
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

        # Three tabs (screen-size piece 3, Andreas 2026-09-26): the single
        # column grew with every tool and got tall on a laptop. Things you set
        # once live here; choices remembered where you make them (Share's
        # caption, the title plate, annotation layers) stay in their tools.
        self.tabs = QTabWidget()

        general = QWidget()
        g = QFormLayout(general)
        g.addRow("Default folder", _folder_row(self._dir))
        g.addRow("Handle (for shares)", self._handle)
        self.tabs.addTab(general, "General")

        tools = QWidget()
        t = QFormLayout(tools)
        t.addRow("GraXpert (required)",
                 _path_row(self._gx, self._test_graxpert, self._gx_result,
                           DOWNLOAD_URLS["graxpert"],
                           "Select GraXpert.app (or its executable)"))
        t.addRow("RC-Astro (optional)",
                 _path_row(self._rc, self._test_rcastro, self._rc_result,
                           DOWNLOAD_URLS["rcastro"],
                           "Select the rc-astro command (RC-Astro/CLI/rc-astro)"))
        t.addRow("StarNet2 (optional)",
                 _path_row(self._starnet, self._test_starnet, self._starnet_result,
                           DOWNLOAD_URLS["starnet"],
                           "Select the starnet2 executable"))
        t.addRow("ASTAP (optional)",
                 _path_row(self._astap, self._test_astap, self._astap_result,
                           DOWNLOAD_URLS["astap"],
                           "Select ASTAP.app (or its executable)"))
        for edit, _label, _name in self.tool_fields().values():
            edit.textChanged.connect(self._refresh_status)
        self._refresh_status()
        t.addRow("", self.rescan_btn)
        t.addRow("", self.rescan_result)
        t.addRow("Preferred denoise engine", self.denoise_box)
        note = QLabel("RC-Astro unlocks BlurX / NoiseX / StarX and the starless+stars export. "
                      "ASTAP adds plate-solving — install it and its D05 star database "
                      "(from the ASTAP page) for target identification and annotation.")
        note.setWordWrap(True)
        t.addRow(note)
        self.tabs.addTab(tools, "External tools")

        # The page you open to check exactly what leaves this computer, so it
        # SAYS so on the page — the tooltips were the only place it was written.
        privacy = QWidget()
        pv = QVBoxLayout(privacy)
        for box in (self.check_updates, self.telemetry):
            pv.addWidget(box)
            why = QLabel(box.toolTip())
            why.setWordWrap(True)
            why.setObjectName("stepDesc")          # the app's quiet explanatory text
            why.setContentsMargins(24, 0, 0, 10)   # under the box's label, not its tick
            pv.addWidget(why)
        pv.addStretch(1)
        self.tabs.addTab(privacy, "Privacy")

        # QTabWidget sizes to its LARGEST page, so switching tabs never resizes
        # the window — nothing moves (piece 1's rule).
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fit_path_boxes()

    def _fit_path_boxes(self) -> None:
        """Wide enough to read a real install path whole. In tabs the dialog
        sizes to its content, and the boxes shrank to show "ert.app" of
        GraXpert.app. Measured with the POLISHED font (the app stylesheet's
        size and padding) — unpolished it came out 1 px short — and before the
        dialog is shown: widening it afterwards made the window jump on the
        first tab switch."""
        for edit, _label, _name in self.tool_fields().values():
            edit.ensurePolished()
            edit.setMinimumWidth(edit.fontMetrics().horizontalAdvance(_TYPICAL_PATH) + 40)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_path_boxes()

    def _test_starnet(self) -> None:
        """Runs it with no arguments: StarNet2 prints its usage and exits, which
        is enough to prove the binary and its weights package are both there —
        the usual failure is a copied executable without the weights beside it.
        """
        path = resolve_binary(self._starnet.text().strip())
        self._starnet_result.setText(
            "Found" if is_tool(path) else "Not found — point at the starnet2 executable")

    def _rescan(self) -> None:
        """Look again, and repair anything broken.

        Reads the LINE EDITS rather than the saved settings, so it acts on what
        the user is looking at — including a path they have just fumbled and not
        yet saved, which is the case this button exists for. `replace_invalid`
        lets it overwrite a path that does not resolve; a working custom path is
        still left alone.
        """
        tools = self.tool_fields()
        current = Settings(**{k: e.text().strip() for k, (e, _l, _n) in tools.items()})
        found = detect_tool_paths(current, TOOL_CANDIDATES, replace_invalid=True)
        # .get, not [k]: the detector's table is the authority on what exists
        # and this dialog may not have caught up. A tool it cannot show is a
        # test failure (test_the_dialog_knows_every_tool_the_detector_knows),
        # never a KeyError under the user's cursor.
        for key, value in found.items():
            if key in tools:
                tools[key][0].setText(value)
        if found:
            self.rescan_result.setText(
                "✓ Found " + ", ".join(tools[k][2] for k in sorted(found) if k in tools))
        else:
            configured = [e.text().strip() for e, _l, _n in tools.values() if e.text().strip()]
            self.rescan_result.setText(
                "Everything already set up." if len(configured) == len(tools)
                else "Nothing found in the usual places — use Browse… if a tool "
                     "is installed somewhere else.")

    def _show_result(self, label: QLabel, path: str, args: list[str]) -> None:
        if not path.strip():
            label.setText("✗ No path set")
            return
        ok, msg = probe_binary(resolve_binary(path.strip()), args, runner=self._probe_runner)
        label.setText(("✓ " if ok else "✗ ") + msg)

    def tool_fields(self) -> dict:
        """{settings field: (line edit, status label, display name)}.

        THE one place a tool is listed. StarNet2 was added to this dialog on
        2026-09-18 and left out of FOUR separate hand-written collections: the
        status loop, the textChanged connections, _rescan's field map and
        _rescan's name map. Each was found separately, by Andreas, using the
        app — the last one as `KeyError: 'starnet_path'` under his cursor when
        he pressed Rescan.

        Keys are the Settings field names, because that is what
        detect_tool_paths returns; test_the_dialog_knows_every_tool_the_detector_knows
        fails if the two ever drift.
        """
        return {
            "graxpert_path": (self._gx, self._gx_result, "GraXpert"),
            "rcastro_path": (self._rc, self._rc_result, "RC-Astro"),
            "starnet_path": (self._starnet, self._starnet_result, "StarNet2"),
            "astap_path": (self._astap, self._astap_result, "ASTAP"),
        }

    def _refresh_status(self) -> None:
        """Say where each tool stands the moment the dialog opens.

        The three status chips used to live on the toolbar, permanently, for a
        question you answer once during setup. This is where the paths are, so
        this is where the answer belongs — but it has to be there without
        pressing Test three times, or moving it would just hide it.

        Cheap check only (executable, not run): Test is what actually runs the
        program, and this fires on every keystroke.
        """
        for edit, label, name in self.tool_fields().values():
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
            starnet_path=self._starnet.text().strip(),
            base_dir=self._dir.text().strip(),
            denoise_engine=("graxpert" if self.denoise_box.currentText() == "GraXpert"
                            else "rcastro"),
            handle=self._handle.text().strip(),
            check_updates=self.check_updates.isChecked(),
            telemetry=("on" if self.telemetry.isChecked() else "off"),
        )
