import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.upscale_dialog import UpscaleDialog
from nocturne.settings import Settings


def _img(h=60, w=60):
    d = np.full((h, w, 3), 0.1, np.float32); d[30, 30] = 1.0
    from nocturne.core.image import AstroImage
    return AstroImage(d, is_linear=False, metadata={"target": "M42", "source_label": "m42.fits"})


def _dlg(qtbot, **kw):
    d = UpscaleDialog(_img(), {"target": "M42", "source_label": "m42.fits"}, Settings(), **kw)
    qtbot.addWidget(d)
    return d


def test_dialog_builds(qtbot):
    d = _dlg(qtbot)
    assert d._engine.name == "Lanczos"


def test_run_upscale_produces_2x_result(qtbot):
    d = _dlg(qtbot)
    d._run_upscale()                       # full-frame (no crop box shown)
    assert d._result is not None
    assert d._result.data.shape == (120, 120, 3)


def test_export_uses_injected_saver_and_writes_report(qtbot, tmp_path):
    d = _dlg(qtbot)
    d._run_upscale()
    saved = {}
    d._save_runner = lambda img, path: saved.update(path=path, shape=img.data.shape)
    d._do_export(str(tmp_path / "out.jpg"))
    assert saved["shape"] == (120, 120, 3)
    assert (tmp_path / "out.txt").exists()          # provenance report written
    assert "Lanczos" in (tmp_path / "out.txt").read_text()


def test_open_as_copy_calls_callback(qtbot):
    got = {}
    d = _dlg(qtbot, on_open_copy=lambda img: got.update(shape=img.data.shape))
    d._run_upscale()
    d._do_open_copy()
    assert got["shape"] == (120, 120, 3)


def test_open_as_copy_closes_the_dialog(qtbot):
    from PySide6.QtWidgets import QDialog
    opened = {}
    d = _dlg(qtbot, on_open_copy=lambda img: opened.update(ok=True))
    d._run_upscale()
    d._do_open_copy()
    assert opened.get("ok") is True
    assert d.result() == QDialog.DialogCode.Accepted   # dialog closed -> main window (with the copy) is revealed
