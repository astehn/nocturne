"""Colour Tint, Curves, Colour Balance and Narrowband in the words of the panel
or dialog that set them (2026-10-17): no point tuples, no slot keys, no axis
ids, and only the Narrowband controls the chosen palette actually uses."""
import datetime
import re

import numpy as np
import pytest

from nocturne.core.curves import curve_key
from nocturne.core.image import AstroImage
from nocturne.core.narrowband import (
    DIALOG_CONTROLS, GOLD_BLUE, PALETTES, NarrowbandParams, palette_controls,
    palette_defaults, render)
from nocturne.core.provenance import build_report
from nocturne.recipe import serialize_option


def _report(name, option) -> str:
    return build_report([(name, option)], {}, app_version="x",
                        date=datetime.date(2026, 10, 17))


def _params(r: str) -> list[str]:
    return r.split("## Parameters\n\n")[1].split("\n\n")[0].splitlines()[1:]


# ---- Colour Tint -----------------------------------------------------------
def test_tint_is_labelled_with_the_panels_words_and_direction():
    r = _report("Colour Tint", (0.25, -0.1))
    assert "1. Colour Tint — tint +0.25, temperature −0.10" in r
    assert _params(r) == ["- tint (Green ←→ Magenta): +0.25, towards magenta",
                          "- temperature (Cool ←→ Warm): −0.10, towards cool"]


def test_a_centred_tint_slider_says_so():
    r = _report("Colour Tint", [0.0, 0.3])
    assert _params(r) == ["- tint (Green ←→ Magenta): 0.00, centred",
                          "- temperature (Cool ←→ Warm): +0.30, towards warm"]


# ---- Curves ----------------------------------------------------------------
def test_a_curve_is_described_not_dumped():
    r = _report("Curves", {curve_key("rgb", "all"): [(0, 0), (0.25, 0.3), (1, 1)]})
    (line,) = _params(r)
    # One point at 0.25 lifts the whole curve: most in the midtones, but the
    # highlights too (by 0.016 on average) — said, as it is true.
    assert line == ("- RGB curve: 3 points — brightens the shadows, midtones and highlights "
                    "(in 0.25 → out 0.30)")


def test_an_s_curve_reads_as_one():
    pts = [(0, 0), (0.25, 0.18), (0.75, 0.84), (1, 1)]
    (line,) = _params(_report("Curves", {curve_key("rgb", "all"): pts}))
    assert line.startswith("- RGB curve: 4 points — darkens the shadows, brightens the highlights")


def test_black_and_white_points_are_named():
    pts = [(0.1, 0), (0.9, 1)]
    (line,) = _params(_report("Curves", {curve_key("rgb", "all"): pts}))
    assert "black point at 0.10" in line and "white point at 0.90" in line


def test_colour_and_saturation_curves_use_their_own_verbs():
    r = _report("Curves", {curve_key("r", "all"): [(0, 0), (0.5, 0.55), (1, 1)],
                           curve_key("s", "reds"): [(0, 0), (0.5, 0.4), (1, 1)]})
    lines = _params(r)
    assert lines[0].startswith("- Red curve: 3 points — adds red to the shadows, midtones "
                               "and highlights")
    assert lines[1].startswith("- Saturation curve, Reds only: 3 points — lowers saturation")


def test_a_legacy_bare_list_is_the_rgb_curve():
    (line,) = _params(_report("Curves", [[0.0, 0.0], [0.3, 0.4], [1.0, 1.0]]))
    assert line.startswith("- RGB curve: 3 points — brightens")


# ---- Colour Balance --------------------------------------------------------
_CB = {"shadows": [0, 0, 0], "midtones": [0.02, 0, -0.01], "highlights": [-0.05, 0.03, 0],
       "preserve_lum": True, "strength": 0.8, "lo": 0.1, "hi": 0.6, "feather": 0.08,
       "invert": True}


def test_colour_balance_in_the_dialogs_words():
    r = _report("Colour Balance", _CB)
    assert "1. Colour Balance — midtones, highlights (inverted)" in r
    assert _params(r) == [
        "- Midtones: Cyan — Red +2, Yellow — Blue −1",
        "- Highlights: Cyan — Red −5, Magenta — Green +3",
        "- Preserve luminosity: on",
        "- Strength: 80%",
        "- Range: brightness 0.10 to 0.60, Feather 0.08",
        "- Invert the range: on",
    ]


def test_an_unlimited_colour_balance_has_no_range_line():
    cb = dict(_CB, lo=0.0, hi=1.0, invert=False, preserve_lum=False)
    lines = _params(_report("Colour Balance", cb))
    assert "- Preserve luminosity: off" in lines
    assert not any(ln.startswith(("- Range", "- Invert")) for ln in lines)


# ---- Narrowband ------------------------------------------------------------
_LABELS = {"oxygen_strength": "oxygen strength", "blend_amount": "green blend",
           "protect_background": "protect background", "saturation": "saturation",
           "gold_strength": "gold", "blue_strength": "blue",
           "highlight_reduction": "tame core", "brightness": "brightness",
           "lightness_preserve": "preserve lightness"}


@pytest.mark.parametrize("palette", PALETTES)
def test_narrowband_lists_exactly_the_controls_its_palette_uses(palette):
    lines = _params(_report("Narrowband", NarrowbandParams(palette=palette)))
    assert lines[0] == f"- palette: {palette}"
    shown = [ln[2:].split(":")[0] for ln in lines[1:]]
    assert shown == [_LABELS[c] for c in palette_controls(palette)]


def test_the_gold_and_blue_numbers_are_the_dialogs():
    lines = _params(_report("Narrowband", NarrowbandParams(
        palette=GOLD_BLUE, oxygen_strength=0.6, protect_background=0.2,
        gold_strength=1.2, blue_strength=0.8, highlight_reduction=2.0)))
    assert lines == ["- palette: SHO-style (gold and blue)", "- oxygen strength: 60%",
                     "- protect background: 20%", "- gold: 120%", "- blue: 80%",
                     "- tame core: 25%", "- brightness: ×1.00"]


def test_hoo_shows_its_blend_and_lightness():
    lines = _params(_report("Narrowband", NarrowbandParams(palette="HOO",
                                                           lightness_preserve=True)))
    assert "- green blend: 0.60" in lines and "- preserve lightness: on" in lines
    assert "- oxygen strength: ×0.85" in lines and "- saturation: 0.85" in lines


def test_a_pre_2026_09_09_oiii_boost_still_reads():
    old = {"palette": "HOO", "blackpoint": 1.0, "oiii_boost": 1.3, "blend_amount": 0.6,
           "highlight_reduction": 1.0, "brightness": 1.0, "highlight_recover": 1.0,
           "saturation": 0.85, "lightness_preserve": False, "protect_background": 0.4,
           "scnr": True}
    assert "- OIII boost (an earlier control): ×1.30" in _params(_report("Narrowband", old))


def _nb_image():
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:64, 0:64]
    neb = np.exp(-((yy - 32) ** 2 + (xx - 30) ** 2) / 300.0)
    data = np.stack([0.15 + 0.6 * neb, 0.12 + 0.3 * neb * (xx / 64), 0.1 + 0.4 * neb * (yy / 64)],
                    axis=2) + rng.normal(0, 0.01, (64, 64, 3))
    return AstroImage(np.clip(data, 0, 1).astype(np.float32), is_linear=False)


_MOVED = {"oxygen_strength": 1.4, "blend_amount": 0.0, "protect_background": 0.0,
          "saturation": 1.4, "gold_strength": 1.8, "blue_strength": 0.3,
          "highlight_reduction": 4.0, "brightness": 1.6, "lightness_preserve": True}


@pytest.mark.parametrize("palette", PALETTES)
def test_which_controls_a_palette_uses_is_measured_not_asserted(palette):
    """palette_controls is what the dialog greys/hides by and what the report
    lists, so it must be what render() does. One exception, a dialog fact:
    gold and blue reads saturation, but its dialog REPLACES that control with
    Gold and Blue and holds it at the palette's default."""
    assert set(_MOVED) == set(DIALOG_CONTROLS)
    img = _nb_image()
    base = palette_defaults(palette)
    ref = render(img, base).data
    for field in DIALOG_CONTROLS:
        moved_p = NarrowbandParams(**{**base.__dict__, field: _MOVED[field]})
        moved = float(np.abs(render(img, moved_p).data - ref).max()) > 1e-5
        expected = field in palette_controls(palette)
        if palette == GOLD_BLUE and field == "saturation":
            assert moved and not expected
            continue
        assert moved == expected, f"{palette}: {field} {'moves' if moved else 'is inert'}"


def test_the_report_never_meets_internal_names():
    for name, opt in (("Colour Tint", (0.1, 0.2)), ("Colour Balance", _CB),
                      ("Narrowband", serialize_option("narrowband", NarrowbandParams())),
                      ("Curves", {curve_key("g", "blues"): [(0, 0), (0.4, 0.5), (1, 1)]})):
        r = _report(name, opt)
        assert not re.search(r"\(\s*-?\d+(\.\d+)?,\s*-?\d", r), r
        assert not re.search(r"\b(rgb|[rgbs])/\w+", r), r
