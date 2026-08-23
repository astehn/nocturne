from build_dataset import Rung, plan_ladder


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
