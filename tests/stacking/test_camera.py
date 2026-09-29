from nocturne.stacking.camera import Camera, mismatch

S30 = Camera("ZWO Seestar S30 Pro", (2160, 3840), 3.738)


def test_header_rounding_is_one_camera():
    assert mismatch(S30, Camera("ZWO Seestar S30 Pro", (2160, 3840), 3.7386)) is None


def test_a_different_scale_is_refused_even_at_the_same_size():
    s50pro = Camera("ZWO Seestar S50 Pro", (2160, 3840), 2.30)
    assert "S50 Pro" in mismatch(S30, s50pro)


def test_a_different_size_at_the_same_scale_is_refused():
    assert "different size" in mismatch(S30, Camera("ZWO Seestar S30 Pro", (1080, 1920), 3.738))


def test_an_unknown_side_never_blocks():
    assert mismatch(S30, None) is None and mismatch(None, S30) is None
    assert mismatch(S30, Camera("", (2160, 3840), None)) is None
