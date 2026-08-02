from __future__ import annotations

import numpy as np

from .image import AstroImage

_KNEE = 0.4   # luminance above which the sky ops fade to nothing


def _shadow_weight(lum: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - lum / _KNEE, 0.0, 1.0) ** 2   # 1 near black, 0 above the knee


def boost_hue(img: AstroImage, hue: float, amount: float = 0.15,
              width: float = 0.12) -> AstroImage:
    """Increase saturation of pixels near `hue` (0..1) with smooth circular
    falloff. Mono is returned unchanged."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    hsv = rgb2hsv(np.clip(img.data, 0.0, 1.0))
    dist = np.abs(hsv[..., 0] - hue)
    dist = np.minimum(dist, 1.0 - dist)                # circular hue distance
    w = np.exp(-(dist ** 2) / (2.0 * width ** 2))
    hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + amount * w), 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def darken_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked darken: pull the dark background down, leave bright signal."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data - amount * _shadow_weight(lum), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))


def lighten_sky(img: AstroImage, amount: float = 0.08) -> AstroImage:
    """Shadow-masked lighten: gently lift the dark background."""
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2, keepdims=True) if img.is_color else data
    out = np.clip(data + amount * _shadow_weight(lum) * (1.0 - data), 0.0, 1.0)
    return AstroImage(out.astype(np.float32), is_linear=img.is_linear,
                      metadata=dict(img.metadata))


def _smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / max(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def soft_glow(img: AstroImage, amount: float = 0.3, radius: float = 10.0,
              threshold: float = 0.15) -> AstroImage:
    """Orton-style bloom: blur a copy and screen it back, gated by a BLURRED
    highlight mask so the glow bleeds outward into the surrounding sky (a real
    dreamy bloom, not just brightening the highlights). Works on mono too."""
    from scipy.ndimage import gaussian_filter
    data = np.clip(img.data, 0.0, 1.0)
    lum = data.mean(axis=2) if img.is_color else data
    hi = gaussian_filter(_smoothstep(lum, threshold, 1.0), radius)   # spread -> bloom bleeds out
    if img.is_color:
        blurred = np.stack([gaussian_filter(data[..., c], radius)
                            for c in range(data.shape[2])], axis=2)
        glow = blurred * (hi[..., None] * amount)
    else:
        blurred = gaussian_filter(data, radius)
        glow = blurred * (hi * amount)
    out = 1.0 - (1.0 - data) * (1.0 - np.clip(glow, 0.0, 1.0))   # screen blend
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def vibrance(img: AstroImage, amount: float = 0.1) -> AstroImage:
    """Saturation boost weighted by (1 - saturation) so under-saturated colour
    lifts more and saturated colour is protected; shadow-protected. Mono unchanged."""
    if not img.is_color:
        return img.copy()
    from skimage.color import hsv2rgb, rgb2hsv
    data = np.clip(img.data, 0.0, 1.0)
    hsv = rgb2hsv(data)
    s = hsv[..., 1]
    lum = data.mean(axis=2)
    shadow_protect = np.clip((lum - 0.12) / 0.18, 0.0, 1.0)     # mirrors saturation.saturate
    neutral_gate = _smoothstep(s, 0.0, 0.05)   # leave true neutrals (s~0, no real hue) alone
    hsv[..., 1] = np.clip(s + amount * (1.0 - s) * shadow_protect * neutral_gate, 0.0, 1.0)
    return AstroImage(np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def dark_structure(img: AstroImage, amount: float = 0.4, radius: float = 10.0) -> AstroImage:
    """Add local contrast to dark structures (dust lanes, dark nebulae) for
    definition — a symmetric local-contrast (unsharp) pass gated to a mid-dark
    luminance band. Sharpens dust detail BOTH ways (a local-dark pixel darkens, a
    local-bright one brightens), so it is brightness-neutral and doesn't mud/darken
    the whole frame the way a deepen-only pull would. The band gate protects the
    background noise floor (very dark) and bright signal (nebula/stars).
    Hue-preserving (luminance gain applied to RGB). Mono supported."""
    from scipy.ndimage import gaussian_filter
    data = np.clip(img.data.astype(np.float32), 0.0, 1.0)
    lum = data.mean(axis=2) if img.is_color else data
    detail = lum - gaussian_filter(lum, radius)            # signed local contrast
    band = _smoothstep(lum, 0.04, 0.10) * (1.0 - _smoothstep(lum, 0.40, 0.60))
    lum_out = np.clip(lum + amount * band * detail, 0.0, 1.0)
    if img.is_color:
        out = data * (lum_out / np.maximum(lum, 1e-4))[..., None]   # hue-preserving gain
    else:
        out = lum_out
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def star_colour_layers(starless: AstroImage, stars: AstroImage,
                       amount: float = 0.2) -> AstroImage:
    """Lift saturation on the STARS layer of a star/starless split, then screen
    the untouched starless layer back on top — so only stars gain colour and
    nebulosity/sky are never affected. Mirrors `saturation.nebula_saturate` but
    targets the opposite layer.

    The split (StarXTerminator when RC-Astro is available, else the free
    sep-based `split_stars`) is done by the caller, so this stays pure. Boosting
    the stars layer is self-masking: it is ~black off the stars, and lifting the
    saturation of a black pixel (value≈0) produces no colour, so nebula can't
    tint even where the split left faint residual. The lift is additive because
    stars are near-white (low saturation); a tiny neutral gate keeps pure-white
    blown cores from taking a hue. `amount=0` is a plain recombine. Mono stars
    (no chroma to boost) recombine unchanged."""
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    if st.ndim == 3 and amount > 0.0:
        from skimage.color import hsv2rgb, rgb2hsv
        hsv = rgb2hsv(st)
        s = hsv[..., 1]
        neutral_gate = _smoothstep(s, 0.0, 0.02)     # don't tint pure-white cores (s~0)
        hsv[..., 1] = np.clip(s + amount * (1.0 - s) * neutral_gate, 0.0, 1.0)
        st = np.clip(hsv2rgb(hsv), 0.0, 1.0).astype(np.float32)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=starless.is_linear, metadata=dict(starless.metadata))


def sharpen_nebulosity_layers(starless: AstroImage, stars: AstroImage,
                              amount: float = 0.6, radius: float = 1.6,
                              floor_pct: float = 20.0, ramp: float = 0.10) -> AstroImage:
    """Sharpen the NEBULOSITY of a star/starless split and add the untouched
    stars back — the thing people leave Nocturne to do in Photoshop.

    Sharpening a stretched astro image globally is the classic way to ruin one:
    it rings bright stars and amplifies background noise into texture. Both
    failure modes are removed here rather than warned about.

      Stars   — the split takes them out first, so they cannot ring, and they are
                screened back afterwards completely untouched. This is the same
                real split (StarXTerminator, else the free sep-based one) that
                Star Colour and Upscale Crop use, not a threshold mask.
      Sky     — a signal mask ramps the effect in just above the sky level, so
                faint background gets none of it. Without this, the loudest
                thing an unsharp mask finds in an astro frame is the noise.

    `floor_pct`/`ramp` are measured, not guessed. They anchor the ramp to the SKY
    rather than to the middle of the histogram: at floor_pct=40/ramp=0.25 the
    mask over nebulosity swung from 0.08 to 1.00 purely with how much sky was in
    frame (a wide field pushes the 40th percentile up INTO the signal), so the
    effect varied by 4x between targets. At 20/0.10 the mask is 0.57-1.00 and the
    acutance gain holds at x1.205-x1.217 across 10-80% sky, while the sky itself
    stays at x1.000-x1.006.

    Positive-only high-pass (`out = base + amount*max(base-blur, 0) * mask`),
    mirroring `deconvolution.sharpen`: adding the negative lobe as a plain
    unsharp mask would carve dark rims around bright nebula edges, which is the
    over-sharpened look that reads as artificial even to people who cannot name
    why.

    `radius` is small on purpose. Mid-scale structure is Local Contrast's job
    (CLAHE); this is for edge acutance, and a large radius here would duplicate
    that badly.
    """
    from scipy.ndimage import gaussian_filter
    base = np.clip(starless.data.astype(np.float32), 0.0, 1.0)
    if amount <= 0.0:
        return _screen_back(base, stars, starless)
    lum = base.mean(axis=2) if base.ndim == 3 else base
    lo = float(np.percentile(lum, floor_pct))
    mask = _smoothstep(lum, lo, min(1.0, lo + ramp))
    # Per channel, like soft_glow: blurring across the colour axis would bleed
    # hue between channels rather than blurring each one spatially.
    blur = (gaussian_filter(base, radius) if base.ndim == 2 else
            np.stack([gaussian_filter(base[..., c], radius) for c in range(base.shape[2])],
                     axis=-1))
    detail = np.maximum(base - blur, 0.0)
    m = mask if base.ndim == 2 else mask[..., None]
    out = np.clip(base + amount * detail * m, 0.0, 1.0)
    return _screen_back(out, stars, starless)


def _screen_back(base: np.ndarray, stars: AstroImage, ref: AstroImage) -> AstroImage:
    """Screen the stars layer over `base` — the same recombine star_colour_layers
    uses, so a split processed either way rejoins identically."""
    st = np.clip(stars.data.astype(np.float32), 0.0, 1.0)
    out = 1.0 - (1.0 - base) * (1.0 - st)
    return AstroImage(np.clip(out, 0.0, 1.0).astype(np.float32),
                      is_linear=ref.is_linear, metadata=dict(ref.metadata))


ENHANCE_OPS = {
    "Boost Red": lambda i: boost_hue(i, 0.0),
    "Boost Cyan": lambda i: boost_hue(i, 0.5),
    "Boost Blue": lambda i: boost_hue(i, 0.667),
    "Boost Gold": lambda i: boost_hue(i, 0.11),
    "Vibrance": lambda i: vibrance(i),
    "Darken Sky": darken_sky,
    "Lighten Sky": lighten_sky,
    "Dark Structure": lambda i: dark_structure(i),
    "Soft Glow": lambda i: soft_glow(i),
}
# "Star Colour" is intentionally excluded — it needs a star split; callers handle it.
