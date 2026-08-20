from __future__ import annotations

import numpy as np

from .image import AstroImage


def apply_levels(img: AstroImage, black: float, gamma: float, white: float) -> AstroImage:
    """Levels adjustment: remap [black, white] to [0, 1] then apply midtone gamma."""
    white = max(white, black + 1e-4)
    x = np.clip((img.data - black) / (white - black), 0.0, 1.0)
    out = np.power(x, 1.0 / max(gamma, 1e-3))
    return AstroImage(
        out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata)
    )


# Black point = median - _BLACK_SIGMA * MAD, the same robust shape autostretch
# uses. 4.0, not autostretch's 2.8, because the two run on different data: 2.8
# clips the LINEAR frame before a midtone transfer, while this runs after the
# stretch has already compressed everything upward. Measured across six real
# masters (M 45, M 31 mosaic, M 8, M 16, NGC 7000, NGC 281): at 2.8 the sky fell
# to 0.106-0.155 and M 8 crushed 1.25% of the frame to pure black; at 4.0 the sky
# lands at 0.150-0.201 with black clipping at or under 0.32% everywhere; at 5.0
# it barely moves three of the six. 4.0 deepens the sky without eating faint
# nebulosity.
_BLACK_SIGMA = 4.0


def auto_levels(data: np.ndarray) -> tuple[float, float, float]:
    """Suggested (black, gamma, white) for a STRETCHED image.

    Sets a black point and nothing else, because after a stretch there is
    nothing else left to set automatically — and both of the other two used to
    do active harm:

    * **Gamma is 1.0.** autostretch deliberately places the background at
      `_TARGET_BG` (0.25); this function used to re-target 0.35 with an adaptive
      gamma, so two steps disagreed about sky brightness and the later one won.
      Measured, it lifted the sky +12% to +30% on every real master. That is the
      "milky" look Andreas rejected. `auto_enhance` had already diagnosed this
      and worked around it locally by discarding the gamma; the manual Levels
      step kept the defect.
    * **White is 1.0.** The stretch already maps the data into [0, 1] with star
      cores at the top, so a percentile white point can only clip stars or
      brighten the frame. The old 99.9th percentile drove ~0.08% of pixels to
      pure white on every master — roughly 6,000 star cores, whose colour is
      real data, since Seestar cores do not saturate in the capture. Raising it
      to 99.99% did not fix it either: on M 16 that percentile is 0.889 against
      a maximum of 0.999, so it BRIGHTENED the sky 0.2013 -> 0.2264, smuggling
      the lift back in through the other end.

    MAD and not a percentile, which is the part that matters on a mosaic: 11.59%
    of Andreas' real M 31 mosaic is empty border outside panel coverage, so the
    old 1st percentile landed inside the border and returned exactly 0.0 — the
    black point silently did nothing on every mosaic he made. The robust
    estimator reads 0.1431 on that same frame and never sees the border.

    nanmedian for the reason `autostretch._stretch_params` documents: these are
    two scalars derived from the whole frame, and with plain `np.median` one NaN
    makes both NaN, which then blanks every pixel.
    """
    lum = data.mean(axis=2) if data.ndim == 3 else data
    if not np.isfinite(lum).any():
        return 0.0, 1.0, 1.0            # no statistics to derive from
    med = float(np.nanmedian(lum))
    mad = float(np.nanmedian(np.abs(lum - med)))
    black = float(np.clip(med - _BLACK_SIGMA * mad, 0.0, 0.5))
    return black, 1.0, 1.0
