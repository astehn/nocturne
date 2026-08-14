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
    panels = discover_panels(_two_pointings(), max_spread_deg=0.56)
    assert len(panels) == 2
    assert sorted(len(p.paths) for p in panels) == [5, 5]


def test_dithered_frames_of_one_pointing_stay_together():
    pointings = {f"s{i}.fit": (10.0 + i * 0.02, 41.0 + i * 0.02) for i in range(20)}
    panels = discover_panels(pointings, max_spread_deg=0.56)
    assert len(panels) == 1
    assert len(panels[0].paths) == 20


def test_grouping_is_independent_of_input_order():
    """A greedy centroid walks as it absorbs members, so the same subs cluster
    differently depending on arrival order — two spikes on the same 392 frames
    got 22 panels and 29. Single linkage has no such freedom, and a stacker
    whose panel count depends on filename order would be untestable.

    The fixture is a DRIFT CHAIN, spaced at 0.3 deg against a 0.56 deg spread
    limit, because that is the geometry which actually discriminates. Two
    pointings far apart cluster identically under any algorithm, so a fixture
    like that would let a greedy implementation pass this test — it did, when
    this test was first written.
    """
    pointings = {f"c{i}.fit": (10.0, 41.0 + i * 0.3) for i in range(6)}
    reference = discover_panels(pointings, max_spread_deg=0.56)
    assert len(reference) == 3, "a 1.5 deg chain cannot be one 0.56 deg panel"
    for seed in range(8):
        items = list(pointings.items())
        random.Random(seed).shuffle(items)
        assert discover_panels(dict(items), max_spread_deg=0.56) == reference

    # and the same for two chains that must stay apart
    two = dict(pointings)
    two.update({f"d{i}.fit": (10.0, 45.0 + i * 0.3) for i in range(6)})
    ref2 = discover_panels(two, max_spread_deg=0.56)
    assert len(ref2) == 6, "three panels per chain, and the chains stay apart"
    for seed in range(8):
        items = list(two.items())
        random.Random(seed).shuffle(items)
        assert discover_panels(dict(items), max_spread_deg=0.56) == ref2


def test_a_chain_does_not_bridge_into_one_panel():
    """THE test this module exists for, and the assertion was the other way
    round until the real data spoke.

    Under single linkage A-B and B-C merge whenever each hop is short enough,
    even though A and C are 0.8 deg apart — and on the real 392-sub M 31 set
    that chaining swallowed 390 frames into a single "panel". Complete linkage
    bounds the whole group's spread, so a bridge that would exceed the limit is
    refused however short each individual hop is.
    """
    pointings = {"a.fit": (10.0, 41.0), "b.fit": (10.0, 41.4), "c.fit": (10.0, 41.8)}
    panels = discover_panels(pointings, max_spread_deg=0.56)
    assert len(panels) == 2, "0.8 deg end to end cannot be one 0.56 deg panel"
    assert {len(p.paths) for p in panels} == {1, 2}


def test_a_grid_of_dithered_panels_survives_clustering():
    """The situation that actually broke: a dense grid where every panel
    overlaps its neighbours. Nine pointings 0.73 deg apart — the real M 31
    spacing — each dithered over 0.3 deg, which is the measured dither extent.
    Single linkage merged the lot; the count must come back as nine."""
    pointings = {}
    for gy in range(3):
        for gx in range(3):
            for k in range(4):
                pointings[f"p{gy}{gx}_{k}.fit"] = (10.0 + gx * 0.73 + k * 0.1,
                                                   41.0 + gy * 0.73 + k * 0.1)
    panels = discover_panels(pointings, max_spread_deg=0.56)
    assert len(panels) == 9, [len(p.paths) for p in panels]
    assert all(len(p.paths) == 4 for p in panels)


def test_ra_separation_accounts_for_declination():
    """One degree of RA is much less than one degree on the sky at Dec 60."""
    pointings = {"a.fit": (10.0, 60.0), "b.fit": (11.0, 60.0)}   # 0.5 deg apart on sky
    assert len(discover_panels(pointings, max_spread_deg=0.56)) == 1
