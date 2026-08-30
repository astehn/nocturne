import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_TRAINING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TRAINING)
sys.path.insert(0, _TRAINING)
sys.path.insert(0, _REPO_ROOT)

from build_injection import (  # noqa: E402
    HELD_OUT,
    build_group,
    plan_groups,
    write_group_tiles,
)


class _Group:
    """The three attributes plan_groups reads off a FrameGroup."""

    def __init__(self, slug, target, n, mosaic=False):
        self.slug, self.target_dir, self.frames = slug, target, list(range(n))
        self.mosaic = mosaic


# ------------------------------------------------------------- the holdout

def test_the_test_masters_are_never_training_material():
    """M8 and M45 are the only honest tests we have. NGC6888 and NGC7000 are the
    gate's held-out pairs. A model trained on any of them cannot be judged by
    them, and every conclusion of the 2026-08-24 postmortem rested on that
    separation.

    NGC7000 replaced NGC281 on 2026-08-30 so NGC281's recovered 1514 frames could
    train; it keeps the light-polluted holdout the split needs. What must never
    change is that M8 and M45 are in here.
    """
    assert {"M8", "M45", "NGC6888", "NGC7000"} <= set(HELD_OUT)
    assert {"M8", "M45"} <= set(HELD_OUT), "Andreas' own masters are not negotiable"


def test_held_out_targets_are_excluded_from_the_plan():
    groups = [_Group("s30_M8_x", "M8", 460), _Group("s30_M16_x", "M16", 366),
              _Group("s30_NGC6888_x", "NGC6888", 183),
              _Group("s50_M42_x", "M42", 2361)]
    kept = [g.target_dir for g in plan_groups(groups)]
    assert "M8" not in kept and "NGC6888" not in kept
    assert "M16" in kept and "M42" in kept


def test_every_held_out_target_is_excluded_not_just_the_two_checked():
    """Swept, so a future edit that drops one name from HELD_OUT is caught by
    the rule rather than by whichever two names an example happened to use."""
    groups = [_Group(f"s30_{t}_x", t, 400) for t in HELD_OUT]
    assert plan_groups(groups) == []


def test_a_group_too_small_for_two_halves_is_skipped():
    assert plan_groups([_Group("s30_x", "X", 4)]) == []


def test_a_mosaic_is_skipped():
    """A mosaic's frames do not share a canvas, so subtracting one half from
    the other leaves the SKY behind, not noise -- the one thing the field must
    not contain. build_dataset excludes them for the same reason."""
    assert plan_groups([_Group("s30_M31_x", "M31", 900, mosaic=True)]) == []


# ------------------------------------------------ one target, four fields

class _FakePrepared:
    """Stands in for PreparedStack: records exactly which frames were stacked.

    Each frame contributes its own fixed random plane, so an integration is a
    fingerprint of the set that produced it and a test can tell two splits
    apart.
    """

    def __init__(self, paths, shape=(24, 24, 3)):
        self.available_paths = tuple(paths)
        self.shape = shape
        self.calls: list[tuple[str, ...]] = []
        rng = np.random.default_rng(7)
        # A shared scene plus per-frame noise, so the target has structure to
        # be scaled BY and is not simply its own noise.
        self._scene = (0.1 + 0.4 * rng.random(shape)).astype(np.float32)
        self._plane = {p: self._scene + rng.normal(0, 0.02, shape).astype(np.float32)
                       for p in self.available_paths}

    def integrate(self, subset, **kw):
        subset = tuple(subset)
        self.calls.append(subset)
        data = np.mean([self._plane[p] for p in subset], axis=0).astype(np.float32)
        return SimpleNamespace(
            data=data,
            coverage=np.full(self.shape[:2], len(subset), np.int32),
            used=subset, method_used="sigma_clip",
            integration_seconds=10.0 * len(subset))


def _paths(n):
    # Under a directory that does not exist, so Path.resolve() cannot rewrite
    # it through a symlink (/tmp -> /private/tmp on macOS) and the assertions
    # below can compare against the same strings partition_pair returns.
    return [f"/nocturne-injection-test/f{i:04d}.fits" for i in range(n)]


def test_the_noise_fields_and_the_target_come_from_the_same_group():
    """Borrowing a field from another sky would put bright-pixel noise over
    dark sky: D carries signal-dependent shot noise tied to the intensities of
    the field it was made from. Silently plausible, physically wrong."""
    paths = _paths(40)
    prepared = _FakePrepared(paths)
    build_group(prepared, list(paths), seed=1)
    allowed = {str(Path(p).resolve()) for p in paths}
    used = {p for call in prepared.calls for p in call}
    assert used <= allowed, f"stacked frames from outside the group: {used - allowed}"


def test_each_field_comes_from_two_disjoint_halves():
    """An overlapping split shares frames, hence noise, between the two sides:
    the subtraction would then cancel part of the very noise it exists to
    measure, and the field would be quieter than the stack it claims to be."""
    paths = _paths(40)
    prepared = _FakePrepared(paths)
    build_group(prepared, list(paths), seed=1)
    assert len(prepared.calls) == 8          # four splits, two halves each
    for i in range(0, 8, 2):
        a, b = set(prepared.calls[i]), set(prepared.calls[i + 1])
        assert not (a & b), f"split {i // 2} overlaps in {len(a & b)} frames"
        assert len(a) == len(b) == 20


def test_the_four_fields_are_four_different_splits():
    """Four fields from one split would be four copies of the same noise, and
    the 'four different disjoint half-splits' in the design would be decorative."""
    paths = _paths(40)
    prepared = _FakePrepared(paths)
    out = build_group(prepared, list(paths), seed=1)
    assert out.fields.shape[0] == 4
    for i in range(4):
        for j in range(i + 1, 4):
            assert not np.allclose(out.fields[i], out.fields[j]), \
                f"field {i} and field {j} are the same noise"


def test_the_target_is_scaled_into_the_unit_range_and_the_fields_with_it():
    """Everything downstream (to_model_space, asinh_a=0.01) assumes the ladder
    pairs' 0..1 convention. A field divided by a different scale than its own
    target would inject noise of the wrong size -- and it would look right."""
    paths = _paths(40)
    prepared = _FakePrepared(paths)
    out = build_group(prepared, list(paths), seed=1)
    assert 0.0 <= float(out.target.min()) and float(out.target.max()) <= 1.0
    assert float(out.target.max()) > 0.5, "scaled to something, but not to the scene"
    # Recomputed from the two half-stacks split 0 actually integrated, so this
    # checks the ONE divisor claim rather than merely that both look plausible.
    raw_a = np.mean([prepared._plane[p] for p in prepared.calls[0]], axis=0)
    raw_b = np.mean([prepared._plane[p] for p in prepared.calls[1]], axis=0)
    assert np.allclose(out.target, np.clip((raw_a + raw_b) / 2 / out.scale, 0, 1),
                       atol=1e-6)
    assert np.allclose(out.fields[0], (raw_a - raw_b) / np.sqrt(2) / out.scale,
                       atol=1e-6)


def test_the_depth_recorded_is_the_frame_count_the_target_actually_has():
    """The dataset turns a requested stack depth into a sigma with the sqrt(n)
    law, off THIS number. Recording the group's raw frame count instead of the
    two halves that were really stacked would mislabel every sample."""
    paths = _paths(41)                       # odd, so half*2 != len(paths)
    prepared = _FakePrepared(paths)
    out = build_group(prepared, list(paths), seed=1)
    assert out.half == 20
    assert out.depth == 40


def test_a_tile_carries_its_target_its_four_fields_and_its_depth(tmp_path):
    paths = _paths(40)
    prepared = _FakePrepared(paths, shape=(40, 40, 3))
    out = build_group(prepared, list(paths), seed=1)
    n = write_group_tiles(tmp_path, out, tile_size=24, overlap=8, min_coverage=0.9)
    assert n > 0
    written = sorted(tmp_path.glob("tile_*.npz"))
    assert len(written) == n
    with np.load(written[0]) as rec:
        assert rec["target"].shape == (24, 24, 3)
        assert rec["fields"].shape == (4, 24, 24, 3)
        assert rec["coverage"].shape == (24, 24)
        assert int(rec["depth"]) == 40


def test_low_coverage_tiles_are_not_written(tmp_path):
    """A frame-edge pixel was reached by only some frames, so its 'clean'
    target is not clean there -- the same rule materialize_tiles applies."""
    paths = _paths(40)
    prepared = _FakePrepared(paths, shape=(40, 40, 3))
    out = build_group(prepared, list(paths), seed=1)
    out.coverage[:, :20] = 0.1
    n = write_group_tiles(tmp_path, out, tile_size=24, overlap=8, min_coverage=0.9)
    full = write_group_tiles(tmp_path / "all", out, tile_size=24, overlap=8,
                             min_coverage=0.0)
    assert 0 <= n < full


def test_plan_groups_excludes_held_out_under_the_archives_own_naming():
    """The exclusion that never fired. plan_groups compared target_dir to
    HELD_OUT by equality, and the archive rebuilt off the Seestar names things
    "M 8_sub" where the list says "M8" — so on 2026-08-30 a dry run showed all
    four held-out targets queued for building, including Andreas' own masters.

    Detecting that in a preflight was not enough; this is the code that decides.
    """
    from types import SimpleNamespace

    from build_injection import plan_groups

    def g(name, n=200):
        return SimpleNamespace(target_dir=name, frames=tuple(range(n)), mosaic=False)

    groups = [g("M 8_sub"), g("M 45_sub"), g("NGC 6888_sub"), g("NGC 7000 LP"),
              g("IC 1396A_sub", 2535), g("NGC281_sub", 1514)]
    kept = {x.target_dir for x in plan_groups(groups)}
    assert kept == {"IC 1396A_sub", "NGC281_sub"}, f"kept {sorted(kept)}"


def test_a_deep_group_is_not_condemned_by_one_stray_frame():
    """NGC 281's 1514 frames were flagged a mosaic by a 3.89-degree RA span set
    by ONE frame caught mid-slew, which would have dropped the second-deepest
    group in the archive on the day it was released for training."""
    from nocturne.training.pairs import robust_span, sky_ra_span
    ra = [13.63] * 1512 + [9.95, 13.85]          # the real distribution
    span = sky_ra_span(robust_span(ra), 56.77)
    assert span < 1.5, f"NGC 281 still reads as a mosaic at {span:.2f} deg"
