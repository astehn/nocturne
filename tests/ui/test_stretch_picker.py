"""The visual stretch picker: six real previews of the user's own image.

Why it exists is in the spec. The short version: ladders of four of Andreas's
masters wanted 0.10, 0.10, 0.10 and 0.20-0.30, so one default cannot serve them
all and the choice has to be made by eye, on the image in hand.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.stretch_picker import STRETCH_PICKS, Pick, StretchPickerDialog


def _linear():
    rng = np.random.default_rng(0)
    return AstroImage(
        np.clip(rng.normal(0.02, 0.005, (200, 160, 3)), 0, 1).astype(np.float32),
        is_linear=True)


def test_the_six_values_are_the_ones_he_picked_from():
    """Pinned as EVIDENCE. Andreas judged all four of his targets from an even
    ladder over this range; an edit that drifts these should have to come back
    and disagree with that."""
    assert [v for _n, v in STRETCH_PICKS] == [0.00, 0.12, 0.24, 0.36, 0.48, 0.60]
    assert len(STRETCH_PICKS) == 6


def test_the_names_describe_the_result_not_the_subject():
    """The Target dropdown died on 2026-09-13 because Auto/Nebula/Galaxy/Cluster
    claimed to know the subject. These describe the picture in front of you,
    which is the difference that makes naming safe here."""
    names = " ".join(n.lower() for n, _v in STRETCH_PICKS)
    for banned in ("nebula", "galaxy", "cluster", "auto"):
        assert banned not in names


def test_choosing_a_panel_produces_a_dict_not_a_float(qtbot):
    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    d.choose(1)
    assert d.result_option() == {"amount": STRETCH_PICKS[1][1]}


def test_nothing_chosen_yields_nothing(qtbot):
    """Cancel has to be distinguishable from picking the first panel."""
    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    assert d.result_option() is None


def test_every_panel_renders_a_different_picture(qtbot):
    """A grid of six identical thumbnails would look like it worked."""
    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    means = [float(np.asarray(img.data).mean()) for _n, _v, img in d.panels()]
    assert len(set(round(m, 4) for m in means)) == len(means), means
    assert means == sorted(means), "brighter settings must give brighter panels"


def test_previews_are_downscaled_not_full_size(qtbot):
    """Six full-resolution stretches of a 40 Mpx master took about 30 s when
    measured; at preview size the same work is well under a second, which is why
    there is no progress UI here.

    `preview.downscale` shrinks by an INTEGER block factor, so it targets 640 px
    rather than capping at it — a 4000 px edge becomes 666, not 640. Asserting
    `<= 640` would be asserting a contract it does not make. What matters is
    that the panels are preview-sized, so that is what is checked.
    """
    big = AstroImage(np.full((4000, 3000, 3), 0.02, np.float32), is_linear=True)
    d = StretchPickerDialog(big)
    qtbot.addWidget(d)
    for _n, _v, img in d.panels():
        longest = max(img.data.shape[:2])
        assert longest < 4000 / 4, f"barely shrunk: {longest}"
        assert longest <= 640 * 2, f"far larger than the 640 target: {longest}"


def test_a_pick_receives_the_answers_so_far(qtbot):
    """THE architectural guard.

    Linked-vs-unlinked is expected to be prepended, and a linked and an unlinked
    stretch give different pictures at the SAME brightness — which is why
    AstroWizard renders its depth grid only after the colour pick is answered.
    If options() stops taking state, prepending becomes a rewrite, and nothing
    else in the suite would notice.
    """
    seen = {}
    first = Pick(title="first", key="mode",
                 options=lambda state: [("a", 0.0, _linear())])
    second = Pick(title="second", key="amount",
                  options=lambda state: (seen.update(state),
                                         [("b", 0.5, _linear())])[1])
    d = StretchPickerDialog(_linear(), picks=[first, second])
    qtbot.addWidget(d)
    d.choose(0)
    assert seen == {"mode": 0.0}, "the second pick never saw the first's answer"


# --- fitting on screen ---------------------------------------------------
# Six 640 px panels in a 3x2 grid is a 1984x1527 window. It shipped that way for
# one afternoon and did not fit a 2560x1440 monitor: the bottom row ran off the
# screen edge and Cancel was below it, unreachable. Anything that grows the
# dialog has to shrink the previews instead of the window.

_SCREENS = [
    ("MacBook Air floor", 1280, 800),      # the size floor this app targets
    ("MacBook Pro 14", 1512, 982),
    ("27 inch", 2560, 1440),               # the monitor it overflowed on
    ("5K", 5120, 2880),
]


@pytest.mark.parametrize("label,width,height", _SCREENS)
def test_the_grid_fits_the_screen_it_opens_on(qtbot, label, width, height):
    from PySide6.QtCore import QSize
    from nocturne.ui.stretch_picker import preview_edge, _COLUMNS

    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    chrome = d._chrome(2)
    available = QSize(int(width * 0.9), int(height * 0.9))
    edge = preview_edge(available, chrome, 2)

    assert chrome.width() + _COLUMNS * edge <= available.width(), label
    assert chrome.height() + 2 * edge <= available.height(), label


def test_the_dialog_fits_the_screen_it_is_actually_on(qtbot):
    """The whole point, asserted on the real widget rather than the arithmetic.

    `_chrome` is measured from live size hints, so this also catches a new row
    of text that the pure-function test above would happily size around.
    """
    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    available = d._available()
    # size(), not sizeHint(): the grid lives in a QScrollArea, whose hint does
    # not grow with its contents, so sizeHint() would pass no matter how far the
    # window overflowed. That version of this test survived the mutation.
    assert d.size().width() <= available.width()
    assert d.size().height() <= available.height()


def test_previews_never_shrink_below_judging_size(qtbot):
    """A screen too small for six panels scrolls; it does not serve previews so
    small that faint nebulosity — the thing being judged — is invisible."""
    from PySide6.QtCore import QSize
    from nocturne.ui.stretch_picker import preview_edge, _PREVIEW_MIN

    assert preview_edge(QSize(320, 240), QSize(64, 247), 2) == _PREVIEW_MIN
