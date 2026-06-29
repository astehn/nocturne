from seestar_processor.core.instrument import SEESTAR_S30_PRO


def test_seestar_s30_pro_profile():
    p = SEESTAR_S30_PRO
    assert p.width == 3840
    assert p.height == 2160
    assert p.pixel_size_um == 2.9
    assert p.focal_length_mm == 150.0
    assert p.bayer_pattern == "RGGB"
    assert round(p.pixel_scale_arcsec, 1) == 4.0
