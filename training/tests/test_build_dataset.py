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
    assert deepest >= 390, f"deepest n2n input was only {deepest}"


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


def _group(n_frames, slug_target="M16"):
    frames = tuple(
        FrameInfo(f"/src/{slug_target}/f{i:04d}.fit", f"f{i:04d}.fit", slug_target,
                  slug_target, "s30", "S30 Pro", "", (2160, 3840), "LP", 10.0,
                  "2026-08-09", f"2026-08-09T00:00:{i % 60:02d}", 275.1, -13.8, None)
        for i in range(n_frames)
    )
    return FrameGroup("s30", slug_target, "LP", 10.0, "2026-08-09", frames)


def _stub_build(monkeypatch, tmp_path, group, *, pre_made=()):
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
        rungs = config.rungs or tuple(
            (n_in, config.target_count) for n_in in config.input_counts
        )
        for n_in, n_tgt in rungs:
            _write(n_in, n_tgt, config.pairs_per_group)
        return [{"group": group.slug, "pairs": []}]

    monkeypatch.setattr(bd, "generate_training_pairs", fake_generate)
    manifest = bd.build_dataset(
        {"name": "ds", "source": str(tmp_path / "src"), "sensor": "s30",
         "pairs_per_depth": 2, "method": "sigma_clip"},
        on_line=lambda *a: None,
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
    assert set(calls[0].rungs) == {(r.n_in, r.n_tgt) for r in ladder}
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
    assert done not in set(calls[0].rungs)
    assert set(calls[0].rungs) == {(r.n_in, r.n_tgt) for r in ladder} - {done}
    assert manifest["summary"]["pairs_already_present"] == 2
    assert manifest["summary"]["pairs_generated"] == 2 * (len(ladder) - 1)
    assert manifest["summary"].get("pairs_failed", 0) == 0
