import numpy as np
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
