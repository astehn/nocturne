from nocturne.core.instrument import SEESTAR_S30_PRO


def test_seestar_s30_pro_profile():
    p = SEESTAR_S30_PRO
    assert p.width == 3840
    assert p.height == 2160
    assert p.pixel_size_um == 2.9
    assert p.focal_length_mm == 160.0
    assert p.bayer_pattern == "GRBG"  # real S30 Pro CFA (from sub headers)
    assert round(p.pixel_scale_arcsec, 1) == 3.7


def test_seestar_s30_pro_sensor_and_fratio():
    p = SEESTAR_S30_PRO
    assert p.sensor == "Sony IMX585"
    assert p.f_ratio == 5.0
