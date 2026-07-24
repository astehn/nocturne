import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.share_dialog import ShareDialog
from nocturne.settings import Settings


def _rgb(h=400, w=300):
    a = np.zeros((h, w, 3), np.uint8); a[:] = 180
    return a

def _dlg(qtbot, meta=None):
    d = ShareDialog(_rgb(), meta or {"target": "NGC 7000", "source_label": "ngc7000.fits"},
                    Settings(handle="me"))
    qtbot.addWidget(d)
    return d

def test_dialog_builds_with_preview(qtbot):
    d = _dlg(qtbot)
    assert d._compose_current().width() > 0

def test_selecting_aspect_locks_ratio(qtbot):
    d = _dlg(qtbot)
    d._select_aspect(1.0, "1:1")
    out = d._compose_current()
    assert abs(out.width() - out.height()) <= 2      # square

def test_caption_toggle_controls_band(qtbot):
    d = _dlg(qtbot)
    d._set_caption(False)
    assert d._current_caption() == ""
    d._set_caption(True)
    assert "NGC 7000" in d._current_caption()

def test_export_uses_injected_saver(qtbot, tmp_path):
    d = _dlg(qtbot)
    saved = {}
    d._save_runner = lambda img, path: saved.update(w=img.width(), path=path)
    d._do_export(str(tmp_path / "out.jpg"))          # bypass the file dialog
    assert saved["w"] > 0 and saved["path"].endswith("out.jpg")

def test_copy_uses_injected_clipboard(qtbot):
    d = _dlg(qtbot)
    grabbed = {}
    d._clipboard_runner = lambda img: grabbed.update(w=img.width())
    d._do_copy()
    assert grabbed["w"] > 0
