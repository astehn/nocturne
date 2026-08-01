import pytest
from nocturne.core.share import caption_line, centered_crop, share_filename, ASPECTS

def test_caption_all_fields():
    meta = {"target": "NGC 7000", "livetime": 3600.0, "exposure": 20.0, "frames": 180,
            "date": "2026-07-16T01:31:01"}
    line = caption_line(meta, "andreas")
    assert line == "NGC 7000 · 1h 00m · 180 × 20s · 2026-07-16 · @andreas"

def test_caption_omits_missing_and_blank_handle():
    assert caption_line({"target": "M31"}, "") == "M31"
    assert "@" not in caption_line({"target": "M31"}, "")

def test_caption_handle_at_optional():
    assert caption_line({"target": "M31"}, "@astro").endswith("@astro")  # not @@astro

def test_caption_empty_when_no_data():
    assert caption_line({}, "") == ""

def test_centered_crop_full_when_none():
    assert centered_crop(100, 200, None) == (0, 200, 0, 100)

def test_centered_crop_square_on_tall():
    # 100x200 tall frame, 1:1 → 100x100 centered vertically
    assert centered_crop(100, 200, 1.0) == (50, 150, 0, 100)

def test_centered_crop_landscape_on_square():
    # 200x200, 16:9 → limited by width → 200x112 (round(200/1.777)=113) centered
    top, bottom, left, right = centered_crop(200, 200, 16/9)
    assert (left, right) == (0, 200)
    assert bottom - top == round(200 / (16/9))

def test_share_filename():
    assert share_filename("NGC7000_182x20s_61min.fits", "4:5") == "NGC7000_182x20s_61min_4x5.jpg"
    assert share_filename(None, "1:1") == "share_1x1.jpg"

def test_aspects_are_width_over_height():
    d = dict(ASPECTS)
    assert d["Original"] is None and d["1:1"] == 1.0
    assert abs(d["9:16"] - 9/16) < 1e-9


import numpy as np

@pytest.fixture(scope="module")
def _qapp():
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])

def _grad(h, w):
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    return a

def test_caption_uses_the_plate_solved_target_when_the_header_has_none():
    """Share was the ONLY surface that read `target` alone. A stacked master with
    no OBJECT header, plate-solved to NGC 7000, showed "NGC 7000" in the info
    strip and the provenance report and published with no target at all."""
    assert caption_line({"target_solved": "NGC 7000"}, "") == "NGC 7000"


def test_a_header_target_still_wins_over_the_solved_one():
    """Same precedence as main_window and provenance: `target or target_solved`.
    The header is what the user actually pointed at and named."""
    assert caption_line({"target": "My Pacman", "target_solved": "NGC 281"}, "") == "My Pacman"


def test_share_and_provenance_name_the_same_target():
    """They drifted once: provenance read `target or target_solved` while Share
    read `target` alone, so the same image was NGC 7000 in the report and
    anonymous in the shared JPEG. Compare them on the same metadata."""
    import datetime
    from nocturne.core.provenance import build_report
    meta = {"target_solved": "NGC 7000"}
    assert "NGC 7000" in caption_line(meta, "")
    report = build_report([], meta, app_version="0.7.1", date=datetime.date(2026, 8, 1))
    assert "NGC 7000" in report
