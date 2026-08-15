import numpy as np

from nocturne.stacking.mosaic import combine_panels, match_offsets


def _layer(value, box):
    """A constant-valued layer covering `box` = (y0, y1, x0, x1) of a 40x40 canvas."""
    data = np.zeros((40, 40), np.float32)
    valid = np.zeros((40, 40), bool)
    y0, y1, x0, x1 = box
    data[y0:y1, x0:x1] = value
    valid[y0:y1, x0:x1] = True
    return data, valid


def test_offsets_are_measured_in_the_overlap_only():
    """Whole-frame statistics are wrong here: panels see different objects, so a
    panel containing a galaxy has a higher median for real reasons. Only the
    shared area compares like with like."""
    a, av = _layer(0.50, (0, 40, 0, 25))
    b, bv = _layer(0.65, (0, 40, 15, 40))     # 0.15 brighter, overlapping 15..25
    offsets = match_offsets([a, b], [av, bv])
    assert abs((offsets[1] - offsets[0]) - (-0.15)) < 1e-3


def test_a_panel_with_no_overlap_gets_no_offset():
    a, av = _layer(0.50, (0, 40, 0, 15))
    b, bv = _layer(0.65, (0, 40, 25, 40))     # disjoint
    offsets = match_offsets([a, b], [av, bv])
    assert offsets[0] == 0.0 and offsets[1] == 0.0


def test_combine_averages_the_overlap_and_keeps_the_wings():
    a, av = _layer(0.4, (0, 40, 0, 25))
    b, bv = _layer(0.8, (0, 40, 15, 40))
    master, coverage = combine_panels([a, b], [av, bv], [1.0, 1.0])
    assert master[0, 5] == np.float32(0.4)               # only panel a
    assert master[0, 35] == np.float32(0.8)              # only panel b
    assert abs(float(master[0, 20]) - 0.6) < 1e-6        # both, equally weighted
    assert coverage[0, 20] == 2 and coverage[0, 5] == 1


def test_weights_bias_the_average_toward_the_deeper_panel():
    """An overlap between a 48-sub panel and a 4-sub one should look mostly like
    the deep one."""
    a, av = _layer(0.4, (0, 40, 0, 25))
    b, bv = _layer(0.8, (0, 40, 15, 40))
    master, _cov = combine_panels([a, b], [av, bv], [3.0, 1.0])
    assert abs(float(master[0, 20]) - 0.5) < 1e-6        # (3*0.4 + 1*0.8)/4


def test_uncovered_canvas_is_zero_with_zero_coverage():
    a, av = _layer(0.4, (0, 10, 0, 10))
    master, coverage = combine_panels([a], [av], [1.0])
    assert master[30, 30] == 0.0
    assert coverage[30, 30] == 0


def test_offsets_are_applied_when_combining():
    """The two halves of the feature have to meet: a measured offset that is not
    applied leaves exactly the seam it was measured to remove."""
    a, av = _layer(0.50, (0, 40, 0, 25))
    b, bv = _layer(0.65, (0, 40, 15, 40))
    offsets = match_offsets([a, b], [av, bv])
    master, _cov = combine_panels([a, b], [av, bv], [1.0, 1.0], offsets)
    # panel b's exclusive area is pulled down to panel a's level
    assert abs(float(master[0, 35]) - 0.50) < 1e-3
    assert abs(float(master[0, 20]) - 0.50) < 1e-3       # and the overlap matches


def test_colour_layers_combine_per_channel():
    a = np.zeros((40, 40, 3), np.float32); a[..., 0] = 0.4
    b = np.zeros((40, 40, 3), np.float32); b[..., 0] = 0.8
    av = np.zeros((40, 40), bool); av[:, :25] = True
    bv = np.zeros((40, 40), bool); bv[:, 15:] = True
    master, coverage = combine_panels([a, b], [av, bv], [1.0, 1.0])
    assert master.shape == (40, 40, 3)
    assert abs(float(master[0, 20, 0]) - 0.6) < 1e-6
    assert coverage[0, 20] == 2


# --- feathering --------------------------------------------------------------

def test_feather_weight_is_zero_at_the_edge_and_full_inside():
    """A panel's contribution must fade in from its border, or every coverage
    boundary is a step. The Stage 1 mosaic showed exactly those steps."""
    from nocturne.stacking.mosaic import feather_weights

    valid = np.zeros((40, 40), bool)
    valid[10:30, 10:30] = True
    w = feather_weights(valid, width=5)

    assert w[valid].max() > 0.99
    assert w[10, 10] < 0.3                    # the corner of the valid region
    assert w[20, 20] > 0.99                   # deep inside
    assert w[~valid].max() == 0.0             # nothing outside


def test_feather_is_monotonic_from_the_edge_inward():
    from nocturne.stacking.mosaic import feather_weights

    valid = np.zeros((40, 40), bool)
    valid[10:30, 10:30] = True
    w = feather_weights(valid, width=5)
    ramp = [float(w[20, x]) for x in range(10, 21)]
    assert all(b >= a - 1e-6 for a, b in zip(ramp, ramp[1:])), ramp


def test_a_panel_narrower_than_the_feather_still_contributes():
    """A thin sliver of coverage must not be weighted to nothing — it is the
    only data in that part of the sky."""
    from nocturne.stacking.mosaic import feather_weights

    valid = np.zeros((40, 40), bool)
    valid[:, 18:22] = True                    # 4 px wide, feather asks for 10
    w = feather_weights(valid, width=10)
    assert w[valid].max() > 0.0


def test_feathering_removes_the_step_between_mismatched_panels():
    """The point of the whole exercise: two panels that disagree by a constant
    must join with a gradient rather than a cliff."""
    from nocturne.stacking.mosaic import combine_panels, feather_weights

    a, av = _layer(0.40, (0, 40, 0, 25))
    b, bv = _layer(0.60, (0, 40, 15, 40))
    hard, _c = combine_panels([a, b], [av, bv], [1.0, 1.0])
    soft, _c2 = combine_panels([a, b], [av, bv], [1.0, 1.0],
                               weights_map=[feather_weights(av, 8),
                                            feather_weights(bv, 8)])
    # the biggest single-pixel jump along a row across the seam
    hard_jump = float(np.abs(np.diff(hard[20, :])).max())
    soft_jump = float(np.abs(np.diff(soft[20, :])).max())
    assert soft_jump < hard_jump / 2, (soft_jump, hard_jump)


# --- global offset matching --------------------------------------------------

def test_offsets_use_every_overlap_not_just_the_first():
    """Three panels in a row, each 0.1 brighter than the last. Chaining against
    the FIRST overlapping neighbour propagates whatever error that one pair had;
    solving all overlaps together spreads the disagreement instead."""
    from nocturne.stacking.mosaic import match_offsets

    a, av = _layer(0.40, (0, 40, 0, 20))
    b, bv = _layer(0.50, (0, 40, 12, 30))
    c, cv = _layer(0.60, (0, 40, 22, 40))
    offsets = match_offsets([a, b, c], [av, bv, cv])

    levelled = [0.40 + offsets[0], 0.50 + offsets[1], 0.60 + offsets[2]]
    assert max(levelled) - min(levelled) < 1e-3, levelled


def test_a_disconnected_panel_keeps_its_own_level():
    """Nothing to match it to. Inventing an offset would move real signal."""
    from nocturne.stacking.mosaic import match_offsets

    a, av = _layer(0.40, (0, 40, 0, 15))
    b, bv = _layer(0.50, (0, 40, 10, 25))
    lone, lv = _layer(0.90, (0, 40, 32, 40))
    offsets = match_offsets([a, b, lone], [av, bv, lv])
    assert offsets[2] == 0.0
    assert abs((0.40 + offsets[0]) - (0.50 + offsets[1])) < 1e-3


def test_matching_is_anchored_so_the_picture_keeps_its_level():
    """Offsets are relative; without an anchor the whole mosaic could drift up
    or down as a group, changing the exposure of the finished picture."""
    from nocturne.stacking.mosaic import match_offsets

    a, av = _layer(0.40, (0, 40, 0, 25))
    b, bv = _layer(0.60, (0, 40, 15, 40))
    offsets = match_offsets([a, b], [av, bv])
    assert offsets[0] == 0.0, "the first panel is the reference"


def _ring():
    """Four panels in a ring, where panel A carries a gradient so its overlap
    with B implies a different offset than its overlap with D. The measurements
    cannot all be satisfied — which is the situation a real mosaic is always in,
    and the only one where solving all overlaps together beats chaining."""
    layers, valids = [], []
    specs = [(0.40, (0, 25, 0, 25)), (0.50, (0, 25, 15, 40)),
             (0.60, (15, 40, 15, 40)), (0.55, (15, 40, 0, 25))]
    for k, (val, (y0, y1, x0, x1)) in enumerate(specs):
        d = np.zeros((40, 40), np.float32)
        v = np.zeros((40, 40), bool)
        d[y0:y1, x0:x1] = val
        if k == 0:
            d[y0:y1, x0:x1] += np.linspace(0, 0.12, x1 - x0, dtype=np.float32)[None, :]
        v[y0:y1, x0:x1] = True
        layers.append(d)
        valids.append(v)
    return layers, valids


def _overlap_residuals(layers, valids, offsets):
    import itertools
    out = []
    for i, j in itertools.combinations(range(len(layers)), 2):
        both = valids[i] & valids[j]
        if both.sum() < 50:
            continue
        out.append(abs(float(np.median(layers[i][both] + offsets[i])
                             - np.median(layers[j][both] + offsets[j]))))
    return out


def test_inconsistent_overlaps_are_spread_not_dumped_on_one_seam():
    """Chaining against the first overlapping neighbour zeroes the seams it uses
    and dumps the entire disagreement on the ones it does not: measured on this
    ring, 0.0000 on four overlaps and 0.0375 on two. Solving every overlap
    together shares the error out, which is what stops one seam being visible."""
    from nocturne.stacking.mosaic import match_offsets

    layers, valids = _ring()
    residuals = _overlap_residuals(layers, valids, match_offsets(layers, valids))
    assert max(residuals) < 0.02, residuals


def test_matching_reports_progress():
    """After the last panel is placed there were several minutes of silence
    while every pair of panels was compared. A bar sitting at 100% with no
    explanation reads as a hang — the exact thing the stacker's phase numbering
    exists to prevent."""
    from nocturne.stacking.mosaic import match_offsets

    layers, valids = [], []
    for k in range(4):
        d = np.zeros((40, 40), np.float32)
        v = np.zeros((40, 40), bool)
        d[:, k * 8:k * 8 + 20] = 0.4 + k * 0.05
        v[:, k * 8:k * 8 + 20] = True
        layers.append(d)
        valids.append(v)

    seen = []
    match_offsets(layers, valids, on_progress=lambda i, n: seen.append((i, n)))
    assert seen, "no progress reported"
    assert seen[-1][0] == seen[-1][1] == 4


class _CountingMask(np.ndarray):
    """A bool array that records every full-array AND it takes part in."""
    calls = []

    def __and__(self, other):
        _CountingMask.calls.append(1)
        return np.ndarray.__and__(self, other)


def test_panels_that_cannot_overlap_are_not_compared_pixel_by_pixel():
    """561 pairs on a 28-megapixel canvas is minutes of work, and most pairs do
    not touch at all. A bounding-box test rejects those for the cost of four
    integers.

    The first version of this test patched np.bitwise_and and passed against the
    unoptimised code, because `a & b` calls ndarray.__and__ and never reaches
    the module function. It counts the operator now.
    """
    from nocturne.stacking.mosaic import match_offsets

    layers, valids = [], []
    for k in range(6):
        d = np.zeros((600, 600), np.float32)
        v = np.zeros((600, 600), bool).view(_CountingMask)
        x = k * 100
        d[:, x:x + 60] = 0.4
        v[:, x:x + 60] = True
        layers.append(d)
        valids.append(v)

    _CountingMask.calls = []
    match_offsets(layers, valids)
    # 15 pairs exist; only the 5 adjacent ones can share pixels
    assert len(_CountingMask.calls) <= 6, (
        f"{len(_CountingMask.calls)} full-canvas comparisons for 5 real overlaps")
