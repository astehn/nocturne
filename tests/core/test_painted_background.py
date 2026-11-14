"""Painted background fit: spike-style injection tests on synthetic sky.

Gradients are injected into a star field and scored like the October spike
(``docs/bge_spike_2026-10-21/spike.py`` ``score``): % of the injected
gradient the model takes out, on 64 px block medians, constant offset ignored.
"""
from __future__ import annotations

import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.core.painted_background import (
    NEBULA,
    SKY,
    UNPAINTED,
    apply_painted,
    auto_labels,
    background_model,
    rasterize_strokes,
    select_sky,
)

_SKY = np.array([0.02, 0.019, 0.018], np.float32)
_NOISE = 0.0004
_TINT = np.array([1.0, 0.8, 0.55], np.float32)     # asymmetric R/B, as the spike


def _field(h=540, w=960, seed=0):
    rng = np.random.default_rng(seed)
    data = _SKY + rng.normal(0, _NOISE, (h, w, 3)).astype(np.float32)
    yy, xx = np.mgrid[-6:7, -6:7]
    for _ in range(300):
        y, x = rng.integers(6, h - 7), rng.integers(6, w - 7)
        sig = rng.uniform(1.0, 2.0)
        psf = np.exp(-(yy ** 2 + xx ** 2) / (2 * sig ** 2))[..., None]
        data[y - 6:y + 7, x - 6:x + 7] += (rng.uniform(0.02, 0.5) * psf
                                           * rng.uniform(0.8, 1.2, 3)).astype(np.float32)
    return data.astype(np.float32)


def _coords(shape):
    h, w = shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return y / h, x / w


def _tinted(g, level):
    g = (g - g.min()) / (g.max() - g.min())
    return (g[..., None] * _TINT * level).astype(np.float32)


def _moon(shape, level):
    y, x = _coords(shape)
    return _tinted(np.exp(-((x + 0.3) ** 2 + (y - 0.2) ** 2) / (2 * 0.35 ** 2)), level)


def _patchy(shape, level):
    y, x = _coords(shape)
    rng = np.random.default_rng(1)
    g = sum(rng.uniform(.4, 1) * np.exp(-((x - cx) ** 2 + (y - cy) ** 2)
                                        / (2 * rng.uniform(.15, .3) ** 2))
            for cx, cy in rng.uniform(0, 1, (4, 2)))
    return _tinted(g, level)


def _linear(shape, level):
    y, x = _coords(shape)
    return _tinted(0.6 * x + 0.4 * y, level)


def _blob(shape, centre, sigma, amp):
    h, w = shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    g = amp * np.exp(-((y - centre[0]) ** 2 + (x - centre[1]) ** 2) / (2 * sigma ** 2))
    return (g[..., None] * np.ones(3, np.float32)).astype(np.float32)


def _block_med(a, f=64):
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    b = a[:h, :w].reshape(h // f, f, w // f, f, -1).transpose(0, 2, 1, 3, 4)
    return np.median(b.reshape(h // f, w // f, f * f, -1), axis=2)


def _score(recovered, G):
    recovered, G = _block_med(recovered), _block_med(G)
    res = G - recovered
    res = res - res.mean(axis=(0, 1))
    g = G - G.mean(axis=(0, 1))
    return 100 * (1 - np.sqrt((res ** 2).mean()) / np.sqrt((g ** 2).mean()))


def _sky_strokes(h, w, r=50.0):
    """Four corners and the two vertical-edge midpoints — where a user dabs sky."""
    pts = [(r, r), (w - r, r), (r, h - r), (w - r, h - r), (r, h / 2), (w - r, h / 2)]
    return [{"kind": "sky", "radius": r, "points": [[x, y]]} for x, y in pts]


def _grid_strokes(h, w, rows=3, cols=4, r=50.0):
    """Dabs spread across the frame — what patchy haze needs: six edge dabs
    leave the interior to automatic selection, which rejects haze peaks
    (60.6% recovered vs 80.4% with this grid, measured 2026-11-14)."""
    return [{"kind": "sky", "radius": r, "points": [[x, y]]}
            for y in np.linspace(r, h - r, rows) for x in np.linspace(r, w - r, cols)]


def _recovered(data, G, strokes):
    labels = rasterize_strokes(strokes, data.shape[:2])
    return background_model(data + G, labels) - background_model(data, labels)


# ---------------------------------------------------------------- rasterize
def test_rasterize_paints_in_order_and_erase_clears():
    strokes = [
        {"kind": "sky", "radius": 20.0, "points": [[20, 50], [180, 50]]},
        {"kind": "nebula", "radius": 25.0, "points": [[150, 50]]},
        {"kind": "erase", "radius": 10.0, "points": [[20, 50]]},
    ]
    lab = rasterize_strokes(strokes, (100, 200))
    assert lab.dtype == np.uint8 and lab.shape == (100, 200)
    assert lab[50, 80] == SKY          # sky only
    assert lab[50, 150] == NEBULA      # nebula painted over the sky
    assert lab[50, 20] == UNPAINTED    # erased
    assert lab[5, 100] == UNPAINTED    # never touched


def test_rasterize_tolerates_out_of_bounds_huge_radius_and_single_point():
    lab = rasterize_strokes([{"kind": "sky", "radius": 1e6, "points": [[-500, -500]]}], (40, 60))
    assert (lab == SKY).all()
    lab = rasterize_strokes([{"kind": "nebula", "radius": 5.0,
                              "points": [[-100, 20], [-50, 20]]}], (40, 60))
    assert (lab == UNPAINTED).all()
    lab = rasterize_strokes([{"kind": "sky", "radius": 3.0, "points": [[30, 20]]},
                             {"kind": "sky", "radius": 3.0, "points": []}], (40, 60))
    assert lab[20, 30] == SKY and lab[20, 40] == UNPAINTED


# ---------------------------------------------------------------- recovery
def test_moon_glow_recovered_with_sky_strokes():
    data = _field()
    G = _moon(data.shape, 0.4 * float(_SKY.mean()))
    assert _score(_recovered(data, G, _sky_strokes(*data.shape[:2])), G) >= 80.0


def test_patchy_recovered_with_sky_strokes():
    data = _field()
    G = _patchy(data.shape, 0.4 * float(_SKY.mean()))
    assert _score(_recovered(data, G, _grid_strokes(*data.shape[:2])), G) >= 70.0


def test_linear_recovered_without_strokes():
    data = _field()
    G = _linear(data.shape, 0.4 * float(_SKY.mean()))
    assert _score(_recovered(data, G, []), G) >= 93.0


# ---------------------------------------------------------------- protection
def test_nebula_stroke_protects_a_faint_blob():
    data = _field(seed=3)
    h, w = data.shape[:2]
    # Per-box noise of the luminance the selector sees: the std of 20 px box
    # medians on this fixture (box edge = 960 // 48).
    bs = max(h, w) // 48
    boxes = data[:(h // bs) * bs, :(w // bs) * bs].mean(axis=2)
    box_med = np.median(boxes.reshape(h // bs, bs, w // bs, bs).transpose(0, 2, 1, 3)
                        .reshape(h // bs, w // bs, -1), axis=2)
    amp = 1.5 * float(box_med.std())
    centre, sigma = (h / 2, w / 2), 80.0   # 60 px reached only 0.34 amp of bulge
    data = data + _blob(data.shape, centre, sigma, amp)
    yy, xx = np.mgrid[0:h, 0:w]
    blob = (yy - centre[0]) ** 2 + (xx - centre[1]) ** 2 < sigma ** 2

    model_no_stroke = background_model(data, rasterize_strokes([], (h, w)))
    labels = rasterize_strokes([{"kind": "nebula", "radius": 2.5 * sigma,
                                 "points": [[centre[1], centre[0]]]}], (h, w))
    model_stroke = background_model(data, labels)

    bulge_without = model_no_stroke[blob].mean() - np.median(model_no_stroke)
    bulge_with = model_stroke[blob].mean() - np.median(model_stroke)
    assert bulge_without > 0.3 * amp             # the fixture reaches the failure
    assert abs(bulge_with) < 0.05 * amp


def test_black_border_stays_black_and_is_never_sky():
    data = _field() + _linear((540, 960), 0.4 * float(_SKY.mean()))
    h, w = data.shape[:2]
    data[:, :w // 4] = 0.0                       # a mosaic edge
    img = AstroImage(data)
    out, _ = apply_painted(img, [], 1.0)
    assert (out.data[:, :w // 4] == 0).all()
    assert np.isfinite(out.data).all() and out.data[:, w // 2:].mean() > 0
    sel = select_sky(data, None)
    zero_box = sel.pts[:, 1] * w < (w // 4 - sel.box)   # centres well inside the border
    assert zero_box.any()
    assert not sel.keep[zero_box].any()
    assert (sel.forced[zero_box] == -1).all()


def test_all_nebula_raises_clear_error():
    data = _field(h=200, w=300)
    labels = rasterize_strokes([{"kind": "nebula", "radius": 1e4, "points": [[0, 0]]}],
                               data.shape[:2])
    with pytest.raises(ValueError, match="Too little sky left"):
        background_model(data, labels)


# ---------------------------------------------------------------- shapes, amounts
def test_mono_image_round_trips_shape():
    data = _field(h=200, w=300).mean(axis=2)
    model = background_model(data, None)
    assert model.shape == data.shape and model.dtype == np.float32
    out, sub = apply_painted(AstroImage(data), None, 1.0)
    assert out.data.shape == data.shape and sub.shape == data.shape
    assert auto_labels(data, None).shape == data.shape


def test_small_crop_has_enough_boxes():
    data = _field(h=200, w=300)
    sel = select_sky(data, None)
    assert min(sel.grid) >= 8
    out, _ = apply_painted(AstroImage(data), [], 1.0)
    assert np.isfinite(out.data).all()


def test_auto_labels_keep_user_paint_and_label_the_rest():
    data = _field(h=200, w=300) + _blob((200, 300), (100, 150), 30, 0.02)
    labels = rasterize_strokes([{"kind": "sky", "radius": 10.0, "points": [[150, 100]]}],
                               data.shape[:2])
    lab = auto_labels(data, labels)
    assert lab.shape == (200, 300) and lab.dtype == np.uint8
    assert lab[100, 150] == SKY                   # user's paint wins
    assert lab[100, 170] == NEBULA                # bright blob, automatic
    assert lab[10, 10] == SKY                     # plain corner sky
    assert set(np.unique(lab)) <= {SKY, NEBULA}


def test_amount_half_subtracts_half_the_model():
    data = _field() + _linear((540, 960), 0.4 * float(_SKY.mean()))
    img = AstroImage(data)
    out_full, sub_full = apply_painted(img, [], 1.0)
    out_half, sub_half = apply_painted(img, [], 0.5)
    np.testing.assert_allclose(img.data - out_half.data,
                               0.5 * (img.data - out_full.data), atol=1e-6)
    np.testing.assert_allclose(sub_half, 0.5 * sub_full, atol=1e-7)
    np.testing.assert_allclose(img.data - out_full.data, sub_full, atol=1e-6)


def test_deterministic():
    data = _field(h=200, w=300) + _moon((200, 300), 0.008)
    strokes = _sky_strokes(200, 300, r=20.0)
    a, _ = apply_painted(AstroImage(data), strokes, 1.0)
    b, _ = apply_painted(AstroImage(data.copy()), strokes, 1.0)
    assert a.data.tobytes() == b.data.tobytes()


def test_untouched_metadata_and_dtype():
    data = _field(h=200, w=300)
    meta = {"OBJECT": "NGC 7000", "nested": {"a": 1}}
    img = AstroImage(data.copy(), is_linear=True, metadata=meta)
    before = img.data.copy()
    out, sub = apply_painted(img, [], 1.0)
    assert out.data.dtype == np.float32 and sub.dtype == np.float32
    assert out.metadata == meta and out.metadata is not img.metadata
    assert out.is_linear is True
    assert np.array_equal(img.data, before)       # input unchanged


# ---------------------------------------------------------------- frame edges
def _box_noise(data):
    """Noise of the box medians the selector sees (box edge = long side // 48)."""
    h, w = data.shape[:2]
    bs = max(h, w) // 48
    L = data[:(h // bs) * bs, :(w // bs) * bs].mean(axis=2)
    med = np.median(L.reshape(h // bs, bs, w // bs, bs).transpose(0, 2, 1, 3)
                    .reshape(h // bs, w // bs, -1), axis=2)
    return bs, float(np.median(np.abs(np.diff(med, axis=1)))) * 1.4826


def test_bright_coverage_border_is_followed_to_the_edge():
    # His M 33 master: the stack's coverage border is a narrow band of brighter
    # sky the stiff fit left in (the right box column rejected outright). Here
    # +10 box-sigma at the edge, falling off over one box. Measured 2026-11-14:
    # without the edge strips and the edge clip the band kept 0.50 of its
    # amplitude and the next five boxes 0.12; with them 0.21 and 0.00.
    data = _field()
    h, w = data.shape[:2]
    bs, noise = _box_noise(data)
    amp = 10 * noise
    x = np.arange(w, dtype=np.float32)
    band = amp * np.exp(-(w - 1 - x) / bs)
    d = data + band[None, :, None].astype(np.float32)
    res = d.mean(axis=2) - background_model(d, None).mean(axis=2)
    assert np.median(res[:, w - 2 * bs:]) < 0.3 * amp
    assert abs(np.median(res[:, w - 7 * bs:w - 2 * bs])) < 0.05 * amp


def test_nebula_stroke_protects_a_blob_touching_the_edge():
    # The edge strips get the looser clip, but a Nebula stroke still forces
    # them out: NGC 7000 runs off the frame.
    data = _field(seed=3)
    h, w = data.shape[:2]
    _bs, noise = _box_noise(data)
    amp = 8 * noise
    centre, sigma = (h / 2, w - 1), 80.0
    data = data + _blob(data.shape, centre, sigma, amp)
    labels = rasterize_strokes([{"kind": "nebula", "radius": 2.5 * sigma,
                                 "points": [[centre[1], centre[0]]]}], (h, w))
    sel = select_sky(data, labels)
    under = (labels[np.minimum((sel.pts[:, 0] * h).astype(int), h - 1),
                    np.minimum((sel.pts[:, 1] * w).astype(int), w - 1)] == NEBULA)
    strips = np.arange(len(sel.pts)) >= sel.grid[0] * sel.grid[1]
    assert (under & strips).any()                  # strips do sit on the blob
    assert not sel.keep[under].any()
    model = background_model(data, labels)
    yy, xx = np.mgrid[0:h, 0:w]
    blob = (yy - centre[0]) ** 2 + (xx - centre[1]) ** 2 < sigma ** 2
    assert abs(model[blob].mean() - np.median(model)) < 0.05 * amp


def test_sky_left_in_one_row_is_too_little_not_a_crash():
    # Nebula everywhere but one row of boxes: collinear centres make the fit's
    # plane term singular — it must read as the user's message.
    data = _field(h=200, w=300)
    h, w = data.shape[:2]
    bs = max(h, w) // 48
    labels = np.full((h, w), NEBULA, np.uint8)
    labels[h // 2 - bs // 2 - 2:h // 2 + bs // 2 + 2] = SKY
    labels[:, :2] = NEBULA
    labels[:, -2:] = NEBULA
    with pytest.raises(ValueError, match="Too little sky left"):
        background_model(data, labels)
