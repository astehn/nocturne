"""Levels: per-colour black points, Auto version 2 (stops at the clipping
warning), and the versioned option. Spec 2026-10-14-levels-clip-aware."""
import json

import numpy as np
import pytest

from nocturne.core.export import display_rgb8
from nocturne.core.image import AstroImage
from nocturne.core.inspect import (CRUSHED_LIMIT, structural_block_peaks,
                                   structural_channel_clipping)
from nocturne.core.levels import (AUTO, AUTO_V1, AUTO_V2, AUTO_VERSION, BLACK_STEPS,
                                  CrushProbe, apply_levels, auto_black, auto_levels,
                                  describe_offsets, new_levels_option,
                                  parse_levels_option, resolve_levels)
from nocturne.steps.levels import LevelsStep


def _legacy_apply_levels(img, black, gamma, white):
    """apply_levels exactly as it was before colour offsets (main 51b6fdd6)."""
    white = max(white, black + 1e-4)
    out = np.subtract(img.data, black)
    out /= (white - black)
    np.clip(out, 0.0, 1.0, out=out)
    if gamma != 1.0:
        out = np.power(out, 1.0 / max(gamma, 1e-3))
    return AstroImage(out.astype(np.float32, copy=False),
                      is_linear=img.is_linear, metadata=dict(img.metadata))


def _sky(h=903, w=1201, seed=0, means=(0.26, 0.25, 0.24), sigma=0.02):
    """A stretched-looking frame: per-channel sky with independent noise, a
    gradient, a nebula patch and stars. Odd, non-square size so the 3x3 block
    grid has a ragged edge and rows cannot be confused with columns."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    grad = 0.03 * (xx / w) - 0.01 * (yy / h)
    d = np.empty((h, w, 3), np.float32)
    for c, m in enumerate(means):
        d[..., c] = m + grad + sigma * rng.standard_normal((h, w))
    d[200:320, 800:1000, 0] += 0.15                      # an Ha patch
    ys, xs = rng.integers(0, h, 300), rng.integers(0, w, 300)
    d[ys, xs] = 0.98                                     # star cores
    return d


def _blue_lane(d):
    """A dark dust lane in BLUE only, wide enough to be structural: version 1's
    shared black point crushes it, nothing else."""
    rng = np.random.default_rng(7)
    h, w = 120, 500
    d[300:300 + h, 150:150 + w, 2] = 0.10 + 0.01 * rng.standard_normal((h, w))
    return d


def _stop_image():
    return AstroImage(_blue_lane(_sky()), is_linear=False)


def _readout(img):
    """The clipping read-out's per-channel structural crushed figure."""
    return structural_channel_clipping(display_rgb8(img)).lo


# --- apply_levels with colour offsets --------------------------------------

@pytest.mark.parametrize("b,g,w", [(0.0, 1.0, 1.0), (0.081, 1.0, 1.0),
                                   (0.05, 1.35, 0.93), (0.4, 0.8, 0.41)])
@pytest.mark.parametrize("offsets", [None, (0.0, 0.0, 0.0), [0, 0, 0]])
def test_no_offsets_is_bit_identical_to_the_old_levels(b, g, w, offsets):
    d = _blue_lane(_sky())
    d[5, 5] = np.nan
    d[6, 6] = np.inf
    img = AstroImage(d, is_linear=False)
    before = d.copy()
    out = apply_levels(img, b, g, w, offsets)
    np.testing.assert_array_equal(out.data, _legacy_apply_levels(img, b, g, w).data)
    assert out.data.dtype == np.float32
    np.testing.assert_array_equal(d, before)                  # source untouched


@pytest.mark.parametrize("g,w", [(1.0, 1.0), (1.35, 0.93)])
def test_an_offset_moves_only_its_own_colour(g, w):
    img = AstroImage(_sky(), is_linear=False)
    b, offs = 0.06, (0.0, 0.021, -0.013)        # uneven: no symmetry to hide in
    out = apply_levels(img, b, g, w, offs).data
    shared = _legacy_apply_levels(img, b, g, w).data
    np.testing.assert_array_equal(out[..., 0], shared[..., 0])
    np.testing.assert_array_equal(out[..., 1],
                                  _legacy_apply_levels(img, b + 0.021, g, w).data[..., 1])
    np.testing.assert_array_equal(out[..., 2],
                                  _legacy_apply_levels(img, b - 0.013, g, w).data[..., 2])


def test_a_negative_black_lifts_that_colours_floor():
    d = _sky()
    d[:50, :50, 0] = 0.0                          # red and blue at zero
    d[:50, :50, 2] = 0.0
    out = apply_levels(AstroImage(d, is_linear=False), 0.0, 1.0, 1.0,
                       (0.0, 0.0, -0.02)).data
    assert out[:50, :50, 2].min() > 0.0           # lifted off zero
    assert out[:50, :50, 0].max() == 0.0          # red, not moved, stays at zero


def test_mono_ignores_the_offsets():
    d = _sky()[..., 0].copy()
    img = AstroImage(d, is_linear=False)
    np.testing.assert_array_equal(apply_levels(img, 0.05, 1.0, 1.0, (0.03, -0.02, 0.01)).data,
                                  _legacy_apply_levels(img, 0.05, 1.0, 1.0).data)


# --- the crushed figure Auto measures IS the read-out's ----------------------

@pytest.mark.parametrize("b,g,w,offs", [
    (0.0, 1.0, 1.0, None), (0.12, 1.0, 1.0, None), (0.2, 1.0, 1.0, None),
    (0.23, 1.0, 1.0, None), (0.15, 1.4, 0.9, (0.02, 0.0, -0.05)),
    (0.1, 1.0, 1.0, (-0.1, 0.1, 0.0)),
])
def test_probe_equals_the_readout(b, g, w, offs):
    d = _blue_lane(_sky())
    d[0:9, 0:9, 1] = np.nan                       # a block of no-data
    d[30:39, 30:39, 0] = -np.inf
    d[60:63, 60:63] = np.inf
    img = AstroImage(d, is_linear=False)
    want = _readout(apply_levels(img, b, g, w, offs))
    assert CrushProbe(img).crushed(b, g, w, offs) == want
    assert max(want) > 0.0 or b == 0.0            # the case is not vacuous


def test_probe_equals_the_readout_when_blocks_are_strided():
    """Same grid when the read-out samples every Nth block, not just all."""
    d = _blue_lane(_sky())
    img = AstroImage(d, is_linear=False)
    out = apply_levels(img, 0.2, 1.0, 1.0)
    peaks = structural_block_peaks(d, 3, 5_000)
    mapped = display_rgb8(apply_levels(AstroImage(peaks, is_linear=False), 0.2, 1.0, 1.0))
    via_peaks = tuple(float(v) for v in (mapped == 0).reshape(-1, 3).mean(axis=0))
    assert via_peaks == structural_channel_clipping(display_rgb8(out), 3, 5_000).lo
    assert via_peaks[2] > 0.0


def test_probe_on_mono_matches_the_grey_readout():
    d = _blue_lane(_sky())[..., 2].copy()
    img = AstroImage(d, is_linear=False)
    want = _readout(apply_levels(img, 0.2, 1.0, 1.0))
    assert CrushProbe(img).crushed(0.2) == (want[0],)
    assert want[0] > CRUSHED_LIMIT


# --- Auto version 2 --------------------------------------------------------

def test_fixture_v1_crushes_blue_only():
    """Precondition: the candidate crushes one channel past the limit."""
    img = _stop_image()
    cand = auto_levels(img.data)[0]
    fig = _readout(apply_levels(img, cand, 1.0, 1.0))
    assert fig[2] > 10 * CRUSHED_LIMIT
    assert fig[0] < CRUSHED_LIMIT and fig[1] < CRUSHED_LIMIT
    assert max(_readout(img)) < CRUSHED_LIMIT     # arrived grey


def test_auto_v2_stops_at_the_largest_black_under_the_limit():
    img = _stop_image()
    a = auto_black(img)
    assert a.stopped and a.candidate == auto_levels(img.data)[0]
    assert 0.0 < a.black < a.candidate
    at = _readout(apply_levels(img, a.black, 1.0, 1.0))
    assert all(f < CRUSHED_LIMIT for f in at), at
    # ...and it is the LARGEST such black, to within one slider step.
    past = _readout(apply_levels(img, a.black + 1.0 / BLACK_STEPS, 1.0, 1.0))
    assert past[2] >= CRUSHED_LIMIT, past


def test_auto_v2_keeps_the_candidate_when_nothing_crushes():
    img = AstroImage(_sky(), is_linear=False)
    a = auto_black(img)
    assert a == (auto_levels(img.data)[0], auto_levels(img.data)[0], False)
    assert a.black > 0.05                          # a real black, not a dead button


def test_auto_v2_never_worsens_an_already_amber_channel():
    """Blue arrives crushed (a zero strip, 2% of the frame); green has a dark
    lane the candidate would crush. Auto stops for green, and is not dragged
    to 0 by blue's figure, which is no worse than it arrived."""
    d = _sky()
    d[:, :24, 2] = 0.0
    rng = np.random.default_rng(3)
    d[500:620, 300:800, 1] = 0.12 + 0.01 * rng.standard_normal((120, 500))
    img = AstroImage(d, is_linear=False)
    arrived = _readout(img)
    assert arrived[2] > CRUSHED_LIMIT                       # precondition: amber
    a = auto_black(img)
    assert a.stopped and a.black > 0.08                     # stopped for green, not at 0
    at = _readout(apply_levels(img, a.black, 1.0, 1.0))
    assert at[2] <= arrived[2]
    assert at[0] < CRUSHED_LIMIT and at[1] < CRUSHED_LIMIT


def test_auto_v1_is_the_candidate_and_linear_keeps_it():
    img = _stop_image()
    c = auto_levels(img.data)[0]
    assert auto_black(img, AUTO_V1) == (c, c, False)
    lin = AstroImage(img.data, is_linear=True)
    assert auto_black(lin) == (c, c, False)


def test_auto_v2_is_deterministic():
    img = _stop_image()
    assert auto_black(img) == auto_black(img)


# --- the option and the step ------------------------------------------------

def test_option_shapes():
    assert AUTO_VERSION == AUTO_V2 == 2
    assert new_levels_option(auto=True) == {"auto": True, "version": 2,
                                            "offsets": [0.0, 0.0, 0.0]}
    assert new_levels_option(0.1, 1.2, 0.9, (0, 0, -0.015)) == {
        "black": 0.1, "gamma": 1.2, "white": 0.9, "offsets": [0.0, 0.0, -0.015]}
    assert parse_levels_option(AUTO) == (True, 1, 0.0, 1.0, 1.0, (0.0, 0.0, 0.0))
    assert parse_levels_option((0.1, 1.2, 0.9)) == (False, 1, 0.1, 1.2, 0.9, (0.0, 0.0, 0.0))
    assert parse_levels_option("") == (False, 1, 0.0, 1.0, 1.0, (0.0, 0.0, 0.0))
    assert parse_levels_option({"auto": True, "offsets": [0.01, 0, 0]}).version == 1
    assert json.loads(json.dumps(new_levels_option(auto=True))) == new_levels_option(auto=True)


def test_step_replays_auto_string_as_version_1():
    img = _stop_image()
    out = LevelsStep().apply(img, AUTO).data
    np.testing.assert_array_equal(out, _legacy_apply_levels(img, *auto_levels(img.data)).data)


def test_step_applies_auto_v2_with_offsets():
    img = _stop_image()
    opt = new_levels_option(auto=True, offsets=(0.0, 0.004, -0.01))
    a = auto_black(img)
    want = apply_levels(img, a.black, 1.0, 1.0, (0.0, 0.004, -0.01)).data
    np.testing.assert_array_equal(LevelsStep().apply(img, opt).data, want)
    assert not np.array_equal(want, LevelsStep().apply(img, AUTO).data)
    r = resolve_levels(img, opt)
    assert r.auto == a and r.offsets == (0.0, 0.004, -0.01)


def test_step_legacy_tuple_is_bit_identical():
    img = _stop_image()
    np.testing.assert_array_equal(LevelsStep().apply(img, (0.07, 1.1, 0.97)).data,
                                  _legacy_apply_levels(img, 0.07, 1.1, 0.97).data)
    np.testing.assert_array_equal(LevelsStep().apply(img, "").data,
                                  _legacy_apply_levels(img, 0.0, 1.0, 1.0).data)


def test_describe_offsets():
    assert describe_offsets((0.0, 0.0, -0.015)) == "blue −0.015"
    assert describe_offsets((0.02, 0.0, 0.0)) == "red +0.020"
    assert describe_offsets((0.0, 0.0, 0.0)) == ""


# --- fix round 1 ------------------------------------------------------------

def _dim_blocks(d, n, channel=2, value=0.15, row0=600):
    """n whole, block-aligned 3x3 patches at `value` in one channel: each is
    exactly one structural block the candidate (~0.22) crushes."""
    for k in range(n):
        y, x = row0 + 3 * (k // 100), 3 + 9 * (k % 100)
        d[y:y + 3, x:x + 3, channel] = value
    return d


def _amber_blue(n_dim):
    """The reviewer's shape: blue ARRIVES amber (a zero strip, 84 of 120,400
    blocks = 0.0698%) and a few dim blue blocks sit above zero."""
    d = _sky()
    d[0:3, 0:252, 2] = 0.0
    return AstroImage(_dim_blocks(d, n_dim), is_linear=False)


def test_an_invisible_rise_on_an_amber_channel_does_not_collapse_auto():
    img = _amber_blue(1)                      # +1 block = +0.0008 points
    arrived = _readout(img)
    assert arrived[2] >= CRUSHED_LIMIT        # precondition: amber on arrival
    cand = auto_levels(img.data)[0]
    assert _readout(apply_levels(img, cand, 1.0, 1.0))[2] > arrived[2]   # it does rise
    assert auto_black(img) == (cand, cand, False)


def test_a_visible_rise_on_an_amber_channel_still_stops_auto():
    from nocturne.core.inspect import CRUSH_INVISIBLE
    img = _amber_blue(10)                     # +10 blocks = +0.0083 points
    arrived = _readout(img)
    a = auto_black(img)
    assert a.stopped and 0.12 < a.black < a.candidate     # stopped at the dim blocks, not 0
    assert _readout(apply_levels(img, a.black, 1.0, 1.0))[2] - arrived[2] < CRUSH_INVISIBLE


def _boundary_image(n_dim):
    """900x1200 = 120,000 blocks, so 60 crushed blocks is EXACTLY the limit."""
    d = _sky(900, 1200)
    return AstroImage(_dim_blocks(d, n_dim), is_linear=False)


def test_boundary_fixture_is_exact():
    img = _boundary_image(60)
    cand = auto_levels(img.data)[0]
    assert max(_readout(img)) == 0.0
    assert _readout(apply_levels(img, cand, 1.0, 1.0)) == (0.0, 0.0, CRUSHED_LIMIT)


def test_a_channel_exactly_at_the_limit_fails_and_just_under_passes():
    at, under = _boundary_image(60), _boundary_image(59)
    assert auto_black(at).stopped                       # read-out is amber at >=
    c = auto_levels(under.data)[0]
    assert auto_black(under) == (c, c, False)


def test_an_unknown_future_auto_version_refuses():
    from nocturne.history.project_store import NewerVersionError
    img = _stop_image()
    with pytest.raises(NewerVersionError):
        auto_black(img, AUTO_VERSION + 1)
    with pytest.raises(NewerVersionError):
        LevelsStep().apply(img, {"auto": True, "version": AUTO_VERSION + 1,
                                 "offsets": [0, 0, 0]})


@pytest.mark.parametrize("shape", [(30, 30, 2), (30, 30, 4)])
def test_crush_probe_wants_one_or_three_channels(shape):
    """AstroImage refuses these shapes today; the probe says so itself rather
    than relying on that, since a 2- or 4-channel array would otherwise be
    measured as something the read-out never shows."""
    from types import SimpleNamespace
    with pytest.raises(ValueError, match="1 or 3 channels"):
        CrushProbe(SimpleNamespace(data=np.full(shape, 0.3, np.float32), is_linear=False))


def test_the_tolerance_never_lets_auto_turn_a_channel_amber():
    """Blue arrives JUST under the limit (59 of 120,000 blocks at zero); one dim
    block would take it to exactly the limit — a rise far smaller than
    CRUSH_INVISIBLE, but it turns the read-out amber, so Auto must stop."""
    d = _sky(900, 1200)
    _dim_blocks(d, 59, value=0.0, row0=300)
    img = AstroImage(_dim_blocks(d, 1), is_linear=False)
    assert 0.0 < _readout(img)[2] < CRUSHED_LIMIT                 # arrived grey
    cand = auto_levels(img.data)[0]
    assert _readout(apply_levels(img, cand, 1.0, 1.0))[2] == CRUSHED_LIMIT
    a = auto_black(img)
    assert a.stopped
    assert _readout(apply_levels(img, a.black, 1.0, 1.0))[2] < CRUSHED_LIMIT
