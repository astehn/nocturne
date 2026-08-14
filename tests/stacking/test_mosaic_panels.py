import random

from nocturne.stacking.mosaic import discover_panels


def _two_pointings():
    """Two pointings 1.5 deg apart in Dec, five dithered frames each."""
    out = {}
    for i in range(5):
        out[f"a{i}.fit"] = (10.0 + i * 0.01, 41.0 + i * 0.01)
        out[f"b{i}.fit"] = (10.0 + i * 0.01, 42.5 + i * 0.01)
    return out


def test_separate_pointings_become_separate_panels():
    panels = discover_panels(_two_pointings(), radius_deg=0.56)
    assert len(panels) == 2
    assert sorted(len(p.paths) for p in panels) == [5, 5]


def test_dithered_frames_of_one_pointing_stay_together():
    pointings = {f"s{i}.fit": (10.0 + i * 0.02, 41.0 + i * 0.02) for i in range(20)}
    panels = discover_panels(pointings, radius_deg=0.56)
    assert len(panels) == 1
    assert len(panels[0].paths) == 20


def test_grouping_is_independent_of_input_order():
    """A greedy centroid walks as it absorbs members, so the same subs cluster
    differently depending on arrival order — two spikes on the same 392 frames
    got 22 panels and 29. Single linkage has no such freedom, and a stacker
    whose panel count depends on filename order would be untestable.

    The fixture is a DRIFT CHAIN, spaced at 0.3 deg against a 0.56 deg radius,
    because that is the geometry which actually discriminates. Two pointings far
    apart cluster identically under either algorithm, so a fixture like that
    would let a greedy implementation pass this test — it did, when this test
    was first written, and only the chain test below caught the mutant.
    """
    pointings = {f"c{i}.fit": (10.0, 41.0 + i * 0.3) for i in range(6)}
    reference = discover_panels(pointings, radius_deg=0.56)
    assert len(reference) == 1, "single linkage joins the whole chain"
    for seed in range(8):
        items = list(pointings.items())
        random.Random(seed).shuffle(items)
        assert discover_panels(dict(items), radius_deg=0.56) == reference

    # and the same for two chains that must stay apart
    two = dict(pointings)
    two.update({f"d{i}.fit": (10.0, 45.0 + i * 0.3) for i in range(6)})
    ref2 = discover_panels(two, radius_deg=0.56)
    assert len(ref2) == 2
    for seed in range(8):
        items = list(two.items())
        random.Random(seed).shuffle(items)
        assert discover_panels(dict(items), radius_deg=0.56) == ref2


def test_chain_of_overlapping_frames_is_one_panel():
    """Single linkage joins A-B and B-C into one group even though A and C are
    further apart than the radius. That is correct: they are one continuous
    pointing drift, not two panels."""
    pointings = {"a.fit": (10.0, 41.0), "b.fit": (10.0, 41.4), "c.fit": (10.0, 41.8)}
    panels = discover_panels(pointings, radius_deg=0.56)
    assert len(panels) == 1


def test_ra_separation_accounts_for_declination():
    """One degree of RA is much less than one degree on the sky at Dec 60."""
    pointings = {"a.fit": (10.0, 60.0), "b.fit": (11.0, 60.0)}   # 0.5 deg apart on sky
    assert len(discover_panels(pointings, radius_deg=0.56)) == 1
