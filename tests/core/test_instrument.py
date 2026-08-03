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


# --- identifying the camera ---------------------------------------------------
# Every value below was read off real Seestar sub headers, not a spec sheet:
#   S30 Pro (NGC 281 / M 17 / C 27): CREATOR='ZWO Seestar S30 Pro',
#     INSTRUME='imx585' or absent, FOCALLEN=160.0, XPIXSZ=2.9
#   S50 (M 42, 2025-12-09):          CREATOR='ZWO Seestar S50',
#     INSTRUME='Seestar S50',        FOCALLEN=250.0, XPIXSZ=2.9

def test_seestar_s50_profile_matches_its_real_headers():
    from nocturne.core.instrument import SEESTAR_S50
    p = SEESTAR_S50
    assert p.focal_length_mm == 250.0 and p.pixel_size_um == 2.9
    assert p.bayer_pattern == "GRBG"
    assert p.f_ratio == 5.0                     # APERTURE=5.0 is an f-ratio: 250/5 = 50 mm
    assert round(p.pixel_scale_arcsec, 2) == 2.39


def test_identify_reads_the_creator_card():
    from nocturne.core.instrument import identify, SEESTAR_S30_PRO, SEESTAR_S50
    assert identify({"creator": "ZWO Seestar S50"}) is SEESTAR_S50
    assert identify({"creator": "ZWO Seestar S30 Pro"}) is SEESTAR_S30_PRO


def test_identify_survives_the_inconsistent_instrume_card():
    """A single S50 sub says INSTRUME='Seestar S50'; S30 Pro subs say 'imx585'
    or omit it. Both spellings must land on the right camera."""
    from nocturne.core.instrument import identify, SEESTAR_S30_PRO, SEESTAR_S50
    assert identify({"instrument": "Seestar S50"}) is SEESTAR_S50
    assert identify({"instrument": "imx585"}) is SEESTAR_S30_PRO


def test_identify_does_not_confuse_the_s30_pro_with_a_future_s30(monkeypatch):
    """'seestar s30' is a prefix of 'seestar s30 pro', so alias matching must
    prefer the LONGEST alias. Asserting only against today's registry would be
    toothless — there is no competing alias yet — so this registers the base
    S30 that someone will eventually add, and proves the ordering holds."""
    from nocturne.core import instrument as m
    base_s30 = m.Instrument(name="ZWO Seestar S30", sensor="Sony IMX662",
                            width=1920, height=1080, pixel_size_um=2.9,
                            focal_length_mm=150.0, aperture_mm=30.0,
                            bayer_pattern="GRBG", aliases=("seestar s30",))
    monkeypatch.setattr(m, "INSTRUMENTS", (base_s30, m.SEESTAR_S30_PRO, m.SEESTAR_S50))
    assert m.identify({"creator": "ZWO Seestar S30 Pro"}) is m.SEESTAR_S30_PRO
    assert m.identify({"creator": "ZWO Seestar S30"}) is base_s30


def test_identify_falls_back_to_focal_length():
    from nocturne.core.instrument import identify, SEESTAR_S30_PRO, SEESTAR_S50
    assert identify({"focal_length": 250.0}) is SEESTAR_S50
    assert identify({"focal_length": 160.0}) is SEESTAR_S30_PRO


def test_identify_admits_when_it_does_not_know():
    """A 400 mm refractor is not a Seestar, and claiming otherwise is worse than
    saying nothing — callers mark an assumption only when they know they made one."""
    from nocturne.core.instrument import identify
    assert identify({"focal_length": 400.0, "pixel_size": 3.76}) is None
    assert identify({}) is None
    assert identify({"creator": "Some Other Camera"}) is None


def test_an_s50_frame_without_optics_is_not_given_the_s30_pros_scale():
    """The whole point. A metadata-poor S50 master that still names its camera
    gets 2.39"/px, not the S30 Pro's 3.74"/px — a 56% error in the FOV hint."""
    from nocturne.core.instrument import fov_hint, SEESTAR_S50
    fov, src = fov_hint({"creator": "ZWO Seestar S50"}, 1920)
    assert src == "profile"
    assert fov == pytest.approx(SEESTAR_S50.pixel_scale_arcsec * 1920 / 3600.0)


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
