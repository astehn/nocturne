import pytest
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


# --- the ONE field-of-view hint, shared by the tool and by SPCC --------------

def test_fov_hint_falls_back_to_the_profile_when_the_header_has_no_optics():
    from nocturne.core.instrument import fov_hint
    fov, src = fov_hint({}, 2160)
    assert src == "profile"
    assert fov is not None and fov > 0


def test_fov_hint_prefers_the_header_when_it_has_optics():
    from nocturne.core.instrument import fov_hint
    fov, src = fov_hint({"focal_length": 400.0, "pixel_size": 3.76}, 2000)
    assert src == "header"
    assert fov == pytest.approx(206.265 * 3.76 / 400.0 * 2000 / 3600.0)


def test_fov_hint_treats_unusable_header_optics_as_absent():
    from nocturne.core.instrument import fov_hint
    for meta in ({"focal_length": 0, "pixel_size": 3.76},
                 {"focal_length": "nonsense", "pixel_size": None},
                 {"focal_length": None, "pixel_size": None}):
        assert fov_hint(meta, 2160)[1] == "profile", meta


def test_spcc_asks_for_the_same_hint_as_the_plate_solve_tool():
    """Found on a real NGC 281 capture 2026-08-01: the panel said "scale assumed
    from Seestar profile" (solved in 4.9 s) while the log said "Couldn't
    plate-solve — used sky balance" for the SAME image. SPCC carried its own
    header-only copy of the hint, so a master without optics in its header made
    it solve blind, fail, and silently drop to sky balance."""
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.color import ColorStep

    seen = {}

    class FakeAstap:
        def solve(self, img, fov_deg=None, ra_hours=None, dec_deg=None, header_cards=None):
            seen["fov"] = fov_deg
            return None                      # fail the solve; we only inspect the hint

    img = AstroImage(np.full((2160, 3840, 3), 0.1, np.float32), is_linear=True,
                     metadata={})            # NO optics in the header
    step = ColorStep(astap=FakeAstap(), gaia_query=lambda *a, **k: [])
    step._photometric(img)          # the method that builds the hint and solves

    assert seen.get("fov") is not None, \
        "SPCC must pass the profile-derived scale, not solve blind"
