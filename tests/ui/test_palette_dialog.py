import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.settings import Settings  # noqa: E402
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.palette_dialog import PaletteDialog  # noqa: E402


def test_palette_dialog_applies_writes_and_hands_off(qtbot, tmp_path):
    (tmp_path / "in.fits").write_text("placeholder")  # loader is faked below
    handed, captured = {}, {}
    dlg = PaletteDialog(Settings(), on_master=lambda img: handed.setdefault("img", img))
    qtbot.addWidget(dlg)
    dlg._loader = lambda path: AstroImage(
        np.random.rand(4, 5, 3).astype(np.float32), is_linear=False)

    def fake_runner(img, name):
        captured["name"] = name
        return img

    dlg._palette_runner = fake_runner
    dlg.input_edit.setText(str(tmp_path / "in.fits"))
    out = tmp_path / "out.tiff"
    dlg.output_edit.setText(str(out))
    dlg.hoo_radio.setChecked(True)
    dlg.open_check.setChecked(True)
    dlg.run()
    assert captured["name"] == "HOO"
    assert out.exists()                 # file written via save_tiff
    assert "img" in handed              # editor handoff called


def test_pseudo_sho_selected_passes_pseudo_name(qtbot, tmp_path):
    (tmp_path / "in.fits").write_text("x")
    captured = {}
    dlg = PaletteDialog(Settings())
    qtbot.addWidget(dlg)
    dlg._loader = lambda path: AstroImage(np.zeros((4, 5, 3), np.float32))
    dlg._palette_runner = lambda img, name: captured.setdefault("name", name) or img
    dlg.input_edit.setText(str(tmp_path / "in.fits"))
    dlg.output_edit.setText(str(tmp_path / "out.tiff"))
    dlg.sho_radio.setChecked(True)
    dlg.run()
    assert captured["name"] == "pseudo_SHO"


def test_background_checkbox_subtracts_pedestal_before_palette(qtbot, tmp_path):
    (tmp_path / "in.fits").write_text("x")
    seen = {}
    bg_master = AstroImage(np.full((6, 6, 3), 0.3, np.float32), is_linear=True)

    def _dialog(out_name):
        dlg = PaletteDialog(Settings())
        qtbot.addWidget(dlg)
        dlg._loader = lambda path: bg_master
        dlg._palette_runner = lambda img, name: (
            seen.__setitem__("med", float(np.median(img.data))) or img)
        dlg.input_edit.setText(str(tmp_path / "in.fits"))
        dlg.output_edit.setText(str(tmp_path / out_name))
        return dlg

    on = _dialog("out_on.tiff")
    on.bg_check.setChecked(True)
    on.run()
    assert seen["med"] < 1e-6              # pedestal removed before the palette ran

    seen.clear()
    off = _dialog("out_off.tiff")
    off.bg_check.setChecked(False)
    off.run()
    assert np.isclose(seen["med"], 0.3, atol=1e-6)   # unchanged when off


def test_palette_dialog_requires_paths(qtbot):
    dlg = PaletteDialog(Settings())
    qtbot.addWidget(dlg)
    dlg.run()
    assert "pick" in dlg.status.text().lower()
