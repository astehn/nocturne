"""Stretch version 2 (2026-10-11): the linked stretch measures the sky on the
sky and takes its black point from the noisiest channel. Version 1 stays, byte
for byte, for every stretch saved before it — Stretch is REPLAYED on reopen.
"""
import hashlib
import json
import os
import zipfile

import numpy as np
import pytest

import nocturne.core.autostretch as A
from nocturne.core.autostretch import (STRETCH_V1, STRETCH_V2, neutral_stretch,
                                       stretch_v2_params)
from nocturne.core.image import AstroImage
from nocturne.core.stretch import amount_to_target, apply_stretch
from nocturne.steps.stretch_step import (StretchStep, new_stretch_option,
                                         parse_stretch_version)

_LEVEL = 1.0 / 255.0


# --- version 1 replays byte-identically ----------------------------------------

def _legacy_frames():
    """Deterministic linear frames covering every branch of the v1 stretch."""
    rng = np.random.default_rng(20261011)
    frames = {}
    h, w = 300, 400
    sky = np.array([0.020, 0.019, 0.021], np.float32)
    noise = np.array([4e-4, 2.5e-4, 6e-4], np.float32)
    d = sky + rng.normal(0, 1, (h, w, 3)).astype(np.float32) * noise
    d[60:240, 80:300] += np.array([0.002, 0.003, 0.009], np.float32)
    frames["nebula"] = np.clip(d, 0, 1).astype(np.float32)
    b = frames["nebula"].copy()
    b[:25] = 0.0
    b[:, -40:] = 0.0
    frames["border"] = b
    n = frames["nebula"].copy()
    n[5, 7, 1] = np.nan
    frames["nan"] = n
    frames["mono"] = frames["nebula"][..., 1].copy()
    big = (sky + rng.normal(0, 1, (900, 700, 3)).astype(np.float32) * noise)
    big[200:700, 100:500] += np.array([0.006, 0.002, 0.001], np.float32)
    frames["big"] = np.clip(big, 0, 1).astype(np.float32)
    return frames


def _digest(a):
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str((a.shape, a.dtype.str)).encode())
    h.update(a.tobytes())
    return h.hexdigest()[:24]


# Captured from neutral_stretch on main @ 15e3505, BEFORE version 2 existed.
# They pin the exact bytes old projects reproduce. If they fail after a numpy
# (or Python/platform) upgrade with no change to autostretch.py, do NOT just
# regenerate them: build the same fixtures on a checkout of 15e3505 under the
# NEW numpy and compare with the branch. Equal there means the library moved
# old pictures for everyone and the hashes may be re-captured from 15e3505;
# different means our code changed version 1 and must be fixed.
_V1_HASHES = {
    ("nebula", 0.205): "b30d6a184de233c6938b8f21",
    ("nebula", 0.31): "e9c65733c463748a304e38b3",
    ("border", 0.205): "3e087c4baeb8f8a0e9358a7f",
    ("border", 0.31): "ad74297c16f38a3a831d46c1",
    ("nan", 0.205): "b5609b9c9a7587757d27c976",
    ("nan", 0.31): "eb2b8a3deb18eceb36a02733",
    ("mono", 0.205): "b1edd3190ab0c39941bb4e7b",
    ("mono", 0.31): "f11871b51cce6249ce9247f5",
    ("big", 0.205): "d4572a64b9163c9dc5dfce97",
    ("big", 0.31): "9ffb6de2c907c386341aea51",
}
# StretchStep().apply(nebula, option) on the same commit, for the option shapes
# saved projects and recipes hold.
_V1_STEP_HASHES = [
    (0.3, "b30d6a184de233c6938b8f21"),
    ("", "b30d6a184de233c6938b8f21"),
    ({"amount": 0.3, "linked": True}, "b30d6a184de233c6938b8f21"),
    ({"amount": 0.55}, "d08e2cf9812c30c03ffce67b"),
]


@pytest.mark.parametrize("key", sorted(_V1_HASHES))
def test_version_1_is_byte_identical_to_the_old_stretch(key):
    name, target = key
    data = _legacy_frames()[name]
    target = 0.205 if target == 0.205 else amount_to_target(0.6)
    assert _digest(neutral_stretch(data, target, version=STRETCH_V1)) == _V1_HASHES[key]


@pytest.mark.parametrize("option,expected", _V1_STEP_HASHES)
def test_an_option_without_a_version_replays_as_version_1(option, expected):
    img = AstroImage(_legacy_frames()["nebula"], is_linear=True)
    assert _digest(StretchStep().apply(img, option).data) == expected


def test_the_version_is_read_from_every_option_shape():
    assert parse_stretch_version({"amount": 0.3, "linked": True, "version": 2}) == 2
    assert parse_stretch_version({"amount": 0.3, "linked": True}) == STRETCH_V1
    assert parse_stretch_version(0.3) == STRETCH_V1
    assert parse_stretch_version("") == STRETCH_V1
    assert parse_stretch_version(None) == STRETCH_V1


def test_a_new_option_records_the_current_version():
    opt = new_stretch_option(0.3)
    assert opt == {"amount": 0.3, "linked": True, "version": A.STRETCH_VERSION}
    assert A.STRETCH_VERSION == STRETCH_V2


def test_the_new_option_replays_as_version_2():
    img = AstroImage(_legacy_frames()["nebula"], is_linear=True)
    got = StretchStep().apply(img, new_stretch_option(0.3)).data
    assert np.array_equal(got, neutral_stretch(img.data, amount_to_target(0.3),
                                               version=STRETCH_V2))
    assert _digest(got) != _V1_STEP_HASHES[0][1]


def test_the_revert_switch_sends_every_new_stretch_back_to_version_1(monkeypatch):
    monkeypatch.setattr(A, "STRETCH_VERSION", STRETCH_V1)
    data = _legacy_frames()["nebula"]
    assert new_stretch_option(0.3)["version"] == STRETCH_V1
    assert _digest(neutral_stretch(data, 0.205)) == _V1_HASHES[("nebula", 0.205)]
    img = AstroImage(data, is_linear=True)
    assert _digest(apply_stretch(img, 0.3).data) == _V1_HASHES[("nebula", 0.205)]
    assert _digest(A.autostretch(img)) == _V1_HASHES[("nebula", 0.205)]


def test_an_unknown_version_is_refused_not_guessed():
    with pytest.raises(ValueError):
        neutral_stretch(_legacy_frames()["nebula"], 0.205, version=7)


def test_recipe_keeps_the_version_only_when_it_was_recorded():
    """Re-saving an old recipe must not upgrade its stretch."""
    from nocturne.recipe import deserialize_option, serialize_option
    assert "version" not in serialize_option("stretch", 0.3)
    assert "version" not in serialize_option("stretch", {"amount": 0.3, "linked": True})
    assert serialize_option("stretch", new_stretch_option(0.3))["version"] == STRETCH_V2
    assert serialize_option("stretch", {"amount": 0.3, "version": 1})["version"] == 1
    old = deserialize_option("stretch", serialize_option("stretch", 0.3))
    assert parse_stretch_version(old) == STRETCH_V1


def test_batch_replays_each_recipe_in_its_own_version():
    from nocturne.batch import apply_recipe
    from nocturne.recipe import Recipe
    from nocturne.settings import Settings
    img = AstroImage(_legacy_frames()["nebula"], is_linear=True)
    old = apply_recipe(img, Recipe(steps=[{"stage": "stretch",
                                           "option": {"amount": 0.3, "linked": True}}]),
                       Settings())
    assert _digest(old.data) == _V1_HASHES[("nebula", 0.205)]
    new = apply_recipe(img, Recipe(steps=[{"stage": "stretch",
                                           "option": new_stretch_option(0.3)}]),
                       Settings())
    assert np.array_equal(new.data, neutral_stretch(img.data, 0.205, version=STRETCH_V2))


def test_a_saved_project_reopens_each_stretch_in_its_own_version(tmp_path):
    from nocturne.history.project import Project
    from nocturne.history.project_store import load_project, save_project

    base = AstroImage(_legacy_frames()["nebula"], is_linear=True)
    for option, want_version in (({"amount": 0.3, "linked": True}, None),
                                 (new_stretch_option(0.3), STRETCH_V2)):
        p = Project(base, str(tmp_path / "cache"))
        p.run_step(StretchStep(), option)
        made = p.current().data.copy()
        path = str(tmp_path / f"p{want_version}.nocturne")
        save_project(p, path)
        with zipfile.ZipFile(path) as zf:
            stored = json.loads(zf.read("manifest.json"))["steps"][0]["option"]
        assert stored.get("version") == want_version
        loaded = load_project(path, str(tmp_path / f"cache{want_version}")).project
        assert np.array_equal(loaded.current().data, made)
        if want_version is None:
            assert _digest(loaded.current().data) == _V1_HASHES[("nebula", 0.205)]


def test_every_path_that_makes_a_stretch_records_the_version():
    """The panel's Apply, the skip-ahead auto-stretch and Auto Enhance: a bare
    amount there reads as version 1 when the project is reopened, so the
    reopened picture would differ from the one that was saved."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    panels = (root / "nocturne/ui/step_panels.py").read_text()
    assert "w.commit_option = lambda: new_stretch_option(" in panels
    mw = (root / "nocturne/ui/main_window.py").read_text()
    assert "option = new_stretch_option(amount)" in mw
    from nocturne.core.auto_enhance import build_auto_plan
    from nocturne.settings import Settings
    plan = dict(build_auto_plan(AstroImage(np.full((64, 64, 3), 0.02, np.float32),
                                           is_linear=True), Settings(),
                                include_crop=False))
    assert plan["stretch"]["version"] == A.STRETCH_VERSION


# --- what version 2 fixes ------------------------------------------------------

def _blue_nebula(seed=1, h=400, w=500):
    """Equal sky pedestal, blue noise x1.5, a blue nebula over 40% of the frame:
    the M 45 shape. Whole-frame medians put blue's sky low; a pooled MAD crushes
    blue's sky noise."""
    rng = np.random.default_rng(seed)
    noise = np.array([4e-4, 2.5e-4, 6e-4], np.float32)       # blue = 1.5 x red
    d = 0.020 + rng.normal(0, 1, (h, w, 3)).astype(np.float32) * noise
    neb = np.zeros((h, w), bool)
    neb[:, : int(w * 0.40)] = True                           # 40% of the frame
    d[neb] += np.array([0.0003, 0.0005, 0.0020], np.float32)  # faint, as M 45's
    return np.clip(d, 0, 1).astype(np.float32), ~neb


def _sky_levels(out, sky):
    return [255.0 * float(np.median(out[..., c][sky])) for c in range(3)]


def _zeros(out, c):
    return float((out[..., c] < 0.5 / 255).mean())


def test_version_2_puts_the_sky_neutral_and_does_not_crush_blue():
    data, sky = _blue_nebula()
    out = neutral_stretch(data, 0.205, version=STRETCH_V2)
    lv = _sky_levels(out, sky)
    assert max(lv) - min(lv) < 1.0, lv
    assert _zeros(out, 2) < 0.03


def test_the_black_point_comes_from_the_noisiest_channel():
    """Plain sky, so the sky reference cannot be the cause: blue has 2.4x
    green's noise. 2.8 MADs of blue's OWN noise leaves its Gaussian tail below
    the black point, P(z < -2.8 x 0.6745) = 2.95%. A MAD pooled over the three
    channels (version 1's) is mostly green's and crushes ~10% of blue."""
    rng = np.random.default_rng(8)
    noise = np.array([4e-4, 2.5e-4, 6e-4], np.float32)
    d = 0.02 + rng.normal(0, 1, (400, 400, 3)).astype(np.float32) * noise
    out = neutral_stretch(np.clip(d, 0, 1), 0.205, version=STRETCH_V2)
    assert _zeros(out, 2) < 0.035
    old = neutral_stretch(np.clip(d, 0, 1), 0.205, version=STRETCH_V1)
    assert _zeros(old, 2) > 0.06


def test_version_1_fails_both_on_the_same_frame():
    """Teeth: the fixture reproduces what was wrong."""
    data, sky = _blue_nebula()
    out = neutral_stretch(data, 0.205, version=STRETCH_V1)
    lv = _sky_levels(out, sky)
    assert lv[2] < min(lv[0], lv[1]) - 1.0, lv
    assert _zeros(out, 2) > 0.03


def test_neutral_input_stays_neutral():
    rng = np.random.default_rng(4)
    grey = 0.02 + rng.normal(0, 3e-4, (300, 300)).astype(np.float32)
    grey[100:200, 100:200] += 0.004
    data = np.repeat(grey[..., None], 3, axis=2)
    out = neutral_stretch(data, 0.205, version=STRETCH_V2)
    assert np.array_equal(out[..., 0], out[..., 1])
    assert np.array_equal(out[..., 1], out[..., 2])


def test_greens_lower_noise_does_not_tint_the_sky_or_the_nebula():
    """The v0.12.0 bug's shape: green has half the noise on a Bayer sensor. With
    an equal pedestal and a grey nebula, nothing may come out green or magenta."""
    rng = np.random.default_rng(5)
    noise = np.array([4e-4, 2e-4, 4e-4], np.float32)
    d = 0.02 + rng.normal(0, 1, (400, 400, 3)).astype(np.float32) * noise
    d[100:300, 100:300] += 0.004
    out = neutral_stretch(np.clip(d, 0, 1), 0.205, version=STRETCH_V2)
    sky = np.ones((400, 400), bool)
    sky[80:320, 80:320] = False
    for region in (sky, ~sky & np.pad(np.ones((160, 160), bool), 120)):
        lv = _sky_levels(out, region)
        assert abs(lv[1] - (lv[0] + lv[2]) / 2) < 0.5, lv


def test_a_real_colour_is_still_reported():
    """Neutralising the sky is not neutralising the picture."""
    data, sky = _blue_nebula()
    out = neutral_stretch(data, 0.205, version=STRETCH_V2)
    neb = ~sky
    r, g, b = (float(np.median(out[..., c][neb])) for c in range(3))
    assert b > g > r


def test_a_tight_crop_with_no_sky_is_calm():
    """Every pixel is nebula, brightening in its own (red) colour: the darkest
    30% is faint nebula, which gets neutralised. Version 1 neutralised the
    MEDIAN nebula there, so version 2 moves the colour less, not more."""
    rng = np.random.default_rng(6)
    h, w = 300, 300
    ramp = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :].repeat(h, 0)
    d = 0.02 + rng.normal(0, 1, (h, w, 3)).astype(np.float32) * np.float32(3e-4)
    d += (0.002 + 0.010 * ramp)[..., None] * np.array([1.0, 0.35, 0.3], np.float32)
    d = np.clip(d, 0, 1).astype(np.float32)
    meds2, ref2, *_ = stretch_v2_params(d, 0.205)
    shift2 = max(abs(m - ref2) for m in meds2)
    meds1 = [float(np.median(d[..., c])) for c in range(3)]
    shift1 = max(abs(m - float(np.mean(meds1))) for m in meds1)
    assert shift2 < shift1
    out = neutral_stretch(d, 0.205, version=STRETCH_V2)
    assert np.isfinite(out).all()
    assert max(_zeros(out, c) for c in range(3)) < 0.03
    # still red where the nebula is brightest
    right = np.zeros((h, w), bool)
    right[:, -30:] = True
    r, g, b = _sky_levels(out, right)
    assert r > g and r > b


def test_a_black_border_stays_black_and_is_not_sky():
    data, sky = _blue_nebula(seed=2)
    framed = data.copy()
    framed[:40] = 0.0
    framed[:, -50:] = 0.0
    border = np.zeros(data.shape[:2], bool)
    border[:40] = True
    border[:, -50:] = True
    out = neutral_stretch(framed, 0.205, version=STRETCH_V2)
    assert (out[border] == 0.0).all()
    meds_framed, ref_f, sh_f, *_ = stretch_v2_params(framed, 0.205)
    inner = data[40:, :-50]
    meds_inner, ref_i, sh_i, *_ = stretch_v2_params(inner, 0.205)
    noise = 2.5e-4
    assert max(abs(a - b) for a, b in zip(meds_framed, meds_inner)) < 0.1 * noise
    assert abs(sh_f - sh_i) < 0.1 * noise
    lv = _sky_levels(out, sky & ~border)
    assert max(lv) - min(lv) < 1.0, lv


def test_nan_is_not_data_and_does_not_poison_the_stretch():
    data = _legacy_frames()["nan"]
    out = neutral_stretch(data, 0.205, version=STRETCH_V2)
    assert np.isfinite(out).all()
    assert (out[5, 7] == 0.0).all()


# --- preview == apply ----------------------------------------------------------

def _scene(h=2160, w=2880, seed=7):
    """Realistic shape: a compact coloured nebula, a gradient-free sky, the
    blue noisiest. Big enough that the full frame is sampled and the sky grid
    is block-averaged, as on a real master."""
    rng = np.random.default_rng(seed)
    noise = np.array([3e-4, 1.8e-4, 4.5e-4], np.float32)
    d = 0.020 + rng.normal(0, 1, (h, w, 3)).astype(np.float32) * noise
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((yy - h * 0.5) / (h * 0.3)) ** 2 + ((xx - w * 0.5) / (w * 0.3)) ** 2
    neb = np.clip(1.0 - r2, 0.0, 1.0).astype(np.float32)
    d += neb[..., None] * np.array([0.002, 0.003, 0.010], np.float32)
    return np.clip(d, 0, 1).astype(np.float32), r2 > 1.2


def _downscale(d, edge):
    """nocturne.ui.preview.downscale's arithmetic, without importing Qt."""
    from skimage.transform import downscale_local_mean
    step = max(1, max(d.shape[:2]) // edge)
    return downscale_local_mean(d, (step, step, 1)).astype(np.float32), step


@pytest.mark.parametrize("edge", [640, 1024])
def test_the_downscaled_preview_measures_the_same_sky_as_the_full_frame(edge):
    """The visual picker renders a 640 px copy; a large window gets more. The
    sky reference is a median of the sky, which averaging does not move, so it
    must agree to a twentieth of the noise. The black point legitimately sits
    nearer the sky on the copy — averaging lowers the noise it is measured from,
    exactly as in version 1 — so what is pinned there is what the user sees:
    the stretched sky, within one 8-bit level, and neutral at both sizes.

    On real data the picker is looser: his M 45 decon state at 640 px puts blue
    2.8 levels from the full frame (1.4 at 1024; IC 1396A <= 0.7), all from the
    black point on the averaged copy — the sky medians agree to 7e-6. Version 1
    was 5.5 levels off there. The live Stretch preview is full-size, so Apply
    is unaffected (review 2026-10-11, M-1)."""
    data, sky = _scene()
    small, step = _downscale(data, edge)
    meds_f, ref_f, *_ = stretch_v2_params(data, 0.205)
    meds_s, ref_s, *_ = stretch_v2_params(small, 0.205)
    noise = 1.8e-4
    assert max(abs(a - b) for a, b in zip(meds_f, meds_s)) < 0.05 * noise
    full = _sky_levels(neutral_stretch(data, 0.205, version=STRETCH_V2), sky)
    sky_s = sky[::step, ::step][: small.shape[0], : small.shape[1]]
    prev = _sky_levels(neutral_stretch(small, 0.205, version=STRETCH_V2), sky_s)
    assert max(abs(a - b) for a, b in zip(full, prev)) < 1.0, (full, prev)
    assert max(full) - min(full) < 1.0 and max(prev) - min(prev) < 1.0


def test_the_live_preview_is_what_apply_commits():
    """The Stretch step's preview renders apply_stretch on the full base with
    the default version; Apply replays the recorded option. Same pixels."""
    img = AstroImage(_legacy_frames()["big"], is_linear=True)
    preview = apply_stretch(img, 0.3, linked=True).data
    committed = StretchStep().apply(img, new_stretch_option(0.3)).data
    assert np.array_equal(preview, committed)


# --- real data -----------------------------------------------------------------

_BENCH = os.environ.get("NOCTURNE_STRETCH_BENCH")


@pytest.mark.skipif(not _BENCH, reason="set NOCTURNE_STRETCH_BENCH to the study's "
                                       "crush/ folder (M45/ and IC1396A/ 4_decon.npy)")
@pytest.mark.parametrize("name,ch,v2_zero,v2_sky", [
    ("M45", 2, 0.0125, 49.3),          # prototype C: blue 1.25%, sky 49/49/49
    ("IC1396A", 0, 0.0026, 47.0),      # prototype C: red 0.26%, sky 47/47/47
])
def test_his_targets_match_the_prototype_he_approved(name, ch, v2_zero, v2_sky):
    from scipy.ndimage import uniform_filter
    d = np.load(os.path.join(_BENCH, name, "4_decon.npy"))
    lum = uniform_filter(d.mean(axis=2), 31)                   # the study's sky
    sky = lum <= np.percentile(A._sample(lum), 30)
    out = neutral_stretch(d, amount_to_target(0.30), version=STRETCH_V2)
    q = (out * 255 + 0.5).astype(np.uint8)
    assert abs(float((q[..., ch] == 0).mean()) - v2_zero) < 0.005
    lv = [255 * float(np.median(out[..., c][sky])) for c in range(3)]
    assert max(lv) - min(lv) < 1.0, lv
    assert all(abs(v - v2_sky) < 1.5 for v in lv), lv
