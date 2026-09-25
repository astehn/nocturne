import pytest

pytest.importorskip("PySide6")
from nocturne.ui.log_panel import format_log_entry  # noqa: E402


def test_format_with_delta():
    assert format_log_entry("Noise & Sharpen", "medium", 0.83) == "Noise & Sharpen (medium) · Δ0.8%"


def test_format_crop_dims():
    assert format_log_entry("Crop", "", None, dims=(1920, 1080)) == "Crop · 1920×1080"


def test_format_no_option_no_delta():
    assert format_log_entry("Stretch", "", None) == "Stretch"


def test_format_zero_delta():
    assert format_log_entry("Color", None, 0.0) == "Color · Δ0.0%"
