"""RC Astro is the suite; what runs is one of its products (Andreas, 2026-10-05:
Noise Reduction said "RC-Astro" for NoiseXTerminator)."""
from tests.ui.test_main_window import _make_fits, _window


def test_the_log_names_the_product():
    from nocturne.ui.main_window import render_engine
    assert render_engine("NoiseX") == "NoiseXTerminator"
    assert render_engine("BlurX") == "BlurXTerminator"
    assert render_engine("StarX") == "StarXTerminator"
    assert render_engine("free") == "built-in"
    assert render_engine("GraXpert") == "GraXpert", "other engines unchanged"


def test_noise_reduction_offers_noisexterminator(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    monkeypatch.setattr(mw, "rcastro_valid", lambda s: True)
    monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("noise_sharpen")
    box = win._panel.engine_box
    items = [box.itemText(i) for i in range(box.count())]
    assert items == ["Default", "NoiseXTerminator", "GraXpert"]
    box.setCurrentText("NoiseXTerminator")
    assert win._panel.commit_option()["engine"] == "rcastro", "the stored id is unchanged"


def test_settings_offers_noisexterminator(qtbot, tmp_path):
    from nocturne.settings import Settings
    from nocturne.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(Settings())
    qtbot.addWidget(d)
    items = [d.denoise_box.itemText(i) for i in range(d.denoise_box.count())]
    assert items == ["NoiseXTerminator", "GraXpert"]
