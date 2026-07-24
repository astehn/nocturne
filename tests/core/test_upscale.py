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
