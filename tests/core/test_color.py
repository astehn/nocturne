import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.color import ColorSettings, apply_color


def test_neutralize_background_equalizes_channel_medians():
    # green background raised -> a color cast
    data = np.full((32, 32, 3), 0.1, dtype=np.float32)
    data[..., 1] = 0.2  # green higher
    img = AstroImage(data)
    out = apply_color(img, ColorSettings(neutralize_background=True))
    meds = [float(np.median(out.data[..., c])) for c in range(3)]
    assert max(meds) - min(meds) < 1e-3


def test_neutralize_keeps_bg_neutral_and_preserves_nebula():
    # Red-dominant emission frame with a slightly-blue background (residual LP).
    # The fix must neutralize the sky WITHOUT desaturating the nebula or casting
    # the sky the complementary colour (the grey-world failure mode).
    rng = np.random.default_rng(0)
    H, W = 120, 120
    d = np.full((H, W, 3), 0.02, dtype=np.float32)
    d[..., 2] = 0.028                      # background slightly blue (LP residue)
    neb = np.zeros((H, W), dtype=bool)
    neb[:48, :] = True                     # ~40% of frame is red (Ha) nebula
    d[neb, 0] = 0.16; d[neb, 1] = 0.05; d[neb, 2] = 0.045
    d = np.clip(d + rng.normal(0, 0.002, d.shape).astype(np.float32), 0, 1)

    out = apply_color(AstroImage(d), ColorSettings(neutralize_background=True)).data
    bg = ~neb
    bgmed = [float(np.median(out[..., c][bg])) for c in range(3)]
    assert max(bgmed) - min(bgmed) < 0.005            # sky neutralized
    assert bgmed[2] <= bgmed[0] + 0.003               # sky NOT cast blue
    nebmed = [float(np.median(out[..., c][neb])) for c in range(3)]
    assert nebmed[0] > nebmed[1] and nebmed[0] > nebmed[2]  # nebula stays red


def test_mono_is_noop():
    img = AstroImage(np.full((8, 8), 0.3, dtype=np.float32))
    out = apply_color(img, ColorSettings())
    assert out.data.ndim == 2
    assert np.allclose(out.data, img.data)


def test_preserves_is_linear_and_dtype():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    out = apply_color(img, ColorSettings())
    assert out.is_linear is True
    assert out.data.dtype == np.float32
    assert out.data.max() <= 1.0 and out.data.min() >= 0.0


def test_remove_green_clamps_green_excess():
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = apply_color(AstroImage(data),
                      ColorSettings(neutralize_background=False, remove_green=True))
    assert out.data[..., 1].max() <= 0.3 + 1e-6  # clamped to (r+b)/2 = 0.3


def test_remove_green_function_clamps_green():
    from nocturne.core.color import remove_green
    data = np.full((8, 8, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.8  # green excess
    out = remove_green(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6           # clamped to (r+b)/2
    assert out.data[..., 0].max() <= 0.3 + 1e-6           # red untouched


def test_remove_green_leaves_non_green_pixel_untouched():
    from nocturne.core.color import remove_green
    data = np.zeros((2, 2, 3), dtype=np.float32)
    data[..., 0] = 0.5; data[..., 1] = 0.2; data[..., 2] = 0.5   # green already below avg
    out = remove_green(AstroImage(data))
    assert np.allclose(out.data[..., 1], 0.2)                     # unchanged


def test_remove_green_mono_is_noop():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4), 0.5, dtype=np.float32))
    out = remove_green(img)
    assert out.data.ndim == 2 and np.allclose(out.data, 0.5)


def test_remove_green_preserves_is_linear():
    from nocturne.core.color import remove_green
    img = AstroImage(np.full((4, 4, 3), 0.4, dtype=np.float32), is_linear=False)
    assert remove_green(img).is_linear is False
