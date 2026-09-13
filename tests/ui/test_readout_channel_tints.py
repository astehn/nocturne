"""R, G and B are shown in their own colours in the hover readout.

Andreas, 2026-09-13: "these numbers mostly read as numbers that the user might
not pay attention to, but they are kind of important". He chose letter AND
number tinted, which is the most scannable of the options — the complaint is
about the segment being skipped over, not about the letter being ambiguous.

TINTS rather than pure hues: #f00/#0f0/#00f on this dark pill are hard to read
at 13px and blue is the worst of the three.
"""
from __future__ import annotations

import re

import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.main_window import _CHANNEL_TINT, _tinted
from tests.ui.test_main_window import _window, _make_fits


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def test_each_channel_carries_its_own_colour(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    data = np.zeros((8, 8, 3), np.float32)
    data[..., 0] = 0.80; data[..., 1] = 0.60; data[..., 2] = 0.40
    text = win._readout_text(AstroImage(data, is_linear=False), 2, 2)

    for label, colour in _CHANNEL_TINT.items():
        assert f'<span style="color:{colour}">' in text, f"{label} is not tinted"
    assert _CHANNEL_TINT["R"] != _CHANNEL_TINT["G"] != _CHANNEL_TINT["B"]


def test_the_number_is_inside_the_tint_not_just_the_letter(qtbot, tmp_path):
    """His choice, and the reason for it: tinting only the letter leaves the
    part he says gets skipped looking exactly as it did."""
    win = _window(qtbot, tmp_path)
    data = np.zeros((4, 4, 3), np.float32)
    data[..., 0] = 0.80; data[..., 1] = 0.60; data[..., 2] = 0.40
    text = win._readout_text(AstroImage(data, is_linear=False), 1, 1)
    assert f'<span style="color:{_CHANNEL_TINT["R"]}">R 0.80</span>' in text


def test_luminance_and_the_linear_flag_are_not_tinted(qtbot, tmp_path):
    """They are not channels. Colouring them would say something untrue about
    what they measure."""
    win = _window(qtbot, tmp_path)
    data = np.zeros((4, 4, 3), np.float32)
    data[..., 0] = 0.80; data[..., 1] = 0.60; data[..., 2] = 0.40
    text = win._readout_text(AstroImage(data, is_linear=True), 1, 1)
    tail = text.split("</span>")[-1]
    assert "L " in tail and "linear" in tail
    assert "<span" not in tail


def test_a_mono_image_is_not_tinted_at_all(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    img = AstroImage(np.full((8, 8), 0.42, np.float32), is_linear=False)
    text = win._readout_text(img, 2, 2)
    assert "V 0.42" in text
    assert "<span" not in text, "V is not a colour channel"


def test_the_plain_reading_is_unchanged(qtbot, tmp_path):
    """Markup is presentation. Strip it and the line must read exactly as it
    did before — same order, same separators, same precision."""
    win = _window(qtbot, tmp_path)
    data = np.zeros((4, 4, 3), np.float32)
    data[..., 0] = 0.80; data[..., 1] = 0.60; data[..., 2] = 0.40
    text = win._readout_text(AstroImage(data, is_linear=False), 1, 1)
    assert _plain(text) == "1, 1  ·  R 0.80  G 0.60  B 0.40  ·  L 0.60"


def test_tinted_leaves_an_unknown_label_alone():
    assert _tinted("L", "L 0.65") == "L 0.65"
    assert _tinted("V", "V 0.42") == "V 0.42"


def test_the_pill_renders_markup_rather_than_printing_it(qtbot):
    """The pill sets RichText once, in its constructor. A caller that had to
    remember would eventually forget and show the user raw <span> tags."""
    from PySide6.QtCore import Qt
    from nocturne.ui.readout_pill import ReadoutPill
    pill = ReadoutPill()
    qtbot.addWidget(pill)
    assert pill.textFormat() == Qt.TextFormat.RichText
