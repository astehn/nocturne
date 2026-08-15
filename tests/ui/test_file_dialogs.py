import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QWidget  # noqa: E402

from nocturne.ui import file_dialogs  # noqa: E402

# Captured at import, before conftest's _no_real_file_dialogs guard replaces it.
# These two tests are the ones that must exercise the real thing.
_REAL_PREPARE = file_dialogs._prepare


class _Recorder:
    """Stands in for QFileDialog so the tests never open a real panel: records
    the dialog it would have shown, and answers with a fixed choice."""

    def __init__(self, accept=True, files=("/tmp/chosen.fits",), name_filter="FITS (*.fits)"):
        self.accept = accept
        self.files = list(files)
        self.name_filter = name_filter
        self.made = []

    def __call__(self, parent, caption, directory, filters):
        dlg = QFileDialog(None)          # real object, never shown
        dlg.exec = lambda: 1 if self.accept else 0
        dlg.selectedFiles = lambda: self.files
        dlg.selectedNameFilter = lambda: self.name_filter
        self.made.append({"parent": parent, "caption": caption,
                          "directory": directory, "filters": filters, "dlg": dlg})
        return dlg


def _patch(monkeypatch, rec):
    def prepare(parent, caption, directory, filters):
        dlg = rec(parent, caption, directory, filters)
        dlg.setWindowModality(Qt.WindowModality.WindowModal if parent is not None
                              else Qt.WindowModality.ApplicationModal)
        return dlg
    monkeypatch.setattr(file_dialogs, "_prepare", prepare)
    return rec


def test_a_parented_dialog_is_window_modal_so_macos_makes_it_a_sheet(qtbot):
    """THE fix. An application-modal panel is placed by macOS on the screen with
    the menu bar, so with the app on a second monitor it opens where the user is
    not looking — and if the window is fullscreen, on another Space entirely. It
    holds the modal session, every click beeps, and the app appears hung.
    Window-modal makes Qt attach it to the parent window as a sheet, which
    cannot move to another screen."""
    parent = QWidget()
    qtbot.addWidget(parent)
    dlg = _REAL_PREPARE(parent, "Pick", "/tmp", "")
    assert dlg.windowModality() == Qt.WindowModality.WindowModal
    assert dlg.parent() is parent


def test_an_unparented_dialog_stays_application_modal(qtbot):
    """Window-modal with no parent would have no window to attach to, and Qt
    would show nothing at all."""
    dlg = _REAL_PREPARE(None, "Pick", "/tmp", "")
    assert dlg.windowModality() == Qt.WindowModality.ApplicationModal


def test_choose_folder_returns_the_selection(qtbot, monkeypatch):
    rec = _patch(monkeypatch, _Recorder(files=["/tmp/some/folder"]))
    parent = QWidget(); qtbot.addWidget(parent)
    assert file_dialogs.choose_folder(parent, "Folder", "/start") == "/tmp/some/folder"
    assert rec.made[0]["caption"] == "Folder"
    assert rec.made[0]["directory"] == "/start"


def test_cancelling_returns_empty_not_a_stale_path(qtbot, monkeypatch):
    """Every call site treats "" as "the user changed their mind". Returning the
    last selection on cancel would silently export to the wrong place."""
    _patch(monkeypatch, _Recorder(accept=False))
    parent = QWidget(); qtbot.addWidget(parent)
    assert file_dialogs.choose_folder(parent, "Folder") == ""
    assert file_dialogs.open_file(parent, "Open") == ""
    assert file_dialogs.save_file(parent, "Save") == ("", "")


def test_save_file_reports_the_chosen_filter(qtbot, monkeypatch):
    """export_final picks the extension from the filter the user ended on, so
    dropping it would write a PNG named .tiff."""
    _patch(monkeypatch, _Recorder(files=["/tmp/out.png"], name_filter="PNG (*.png)"))
    parent = QWidget(); qtbot.addWidget(parent)
    assert file_dialogs.save_file(parent, "Export", "/tmp",
                                  "TIFF (*.tiff);;PNG (*.png)") == ("/tmp/out.png", "PNG (*.png)")


def test_no_static_file_dialogs_remain_in_the_ui():
    """The static QFileDialog.getXxx helpers are ALWAYS application-modal, which
    is the bug. A new call site added later would reintroduce it silently, so
    this fails the build instead."""
    import pathlib
    ui = pathlib.Path(__file__).resolve().parents[2] / "nocturne" / "ui"
    offenders = []
    for path in sorted(ui.glob("*.py")):
        if path.name == "file_dialogs.py":
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "QFileDialog.get" in line:
                offenders.append(f"{path.name}:{n}")
    assert offenders == [], (
        "use nocturne.ui.file_dialogs instead — the static helpers are "
        f"application-modal and strand on the wrong screen: {offenders}")
