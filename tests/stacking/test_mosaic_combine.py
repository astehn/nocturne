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
