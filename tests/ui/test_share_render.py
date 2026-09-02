"""Qt-side Share rendering. These moved out of tests/core/test_share.py when
core/share.py was split: they exercise QImage compositing and file IO, which is
UI-layer work and was the reason core/ was importing PySide6 at all."""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.share import centered_crop  # noqa: E402  (pure half)
from nocturne.ui.share_render import (  # noqa: E402
    compose_share, qimage_from_rgb8, save_share, save_share_jpeg, to_clipboard,
)


def _grad(h, w):
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    a[..., 1] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    return a


def test_compose_crop_and_downscale(qapp):
    img = _grad(500, 400)                       # tall 400x500
    crop = centered_crop(400, 500, 1.0)         # → 400x400
    out = compose_share(img, crop, "", longest_edge=200)
    assert out.width() == 200 and out.height() == 200   # square, downscaled


def test_compose_never_upscales(qapp):
    img = _grad(100, 100)
    out = compose_share(img, (0, 100, 0, 100), "", longest_edge=2048)
    assert out.width() == 100 and out.height() == 100


def test_compose_band_darkens_bottom_only_with_caption(qapp):
    img = _grad(300, 300); img[:] = 200          # uniform bright
    plain = compose_share(img, (0, 300, 0, 300), "", longest_edge=300)
    capped = compose_share(img, (0, 300, 0, 300), "NGC 7000 · @me", longest_edge=300)
    # bottom band row is darker with a caption; a top row is unchanged
    def lum(qi, y):
        c = qi.pixelColor(qi.width() // 2, y)
        return c.red() + c.green() + c.blue()
    assert lum(capped, 295) < lum(plain, 295)     # band burned at the bottom
    assert lum(capped, 5) == lum(plain, 5)        # top untouched


def test_compose_accepts_mono(qapp):
    mono = (np.ones((120, 120), np.uint8) * 128)
    out = compose_share(mono, (0, 120, 0, 120), "", longest_edge=120)
    assert out.width() == 120 and out.height() == 120


def test_save_share_jpeg(qapp, tmp_path):
    out = compose_share(_grad(64, 64), (0, 64, 0, 64), "", longest_edge=64)
    p = tmp_path / "s.jpg"
    save_share_jpeg(out, str(p))
    assert p.exists() and p.stat().st_size > 0


# --- caption styling: placement, size, colour --------------------------------

def _flat(h, w, v=120):
    a = np.zeros((h, w, 3), np.uint8); a[:] = v
    return a


def test_below_placement_extends_the_canvas_and_covers_no_pixels(qapp):
    """"On image" paints over the bottom of the picture. "Below" must not: the
    canvas grows and every original pixel survives."""
    img = _flat(300, 300)
    on = compose_share(img, (0, 300, 0, 300), "NGC 7000", longest_edge=300,
                       placement="on")
    below = compose_share(img, (0, 300, 0, 300), "NGC 7000", longest_edge=300,
                          placement="below")
    assert on.height() == 300, "on-image keeps the frame size"
    assert below.height() > 300, "below-image grows the canvas"
    assert below.width() == on.width() == 300

    # every row of the ORIGINAL picture is untouched in the 'below' variant
    assert below.pixelColor(150, 150).red() == 120
    assert below.pixelColor(150, 299).red() == 120, "the last image row is not painted over"
    # ...whereas on-image has darkened that same row
    assert on.pixelColor(150, 299).red() < 120


def test_caption_size_changes_the_rendered_text_height(qapp):
    from nocturne.core.share import CAPTION_SIZES
    img = _flat(400, 400)
    heights = []
    for _label, frac in CAPTION_SIZES:
        out = compose_share(img, (0, 400, 0, 400), "X", longest_edge=400,
                            placement="below", size_frac=frac)
        heights.append(out.height() - 400)      # the band grows with the font
    assert heights == sorted(heights) and heights[0] < heights[-1], heights


def test_caption_colour_is_applied(qapp):
    """Text is drawn in the requested colour, not always white."""
    img = _flat(300, 300, v=0)                  # black, so the text is what shows
    red = compose_share(img, (0, 300, 0, 300), "IIIIIIIIIIIIIIII", longest_edge=300,
                        placement="below", colour="#ff0000", size_frac=0.038,
                        band_opacity=1.0)          # black strip: the text is what shows
    reds = greens = 0
    for y in range(300, red.height()):
        for x in range(0, 200, 2):
            c = red.pixelColor(x, y)
            reds += c.red(); greens += c.green()
    assert reds > 0, "some text was drawn"
    assert reds > greens * 3, "and it is red, not white"


def test_the_band_never_clips_the_glyphs_at_the_largest_size(qapp):
    """The band used to be a fixed 7% of height while the font was a separate
    fraction — at Large the descenders were cut off."""
    from nocturne.core.share import CAPTION_SIZES
    frac = CAPTION_SIZES[-1][1]
    img = _flat(400, 400)
    out = compose_share(img, (0, 400, 0, 400), "gjpqy", longest_edge=400,
                        placement="below", size_frac=frac)
    band = out.height() - 400
    assert band >= round(400 * frac) * 2, f"band {band} too tight for a {round(400*frac)}px font"


def _text_centroid_x(img, y0):
    """Mean x of the lit pixels below y0 — where the caption actually sits."""
    xs, tot = 0.0, 0.0
    for y in range(y0, img.height()):
        for x in range(img.width()):
            v = img.pixelColor(x, y).red()
            if v > 60:
                xs += x * v; tot += v
    return xs / tot if tot else None


def test_alignment_moves_the_text_across_the_band(qapp):
    img = _flat(300, 300, v=0)                        # black, text is what shows
    cents = {}
    for align in ("left", "centre", "right"):
        out = compose_share(img, (0, 300, 0, 300), "NGC 7000", longest_edge=300,
                            placement="below", align=align, size_frac=0.038)
        cents[align] = _text_centroid_x(out, 300)
    assert None not in cents.values(), cents
    assert cents["left"] < cents["centre"] < cents["right"], cents


def test_band_opacity_controls_how_much_shows_through(qapp):
    """0% leaves the picture untouched; 100% is a solid bar."""
    img = _flat(300, 300, v=200)
    clear = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                          placement="on", band_opacity=0.0)
    solid = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                          placement="on", band_opacity=1.0)
    mid = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                        placement="on", band_opacity=0.5)
    # sample a band pixel well away from the text
    y, x = 295, 280
    assert clear.pixelColor(x, y).red() == 200, "0% must not darken the picture at all"
    assert solid.pixelColor(x, y).red() == 0, "100% is opaque"
    assert 0 < mid.pixelColor(x, y).red() < 200


def test_the_band_slider_darkens_the_strip_below_the_image_too(qapp):
    """It used to be inert here, so it was disabled — and a slider that cannot be
    moved reads as broken rather than as unavailable. It now means "how dark the
    band is" in both modes. 1.0 black, 0.0 white."""
    img = _flat(300, 300, v=200)
    # a caption is required for a band to exist at all; keep it short and
    # left-aligned so x=280 samples the strip rather than the text
    dark = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                         placement="below", band_opacity=1.0)
    light = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                          placement="below", band_opacity=0.0)
    mid = compose_share(img, (0, 300, 0, 300), "x", longest_edge=300,
                        placement="below", band_opacity=0.5)
    y = dark.height() - 5
    assert dark.pixelColor(280, y).red() == 0
    assert light.pixelColor(280, y).red() == 255
    assert 100 < mid.pixelColor(280, y).red() < 155
    # and the picture above is untouched at every setting
    for img_ in (dark, light, mid):
        assert img_.pixelColor(150, 299).red() == 200


# --- the title plate ---------------------------------------------------------

def _plate_rgb(w=400, h=500):
    return (np.random.default_rng(7).random((h, w, 3)) * 255).astype(np.uint8)


def _pixels(img):
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    return np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].copy()


def test_a_plain_string_caption_still_works(qapp):
    """Backwards compatibility: every existing caller and test passes a str."""
    arr = _plate_rgb()
    out = compose_share(arr, (0, 500, 0, 400), "NGC 7000 · 5 h", longest_edge=None)
    assert out.width() == 400


def test_data_reproduces_the_old_renderers_LAYOUT(qapp):
    """What the Data preset actually promises — and what it deliberately does not.

    NOT pixel-identity. Measured 2026-09-02: the old `_burn_caption` draws with a
    bare `QFont()`, which resolves to the system UI face here and to something
    else entirely on Windows — so the old output was never reproducible across
    machines in the first place. Data draws in bundled Manrope, and the same
    string measures 200.5 px against the system font's 216.1 px at 14 px. The
    glyphs differ BY DESIGN; that is the feature.

    What must not change is the geometry: same canvas, same band in the same
    place at the same height. Someone who never opens the new controls gets the
    caption they had, in a face that now travels with the app.
    """
    from nocturne.core.plate import PlateText
    from nocturne.core.presets import preset_by_name
    from nocturne.ui.plate_render import last_layout
    arr = _plate_rgb()
    cap = "NGC 7000 · 5 h 39 m · @andreas"
    old_img = compose_share(arr, (0, 500, 0, 400), cap, longest_edge=None)
    new_img = compose_share(arr, (0, 500, 0, 400), PlateText("", "", cap),
                            longest_edge=None, style=preset_by_name("Data"))
    assert (new_img.width(), new_img.height()) == (old_img.width(), old_img.height())

    # The band: same top edge and same height as the old renderer computes them.
    # px = max(8, round(h * 0.028)); band = max(px * 2, round(h * BAND_FRAC))
    h = old_img.height()
    px = max(8, round(h * 0.028))
    expected_band = max(px * 2, round(h * 0.07))
    lay = last_layout()
    assert abs(lay["band_top"] - (h - expected_band)) <= 1, (
        f"band starts at {lay['band_top']}, old renderer put it at {h - expected_band}")

    # And the pixels ABOVE the band are untouched — the picture is not disturbed.
    top_old = _pixels(old_img)[: int(lay["band_top"]) - 2]
    top_new = _pixels(new_img)[: int(lay["band_top"]) - 2]
    assert np.array_equal(top_old, top_new), "Data altered the picture above the band"


def test_the_plate_is_applied_after_the_downscale(qapp):
    """Styling before the resize would shrink the plate with the image and land
    it at the wrong size. Already true of the caption; must stay true.

    Same source, two output sizes: the plate must occupy the same FRACTION of
    each, not the same pixel count."""
    from nocturne.core.plate import PlateText
    from nocturne.core.presets import preset_by_name
    from nocturne.ui.plate_render import last_layout
    arr = _plate_rgb(1600, 2000)
    style = preset_by_name("Scrim")
    text = PlateText("IC 1396A", "Elephant's Trunk Nebula", "")
    compose_share(arr, (0, 2000, 0, 1600), text, longest_edge=1000, style=style)
    small = last_layout()["block_height"] / 1000
    compose_share(arr, (0, 2000, 0, 1600), text, longest_edge=2000, style=style)
    big = last_layout()["block_height"] / 2000
    assert abs(small - big) < 0.01, "the plate does not scale with the output"


def test_a_plate_never_upscales_either(qapp):
    """A share is never enlarged — that adds pixels without adding detail."""
    from nocturne.core.plate import PlateText
    out = compose_share(_plate_rgb(200, 250), (0, 250, 0, 200),
                        PlateText("M 31", "", ""), longest_edge=4096)
    assert (out.width(), out.height()) == (200, 250)


def test_an_entirely_empty_plate_leaves_the_picture_alone(qapp):
    """Three blank slots must not paint a scrim over nothing — the old str path
    had the same rule, and a bar with no text in it reads as a rendering bug."""
    from nocturne.core.plate import PlateText
    arr = _plate_rgb(120, 150)
    out = compose_share(arr, (0, 150, 0, 120), PlateText("", "", ""), longest_edge=None)
    assert np.array_equal(_pixels(out), _pixels(qimage_from_rgb8(arr)))
