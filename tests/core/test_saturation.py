import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.core.saturation import saturate


def test_saturation_increases_chroma():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 1.0)
    assert (out.data[0, 0].max() - out.data[0, 0].min()) > (0.6 - 0.2)


def test_half_amount_is_noop():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = saturate(AstroImage(data), 0.5)
    assert np.allclose(out.data, data, atol=1e-6)


def test_zero_amount_is_greyscale():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = saturate(AstroImage(data), 0.0).data[0, 0]
    assert out.max() - out.min() < 1e-6           # R=G=B -> grey


def test_partial_desaturation():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    native = 0.6 - 0.2
    out = saturate(AstroImage(data), 0.25).data[0, 0]
    chroma = out.max() - out.min()
    assert 0.0 < chroma < native                  # muted but not grey


def test_monotonic_chroma_across_slider():
    data = np.tile(np.array([0.5, 0.35, 0.2], np.float32), (4, 4, 1))  # dark coloured pixel
    def chroma(a):
        px = saturate(AstroImage(data), a).data[0, 0]
        return float(px.max() - px.min())
    vals = [chroma(a) for a in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert vals == sorted(vals) and vals[0] < vals[-1]


def test_mono_noop():
    img = AstroImage(np.full((8, 8), 0.5, np.float32))
    assert np.allclose(saturate(img, 1.0).data, img.data)


def test_preserves_is_linear_and_range():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    out = saturate(img, 0.5)
    assert out.is_linear is False
    assert out.data.dtype == np.float32
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0


def test_highlights_protected_vs_midtones():
    bright = np.tile(np.array([0.95, 0.85, 0.75], np.float32), (4, 4, 1))
    mid = np.tile(np.array([0.45, 0.35, 0.25], np.float32), (4, 4, 1))
    sb = saturate(AstroImage(bright), 1.0).data[0, 0]
    sm = saturate(AstroImage(mid), 1.0).data[0, 0]
    gain_b = (sb.max() - sb.min()) - (0.95 - 0.75)
    gain_m = (sm.max() - sm.min()) - (0.45 - 0.25)
    assert gain_b < gain_m  # bright pixels gain less chroma
