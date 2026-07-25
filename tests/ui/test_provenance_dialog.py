import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QDialog  # noqa: E402
from nocturne.ui.provenance_dialog import ProvenanceDialog  # noqa: E402


class _Settings:
    base_dir = None


def _dialog(qtbot, monkeypatch, saved, copied):
    d = ProvenanceDialog("# Report\n\nbody", _Settings(),
                         save_runner=lambda text, path: saved.append((text, path)),
                         clipboard_runner=lambda text: copied.append(text))
    qtbot.addWidget(d)
    return d


def test_copy_calls_clipboard_runner(qtbot, monkeypatch):
    copied = []
    d = _dialog(qtbot, monkeypatch, [], copied)
    d._copy_btn.click()
    assert copied == ["# Report\n\nbody"]


def test_save_writes_raw_markdown(qtbot, monkeypatch, tmp_path):
    saved = []
    d = _dialog(qtbot, monkeypatch, saved, [])
    monkeypatch.setattr("nocturne.ui.provenance_dialog.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "p.md"), "")))
    d._save_btn.click()
    assert saved and saved[0][0] == "# Report\n\nbody"
    assert saved[0][1].endswith("p.md")


def test_close_rejects(qtbot, monkeypatch):
    d = _dialog(qtbot, monkeypatch, [], [])
    d._close_btn.click()
    assert d.result() == QDialog.DialogCode.Rejected
