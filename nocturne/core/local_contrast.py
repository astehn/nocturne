from __future__ import annotations

import numpy as np
from skimage.exposure import equalize_adapthist

from .image import AstroImage


def prepare(img: AstroImage) -> np.ndarray:
    """The CLAHE of luminance — the part no `amount` changes, 0.78 s of a 0.90 s
    call on a 33 MP master (2026-10-06). Computed once per base by the live
    preview and handed to `apply_prepared`."""
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    lum = data if data.ndim == 2 else data.mean(axis=2)
    return equalize_adapthist(lum, clip_limit=0.01).astype(np.float32)


def enhance(img: AstroImage, amount: float) -> AstroImage:
    """Local-contrast (CLAHE) boost on luminance, blended by `amount` in [0, 1].
    Color is rescaled by the luminance ratio so hue is preserved."""
    if float(np.clip(amount, 0.0, 1.0)) == 0.0:
        return apply_prepared(img, None, amount)    # no CLAHE needed for a no-op
    return apply_prepared(img, prepare(img), amount)


def apply_prepared(img: AstroImage, clahe: np.ndarray | None,
                   amount: float) -> AstroImage:
    """`enhance` given `prepare(img)` for this same `img` — bit-identical."""
    amount = float(np.clip(amount, 0.0, 1.0))
    if amount == 0.0:
        # Exactly no change, as recover_core does. Through the blend below it
        # is not: the ratio's 1e-6 guard darkens near-black pixels.
        return img.copy()
    data = np.clip(img.data, 0.0, 1.0).astype(np.float32)
    if data.ndim == 2:
        out = data * (1 - amount) + clahe * amount
        return AstroImage(
            np.clip(out, 0.0, 1.0).astype(np.float32),
            is_linear=img.is_linear, metadata=dict(img.metadata),
        )
    lum = data.mean(axis=2)
    new_lum = lum * (1 - amount) + clahe * amount
    ratio = new_lum / np.maximum(lum, 1e-6)
    out = np.clip(data * ratio[..., None], 0.0, 1.0)
    return AstroImage(
        out.astype(np.float32), is_linear=img.is_linear, metadata=dict(img.metadata)
    )
