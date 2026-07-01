import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.core.palette import (
    PALETTES, extract_channels, hoo, pseudo_sho, apply_palette,
)


def _img(pixels):
    # pixels: list of (r,g,b) -> a 1 x N x 3 colour image
    return AstroImage(np.array([pixels], dtype=np.float32), is_linear=False)


def test_extract_channels_ha_red_oiii_greenblue():
    img = _img([(0.8, 0.2, 0.4)])
    ha, oiii = extract_channels(img)
    assert np.allclose(ha, 0.8)
    assert np.allclose(oiii, 0.3)          # (0.2 + 0.4) / 2


def test_extract_channels_rejects_mono():
    mono = AstroImage(np.zeros((4, 4), np.float32))
    with pytest.raises(ValueError):
        extract_channels(mono)


def test_hoo_ha_pixel_red_and_oiii_pixel_teal():
    out = hoo(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    assert ha_px[0] > ha_px[1] and ha_px[0] > ha_px[2]        # red-dominant
    assert np.isclose(oiii_px[1], oiii_px[2]) and oiii_px[1] > oiii_px[0]  # teal


def test_pseudo_sho_ha_gold_oiii_teal():
    out = pseudo_sho(_img([(0.9, 0.1, 0.1), (0.1, 0.9, 0.9)])).data
    ha_px, oiii_px = out[0, 0], out[0, 1]
    # Ha region -> gold: R and G both above B
    assert ha_px[0] > ha_px[2] and ha_px[1] > ha_px[2]
    # OIII region -> teal: B above R
    assert oiii_px[2] > oiii_px[0]


def test_apply_palette_dispatch_and_unknown():
    img = _img([(0.5, 0.5, 0.5)])
    assert apply_palette(img, "HOO").data.shape == img.data.shape
    assert set(PALETTES) == {"HOO", "pseudo_SHO"}
    with pytest.raises(ValueError):
        apply_palette(img, "SHO")
