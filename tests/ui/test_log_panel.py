import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.log_panel import format_log_entry, LogPanel  # noqa: E402


def test_format_with_delta():
    assert format_log_entry("Noise & Sharpen", "medium", 0.83) == \
        "Noise & Sharpen (medium)  —  Δ 0.8%"


def test_format_crop_dims():
    assert format_log_entry("Crop", "", None, dims=(1920, 1080)) == \
        "Crop  —  → 1920×1080"


def test_format_no_option_no_delta():
    assert format_log_entry("Stretch", "", None) == "Stretch"


def test_format_zero_delta():
    assert format_log_entry("Color", None, 0.0) == "Color  —  Δ 0.0%"


def test_log_panel_append_and_clear(qtbot):
    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.append_entry("Hello")
    assert "Hello" in panel.text()
    panel.clear_log()
    assert panel.text().strip() == ""
