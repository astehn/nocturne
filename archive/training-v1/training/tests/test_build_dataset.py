import build_dataset as bd
from build_dataset import Rung, plan_ladder
from nocturne.training.pairs import FrameGroup, FrameInfo


def _truth(rungs):
    return [(r.n_in, r.n_tgt) for r in rungs if r.kind == "truth"]


def _n2n(rungs):
    return [(r.n_in, r.n_tgt) for r in rungs if r.kind == "n2n"]


def test_every_rung_fits_the_group_with_a_reference_reserved():
    for n in (72, 109, 304, 366, 460, 1200):
        for r in plan_ladder(n):
            assert r.n_in + r.n_tgt + 1 <= n, f"{n}: {r} does not fit"
            assert r.n_in >= 1 and r.n_tgt >= 1


def test_truth_rungs_keep_the_old_contract():
    """A truth rung's target must still be genuinely deeper -- that constraint
    is not being relaxed, only bounded to the range where it can be met."""
    for r in plan_ladder(460):
        if r.kind == "truth":
            assert r.n_tgt >= r.n_in * 4.0
            assert r.n_tgt >= 16


def test_a_260_frame_group_reaches_256():
    """The user's ruling, verbatim: 'if a target has 260 it does 256 as well'.
    The old planner capped every target at max(depths)=128 regardless."""
    assert any(n_tgt == 256 for _, n_tgt in _truth(plan_ladder(260)))


def test_a_1200_frame_group_reaches_1024():
    """'if a target has 1200 it will do 1024 as well' -- proves nothing in the
    planner imposes a fixed ceiling."""
    assert any(n_tgt == 1024 for _, n_tgt in _truth(plan_ladder(1200)))


def test_a_72_frame_group_stops_at_64_and_never_tries_128():
    """'if we have a stack with 72 subframes it should stop at 64 and not try
    128'. Asserted as an absence, because emitting an unaffordable rung fails
    later and far away, inside partition_pair."""
    rungs = plan_ladder(72)
    assert rungs, "a 72-frame group must still produce pairs"
    assert all(r.n_in <= 64 and r.n_tgt <= 64 for r in rungs)
    assert not any(r.n_in == 128 or r.n_tgt == 128 for r in rungs)


def test_the_deepest_n2n_input_reaches_the_users_real_depth():
    """The whole point of the spec. M8's 460-frame group must produce an input
    within a few percent of his 405-frame master, or the conditioning channel
    goes on being fed a value outside its training range."""
    deepest = max(n_in for n_in, _ in _n2n(plan_ladder(460)))
    # 381, not 395: the 3% registration reserve (see _RESERVE_FRACTION) costs 14
    # frames here. Against his 405-frame master that is sqrt(405/381) = 1.03,
    # i.e. 3% noisier — still comfortably inside the conditioning range, and far
    # cheaper than losing every deep rung to one unregistrable frame, which is
    # what happened to s50_M101 on 2026-08-24.
    assert deepest >= 375, f"deepest n2n input was only {deepest}"


def test_n2n_rungs_only_appear_above_the_truth_ceiling():
    """Below that depth a genuinely cleaner target exists and is better
    supervision; n2n is for where one cannot exist at all."""
    rungs = plan_ladder(460)
    ceiling = max(r.n_in for r in rungs if r.kind == "truth")
    assert all(r.n_in > ceiling for r in rungs if r.kind == "n2n")


def test_n2n_targets_are_never_shallower_than_the_floor():
    for n in (304, 366, 460, 2361):
        for n_in, n_tgt in _n2n(plan_ladder(n)):
            assert n_tgt >= 64


def test_a_group_too_small_for_any_valid_pair_yields_nothing():
    assert plan_ladder(6) == []


def test_min_target_rejects_a_shallow_target_even_if_the_ratio_passes():
    """A 4-frame stack clears min_ratio=4.0 against a 1-frame input but is
    still mostly noise. Relaxing the knob must bring the bad rung back, or the
    first assertion is not testing what it claims to."""
    assert plan_ladder(6, min_target=16) == []
    assert any(r.n_tgt == 4 for r in plan_ladder(6, min_target=1))


def test_rungs_are_unique():
    for n in (109, 304, 460):
        rungs = plan_ladder(n)
        assert len(rungs) == len({(r.n_in, r.n_tgt) for r in rungs})


def test_the_kind_always_agrees_with_the_ratio_that_defines_it():
    """`kind` is recomputed downstream from (n_in, n_tgt) alone -- Task 3 puts
    that rule in nocturne.training.pairs.rung_kind and _write_pair records ITS
    answer in the manifest. If the planner and that rule ever disagreed, the
    pair would be trained under the loss meant for the other kind.

    Swept rather than spot-checked, because the disagreement is narrow: the
    max-depth rung is `available - min_n2n_target` frames wide, and around
    n_frames=74 that lands at n_in=9, where a 64-frame target genuinely IS
    four times deeper and so is a truth pair, not a Noise2Noise one.
    """
    for n in range(3, 600):
        for r in plan_ladder(n):
            expected = "truth" if r.n_tgt >= r.n_in * 4.0 else "n2n"
            assert r.kind == expected, f"n_frames={n}: {r} should be {expected}"


# The real archive's two geometries, as _read_frame_info records them
# (NAXIS2, NAXIS1): the S30 Pro's 8.3 MP frame holds 40 tiles at 512/32, the
# S50's 2.1 MP frame only 12 -- which matters because every deep group in the
# archive is an S50 one.
_S30_SHAPE = (3840, 2160)
_S50_SHAPE = (1920, 1080)


def _group(n_frames, slug_target="M16", sensor="s30", shape=_S30_SHAPE):
    frames = tuple(
        FrameInfo(f"/src/{slug_target}/f{i:04d}.fit", f"f{i:04d}.fit", slug_target,
                  slug_target, sensor, "S30 Pro", "", shape, "LP", 10.0,
                  "2026-08-09", f"2026-08-09T00:00:{i % 60:02d}", 275.1, -13.8, None)
        for i in range(n_frames)
    )
    return FrameGroup(sensor, slug_target, "LP", 10.0, "2026-08-09", frames)


def _stub_build(monkeypatch, tmp_path, group, *, pre_made=(), cfg=None, lines=None):
    """Run build_dataset against one group with the expensive parts faked.

    Returns (calls, manifest): `calls` is one entry per generate_training_pairs
    invocation, which is the thing under test -- each real one re-registers
    every frame in the group.
    """
    dataset_dir = tmp_path / "ds"
    monkeypatch.setattr(bd, "_DEFAULT_DATASET_ROOT", tmp_path)
    monkeypatch.setattr(bd, "discover_frame_groups", lambda *a, **k: [group])
    monkeypatch.setattr(
        bd, "_noise_record",
        lambda pair_dir, n_in, n_tgt, status: {
            "pair_dir": str(pair_dir), "status": status,
            "input_count": n_in, "target_count": n_tgt,
        },
    )

    def _write(n_in, n_tgt, pairs):
        for i in range(pairs):
            d = dataset_dir / group.slug / f"pair_{i:04d}_in{n_in}_target{n_tgt}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "manifest.json").write_text("{}\n")

    for n_in, n_tgt in pre_made:
        _write(n_in, n_tgt, 2)

    calls = []

    def fake_generate(source, output, *, config, **kwargs):
        calls.append(config)
        # The real generate_training_pairs announces each group it registers
        # through on_progress. The stub must too, or an assertion about what is
        # printed BEFORE building has nothing to sit in front of.
        kwargs["on_progress"](f"preparing 1/1 {group.slug} ({len(group.frames)} frames)")
        rungs = config.rungs or tuple(
            (n_in, config.target_count) for n_in in config.input_counts
        )
        for rung in rungs:
            n_in, n_tgt = rung[0], rung[1]
            _write(n_in, n_tgt,
                   rung[2] if len(rung) > 2 else config.pairs_per_group)
        return [{"group": group.slug, "pairs": []}]

    monkeypatch.setattr(bd, "generate_training_pairs", fake_generate)
    # deep_from=1 makes every rung "deep", i.e. the flat per-group count the
    # tests that predate the depth weighting were written against.
    full = {"name": "ds", "source": str(tmp_path / "src"), "sensor": "s30",
            "pairs_per_depth": 2, "method": "sigma_clip",
            "deep_from": 1, "pairs_deep": 2, "pairs_shallow": 2}
    full.update(cfg or {})
    manifest = bd.build_dataset(
        full,
        on_line=(lines.append if lines is not None else (lambda *a: None)),
    )
    return calls, manifest


def test_a_group_is_registered_once_however_many_target_depths_it_has(tmp_path, monkeypatch):
    """A 366-frame group's ladder has four distinct targets (256, 237, 109,
    64). Grouping the rungs by target and calling once per target meant four
    full re-registrations of the same 365 frames -- measured as four
    "preparing" lines for one group in a smoke build, and roughly two hours of
    duplicated work across the archive. PreparedStack exists precisely so the
    registration is reused."""
    group = _group(366)
    ladder = bd.plan_ladder(366, min_ratio=4.0, min_target=16, min_n2n_target=64)
    assert len({r.n_tgt for r in ladder}) > 1, "fixture must span several targets"

    calls, manifest = _stub_build(monkeypatch, tmp_path, group)

    assert len(calls) == 1, f"{len(calls)} registrations for one group"
    assert {(r[0], r[1]) for r in calls[0].rungs} == {(r.n_in, r.n_tgt) for r in ladder}
    assert manifest["summary"].get("pairs_failed", 0) == 0
    assert manifest["summary"]["pairs_generated"] == 2 * len(ladder)


def test_rungs_already_on_disk_are_not_rebuilt(tmp_path, monkeypatch):
    """Resumability survives the restructure: a rung whose pairs are already
    written is left out of the single call and reported as already_present,
    not regenerated and not counted as failed."""
    group = _group(366)
    ladder = bd.plan_ladder(366, min_ratio=4.0, min_target=16, min_n2n_target=64)
    done = (ladder[0].n_in, ladder[0].n_tgt)

    calls, manifest = _stub_build(monkeypatch, tmp_path, group, pre_made=[done])

    assert len(calls) == 1
    assert done not in {(r[0], r[1]) for r in calls[0].rungs}
    assert {(r[0], r[1]) for r in calls[0].rungs} == {(r.n_in, r.n_tgt) for r in ladder} - {done}
    assert manifest["summary"]["pairs_already_present"] == 2
    assert manifest["summary"]["pairs_generated"] == 2 * (len(ladder) - 1)
    assert manifest["summary"].get("pairs_failed", 0) == 0


# ------------------------------------------------- weighting the set by depth
#
# Measured on the finished n2n_v1 dataset (2026-08-24): 85% of its tiles had an
# input of fewer than 128 frames and about two thirds came from stacks of 32 or
# fewer, while the rungs matching how the user actually shoots (239/256/301/395)
# were 6.5% between them. Nobody chose that -- a flat pairs_per_depth did.
# Every group can afford the shallow rungs, so they get replicated once per
# group; only the biggest groups can afford the deep ones.

def _selected(manifest, group_slug):
    """{(n_in, n_tgt): pairs actually planned} for one group."""
    entry = next(g for g in manifest["groups"] if g["group"] == group_slug)
    out = {}
    for rec in entry["pairs"]:
        key = (rec["input_count"], rec["target_count"])
        out[key] = out.get(key, 0) + 1
    return out


def test_a_deep_rung_gets_more_pairs_than_a_shallow_one(tmp_path, monkeypatch):
    group = _group(366)
    _, manifest = _stub_build(
        monkeypatch, tmp_path, group,
        cfg={"deep_from": 128, "pairs_deep": 4, "pairs_shallow": 1,
             "shallow_depths": [1, 16, 64]},
    )
    got = _selected(manifest, group.slug)
    assert all(n == 4 for (n_in, _), n in got.items() if n_in >= 128), got
    assert all(n == 1 for (n_in, _), n in got.items() if n_in < 128), got
    assert manifest["summary"].get("pairs_failed", 0) == 0


def test_a_shallow_rung_outside_shallow_depths_is_never_built(tmp_path, monkeypatch):
    """The part that actually fixes the weighting. Keeping every power of two
    below 128 at one pair each still leaves shallow material at about a third
    of the set, because there are seven of them per group and three deep rungs.
    A rung that is not selected must not reach generate_training_pairs at all --
    not be built and then dropped."""
    group = _group(366)
    ladder = bd.plan_ladder(366, min_ratio=4.0, min_target=16, min_n2n_target=64)
    dropped = {r.n_in for r in ladder if r.n_in < 128} - {1, 16, 64}
    assert dropped, "fixture must have shallow rungs outside shallow_depths"

    calls, manifest = _stub_build(
        monkeypatch, tmp_path, group,
        cfg={"deep_from": 128, "pairs_deep": 4, "pairs_shallow": 1,
             "shallow_depths": [1, 16, 64]},
    )
    asked = {r[0] for r in calls[0].rungs}
    assert not (asked & dropped), f"built rungs it was told to skip: {asked & dropped}"
    assert {n_in for n_in, _ in _selected(manifest, group.slug)} & {1, 16, 64} == {1, 16, 64}
    assert manifest["summary"].get("pairs_failed", 0) == 0


def test_shallow_material_is_kept_but_not_weighted_towards(tmp_path, monkeypatch):
    """Andreas' ruling: focus on 128 and up, but still cater for the brand-new
    Seestar owner whose only stack is shallow. So shallow must be present and
    must be the minority -- an assertion on both sides, because dropping it
    entirely would satisfy a one-sided 'deep dominates' test."""
    group = _group(366)
    _, manifest = _stub_build(
        monkeypatch, tmp_path, group,
        cfg={"deep_from": 128, "pairs_deep": 4, "pairs_shallow": 1,
             "shallow_depths": [1, 16, 64]},
    )
    got = _selected(manifest, group.slug)
    shallow = sum(n for (n_in, _), n in got.items() if n_in < 128)
    deep = sum(n for (n_in, _), n in got.items() if n_in >= 128)
    assert shallow > 0, "a shallow stack must still be represented"
    assert deep > 2 * shallow, f"deep {deep} vs shallow {shallow}"


# ----------------------------------------------------- the tile-share estimate

def test_one_s50_pair_yields_far_fewer_tiles_than_one_s30_pair():
    """The trap in estimating with a single tiles-per-pair number: 29 was
    measured on n2n_v1, which is entirely S30 (3840x2160 -> 40 tiles). Every
    deep group in the archive is an S50 one at 1920x1080, which holds 12. Using
    29 for both would overstate the deep share by roughly three times."""
    s30 = bd._tiles_per_pair(_S30_SHAPE, 512, 32)
    s50 = bd._tiles_per_pair(_S50_SHAPE, 512, 32)
    assert 28 <= s30 <= 30, s30          # the measured 29.3 per pair
    assert s50 < s30 / 3.0, (s30, s50)


def test_the_tile_share_estimate_splits_deep_from_shallow():
    plans = [
        bd.GroupPlan(_group(366), [], [(Rung(1, 256, "truth"), 1),
                                       (Rung(128, 237, "n2n"), 4)]),
    ]
    rows = bd.tile_share_estimate(plans, deep_from=128, tile_size=512, tile_overlap=32)
    by_label = {r["depth"]: r for r in rows}
    assert by_label["1"]["pairs"] == 1 and not by_label["1"]["deep"]
    assert by_label["128-255"]["pairs"] == 4 and by_label["128-255"]["deep"]
    assert abs(sum(r["share"] for r in rows) - 1.0) < 1e-6
    assert abs(by_label["128-255"]["share"] - 0.8) < 1e-6


def test_the_estimate_is_printed_before_a_single_pair_is_built(tmp_path, monkeypatch):
    """It has to be visible up front, or the weighting is discovered after the
    hours are spent. Asserted on ordering, not just presence."""
    lines = []
    group = _group(366)
    calls, _ = _stub_build(
        monkeypatch, tmp_path, group, lines=lines,
        cfg={"deep_from": 128, "pairs_deep": 4, "pairs_shallow": 1,
             "shallow_depths": [1, 16, 64]},
    )
    text = [str(x) for x in lines]
    estimate_at = next(i for i, l in enumerate(text) if "tile-share estimate" in l)
    assert any("deep" in l and "%" in l for l in text[estimate_at:]), text
    built_at = next((i for i, l in enumerate(text) if "preparing" in l), len(text))
    assert estimate_at < built_at
    # and it describes the plan that was actually built
    deep_row = next(l for l in text[estimate_at:] if l.strip().startswith("deep"))
    assert "12" in deep_row, deep_row      # 3 deep rungs x 4 pairs


# ------------------------------------------------- which sensors get built

def _stub_multi(monkeypatch, tmp_path, groups, cfg):
    seen = {}

    def fake_discover(source, **kwargs):
        seen.update(kwargs)
        return list(groups)

    monkeypatch.setattr(bd, "_DEFAULT_DATASET_ROOT", tmp_path)
    monkeypatch.setattr(bd, "discover_frame_groups", fake_discover)
    monkeypatch.setattr(bd, "generate_training_pairs",
                        lambda *a, **k: [{"group": "x", "pairs": []}])
    monkeypatch.setattr(bd, "_noise_record",
                        lambda pair_dir, n_in, n_tgt, status: {})
    base = {"name": "ds", "source": str(tmp_path / "src"), "method": "average"}
    base.update(cfg)
    manifest = bd.build_dataset(base, on_line=lambda *a: None)
    built = {g["group"] for g in manifest["groups"] if "frame_count" in g}
    return seen, built


def test_a_sensors_list_widens_the_material_that_gets_built(tmp_path, monkeypatch):
    """n2n_v1 built 29% of the archive because `sensor` was one string used
    both to pick the material and to name the shipped model. The S50 groups
    are the deep ones -- M42 2361 frames, SH2-142 1357, NGC7023 821."""
    groups = [_group(366, "M16"), _group(400, "M42", sensor="s50", shape=_S50_SHAPE)]
    _, built = _stub_multi(monkeypatch, tmp_path, groups,
                           {"sensor": "s30", "sensors": ["s30", "s50"]})
    assert built == {groups[0].slug, groups[1].slug}


def test_without_a_sensors_list_the_single_sensor_key_still_selects(tmp_path, monkeypatch):
    """`sensor` alone must keep meaning what it meant, so re-running an old
    config does not silently start building a different archive."""
    groups = [_group(366, "M16"), _group(400, "M42", sensor="s50", shape=_S50_SHAPE)]
    _, built = _stub_multi(monkeypatch, tmp_path, groups, {"sensor": "s30"})
    assert built == {groups[0].slug}


def test_the_model_name_is_not_what_selects_the_material(tmp_path, monkeypatch):
    """The distinction the config has to carry: the model still ships as s30
    while learning from both cameras."""
    groups = [_group(400, "M42", sensor="s50", shape=_S50_SHAPE)]
    _, built = _stub_multi(monkeypatch, tmp_path, groups,
                           {"sensor": "s30", "sensors": ["s30", "s50"]})
    assert built == {groups[0].slug}


# ------------------------------------------------------------ the v2 config

def _config(name):
    import json
    import pathlib
    return json.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "configs" / name).read_text())


def test_n2n_v2_builds_both_sensors_but_still_ships_an_s30_model():
    """The distinction the whole config turns on. `sensors` is the material --
    widening it is the point -- while `sensor` names the file Nocturne ships
    (denoise_s30_v1); the S30 Pro is the camera the app targets."""
    cfg = _config("n2n_v2.json")
    assert cfg["sensors"] == ["s30", "s50"]
    assert cfg["sensor"] == "s30"


def test_n2n_v2_weights_the_set_towards_the_depths_the_user_shoots():
    cfg = _config("n2n_v2.json")
    assert cfg["deep_from"] == 128
    assert cfg["pairs_deep"] == 4
    assert cfg["pairs_shallow"] == 1
    assert cfg["shallow_depths"] == [1, 16, 64]


def test_n2n_v2_changes_only_the_data_selection_from_v1():
    """Two variables at once is how a training run stops being an experiment.
    v2 exists to test a different DATASET, so everything about the model and
    the run has to stay exactly where v1 left it."""
    v1, v2 = _config("n2n_v1.json"), _config("n2n_v2.json")
    unchanged = ("combine_nights", "min_ratio", "min_target", "min_n2n_target",
                 "method", "kappa", "tiles", "exclude_mosaics", "epochs",
                 "strength", "gate_tolerance", "source", "sensor")
    for key in unchanged:
        assert v2[key] == v1[key], f"{key}: {v1[key]!r} -> {v2[key]!r}"
    assert v2["name"] == "n2n_v2"


def test_n2n_v2_does_not_carry_the_superseded_flat_pair_count():
    """`pairs_per_depth` no longer reaches anything build_dataset emits -- every
    rung carries its own count. Leaving it in the config would read as though
    it still set the weighting."""
    assert "pairs_per_depth" not in _config("n2n_v2.json")


def test_a_groups_deepest_rung_survives_the_depth_weighting():
    """Thinning the shallow end must not gut the GATE.

    Neither held-out target is big enough for a 128-frame rung, so with
    shallow_depths=[1,16,64] alone NGC6888 (183 frames) loses 118->64 and
    NGC281 (109) loses both 44->64 and 32->76 — taking the deepest input the
    do-no-harm gate ever checks against real truth from 118 frames down to 64.
    A group's deepest affordable rung is the closest that group can get to a
    real user's stack, which is exactly what the gate needs to see.
    """
    from build_dataset import pairs_for_rung

    # 118 is not in shallow_depths and is below deep_from — dropped unless deepest
    assert pairs_for_rung(118, shallow_depths=[1, 16, 64]) == 0
    assert pairs_for_rung(118, shallow_depths=[1, 16, 64], is_deepest=True) == 1
    # a deep rung is unaffected by the flag
    assert pairs_for_rung(256, shallow_depths=[1, 16, 64], is_deepest=True) == \
           pairs_for_rung(256, shallow_depths=[1, 16, 64])


def test_the_real_held_out_targets_keep_a_deep_rung(capsys):
    """The two gate targets, at their real frame counts."""
    from build_dataset import pairs_for_rung, plan_ladder

    for n_frames in (183, 109):
        ladder = plan_ladder(n_frames)
        deepest = max(r.n_in for r in ladder)
        expect = deepest
        kept = [r.n_in for r in ladder
                if pairs_for_rung(r.n_in, shallow_depths=[1, 16, 64],
                                  is_deepest=(r.n_in == deepest)) > 0]
        assert expect in kept, f"{n_frames}-frame group lost its deepest rung {expect}"


def test_a_rung_survives_frames_that_fail_to_register():
    """Every n2n rung used to consume exactly ALL available frames — n_tgt =
    available - n_in — so one registration failure killed all of them.

    Real case, 2026-08-24: s50_M101 planned 64->149, 128->85 and 149->64 from
    214 frames (each summing to exactly 213), lost 2 frames to "List of matching
    triangles exhausted" on a star-poor galaxy field, and ALL NINE of its deep
    pairs failed. s50_M42's 512->1848 rung likewise uses all 2360 of its frames
    and survived only because none failed — after a two-hour registration.
    """
    LOST = 2  # what M101 actually lost
    for n_frames in (214, 366, 460, 821, 2361):
        registered = n_frames - LOST
        for r in plan_ladder(n_frames):
            assert r.n_in + r.n_tgt + 1 <= registered, (
                f"{n_frames}-frame group: {r} needs {r.n_in + r.n_tgt + 1} of "
                f"{registered} surviving frames — one registration failure kills it")


def test_the_reserve_scales_with_the_group():
    """Checked on n2n rungs only — truth rungs deliberately get no reserve, so
    that a 260-frame group still reaches a 256-frame target (Andreas, 2026-08-23).
    A percentage rounds to nothing on a small group, hence the floor."""
    for n_frames, least in ((109, 4), (2361, 70)):
        n2n = [r for r in plan_ladder(n_frames) if r.kind == "n2n"]
        assert n2n, f"{n_frames}-frame group produced no n2n rung"
        used = max(r.n_in + r.n_tgt for r in n2n)
        assert n_frames - 1 - used >= least, (
            f"{n_frames}-frame group left only {n_frames - 1 - used} frames of headroom")


def test_the_headroom_costs_little_depth():
    """The reserve must not quietly gut the deep end it exists to protect."""
    deepest = max(r.n_in for r in plan_ladder(460))
    assert deepest >= 380, f"M8's deepest input fell to {deepest}"
