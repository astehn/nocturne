from build_dataset import plan_ladder


def test_ladder_reserves_frames_and_records_ratio():
    """input + target + 1 reference must fit, and the target must be
    meaningfully deeper or the pair teaches nothing."""
    got = plan_ladder(n_frames=366, depths=[1, 2, 4, 8, 16, 32, 64, 128], min_ratio=4.0)
    for n_in, n_tgt in got:
        assert n_in + n_tgt + 1 <= 366
        assert n_tgt >= n_in * 4.0
    assert (1, 128) in got and (32, 128) in got
    assert not any(n_in >= 64 for n_in, _ in got)   # 64*4=256, +64+1 > 366


def test_small_group_falls_back_to_the_deepest_affordable_target():
    got = plan_ladder(n_frames=109, depths=[1, 2, 4, 8, 16, 32], min_ratio=4.0)
    assert got, "a 109-frame group must still yield shallow pairs"
    for n_in, n_tgt in got:
        assert n_in + n_tgt + 1 <= 109


def test_a_group_too_small_for_any_valid_pair_yields_nothing():
    assert plan_ladder(n_frames=6, depths=[1, 2, 4, 8], min_ratio=4.0) == []


def test_min_target_rejects_a_shallow_target_even_if_the_ratio_passes():
    """The brief's reference implementation returns [(1, 4)] here because a
    4-frame target clears min_ratio=4.0 against a 1-frame input -- but a
    4-frame stack is still mostly noise. min_target=16 is the ruling that
    overrides the ratio check: this is the same case as the "yields nothing"
    test above, asserted directly against the min_target knob so a future
    change to the default can't silently reopen the bug.
    """
    assert plan_ladder(n_frames=6, depths=[1, 2, 4, 8], min_ratio=4.0, min_target=16) == []
    # With the guard relaxed, the too-shallow pair reappears -- proving the
    # first assertion is actually exercising min_target, not min_ratio.
    assert (1, 4) in plan_ladder(n_frames=6, depths=[1, 2, 4, 8], min_ratio=4.0, min_target=1)
