import numpy as np
import pytest
from nocturne.core.image import AstroImage
from nocturne.core.upscale import LanczosEngine


def _img(h=32, w=48):
    d = np.zeros((h, w, 3), np.float32)
    d[..., 0] = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    return AstroImage(d, is_linear=False, metadata={"target": "NGC 7000"})


def test_lanczos_doubles_dimensions():
    out = LanczosEngine().upscale(_img(32, 48), 2)
    assert out.data.shape == (64, 96, 3)


def test_lanczos_preserves_float_range_and_metadata():
    out = LanczosEngine().upscale(_img(), 2)
    assert out.data.dtype == np.float32
    assert 0.0 <= out.data.min() and out.data.max() <= 1.0
    assert out.metadata.get("target") == "NGC 7000"
    assert out.is_linear is False


def test_lanczos_available_and_provenance():
    e = LanczosEngine()
    assert e.available() is True
    p = e.provenance()
    assert p["engine"] == "Lanczos"


def test_lanczos_preserves_gradient_direction():
    out = LanczosEngine().upscale(_img(16, 16), 2)
    row = out.data[8, :, 0]
    assert row[0] < row[-1]          # left→right ramp survives upscale


from nocturne.core.upscale import upscale_crop, LanczosEngine


def _starry(h=40, w=40):
    d = np.full((h, w, 3), 0.1, np.float32)   # dim background
    d[min(20, h - 1), min(20, w - 1)] = 1.0    # one bright star (clamped in-bounds for small h/w)
    return AstroImage(d, is_linear=False, metadata={"target": "M42", "source_label": "m42.fits"})


def test_upscale_crop_doubles_selected_crop():
    img = _starry(40, 40)
    out = upscale_crop(img, (10, 30, 10, 30), LanczosEngine(), scale=2)  # 20x20 crop → 40x40
    assert out.data.shape == (40, 40, 3)


def test_upscale_crop_full_frame_when_crop_none():
    img = _starry(20, 20)
    out = upscale_crop(img, None, LanczosEngine(), scale=2)
    assert out.data.shape == (40, 40, 3)


def test_upscale_crop_is_nondestructive():
    img = _starry(20, 20)
    before = img.data.copy()
    _ = upscale_crop(img, None, LanczosEngine(), scale=2)
    assert np.array_equal(img.data, before)   # input untouched


def test_upscale_crop_records_provenance():
    out = upscale_crop(_starry(), None, LanczosEngine(), scale=2)
    prov = out.metadata.get("upscale")
    assert prov and prov["engine"] == "Lanczos" and prov["scale"] == 2


from nocturne.core.upscale import upscale_provenance_text, upscale_filename


def test_provenance_text_mentions_engine_scale_and_honesty():
    out = upscale_crop(_starry(), None, LanczosEngine(), scale=2)
    out.metadata["source_label"] = "m42.fits"
    txt = upscale_provenance_text(out.metadata)
    assert "Lanczos" in txt and "2×" in txt
    assert "no synthesized detail" in txt.lower()


def test_upscale_filename():
    assert upscale_filename("NGC7000_182x20s_61min.fits", 2) == "NGC7000_182x20s_61min_2x.jpg"
    assert upscale_filename(None, 2) == "upscale_2x.jpg"


def test_an_upscaled_copy_halves_its_pixel_size():
    """A 2x pixel covers half the sky. Copied unchanged, the copy's solve
    hint and any FITS export said the field was twice as wide (review
    2026-09-29), as a drizzled master once did."""
    img = _starry(20, 20)
    img.metadata.update({"pixel_size": 2.9, "focal_length": 260.0,
                         "solve_cards": {"XPIXSZ": 2.9, "FOCALLEN": 260.0, "CD1_1": 0.0006}})
    out = upscale_crop(img, None, LanczosEngine(), scale=2)
    assert out.metadata["pixel_size"] == 1.45
    assert out.metadata["focal_length"] == 260.0
    assert out.metadata["solve_cards"] == {"XPIXSZ": 1.45, "FOCALLEN": 260.0, "CD1_1": 0.0003}
    assert img.metadata["pixel_size"] == 2.9, "the source image's metadata is untouched"


def test_prepare_then_finish_equals_upscale_crop():
    from nocturne.core.upscale import prepare_upscale, finish_upscale
    img = _starry(40, 40)
    layers = prepare_upscale(img, (10, 30, 10, 30), LanczosEngine(), scale=2)
    a = finish_upscale(layers, 0.35).data
    b = upscale_crop(img, (10, 30, 10, 30), LanczosEngine(), scale=2, tighten=0.35).data
    assert np.array_equal(a, b)


def test_finish_does_not_split_again(monkeypatch):
    """The slider re-runs only the fast part: the star split happens once."""
    import nocturne.steps.star_split as ss
    from nocturne.core.upscale import prepare_upscale, finish_upscale
    calls = []
    real = ss.resolve_star_split
    monkeypatch.setattr(ss, "resolve_star_split", lambda *a, **k: calls.append(1) or real(*a, **k))
    layers = prepare_upscale(_starry(20, 20), None, LanczosEngine(), scale=2)
    for t in (0.0, 0.5, 1.0):
        finish_upscale(layers, t)
    assert calls == [1]


def test_the_plain_resize_is_a_plain_lanczos_of_the_crop():
    from nocturne.core.upscale import prepare_upscale
    img = _starry(40, 40)
    layers = prepare_upscale(img, (10, 30, 10, 30), LanczosEngine(), scale=2)
    crop = AstroImage(img.data[10:30, 10:30].copy(), is_linear=False)
    assert layers.plain_up.dtype == np.uint8
    from nocturne.core.upscale import to_uint8
    assert np.array_equal(layers.plain_up, to_uint8(LanczosEngine().upscale(crop, 2).data))


def test_tighten_changes_only_the_stars():
    from nocturne.core.upscale import prepare_upscale, finish_upscale
    layers = prepare_upscale(_starry(40, 40), None, LanczosEngine(), scale=2)
    loose, tight = finish_upscale(layers, 0.0), finish_upscale(layers, 1.0)
    assert not np.array_equal(loose.data, tight.data)
    assert loose.metadata["upscale"]["tighten"] == 0.0
    assert tight.metadata["upscale"]["tighten"] == 1.0


def test_output_size_and_megapixels():
    from nocturne.core.upscale import megapixels, output_size
    assert output_size(1750, 1167) == (3500, 2334)
    assert output_size(1, 3) == (2, 6)                       # [RF 5] tiny crops are fine
    assert megapixels(3840, 2160) == pytest.approx(8.2944)


def test_finish_is_float32_and_matches_a_full_float32_computation():
    from nocturne.core.star_reduction import reduce_stars
    from nocturne.core.upscale import prepare_upscale, finish_upscale
    from nocturne.steps.star_split import resolve_star_split
    img = _starry(40, 40)
    layers = prepare_upscale(img, None, LanczosEngine(), scale=2)
    assert layers.starless_up.dtype == np.float16 and layers.stars_up.dtype == np.float16
    out = finish_upscale(layers, 0.35)
    assert out.data.dtype == np.float32
    starless, stars = resolve_star_split(img, None)
    ref = reduce_stars(LanczosEngine().upscale(starless, 2),
                       LanczosEngine().upscale(stars, 2), 0.35)
    assert np.abs(out.data - ref.data).max() < 1e-3
