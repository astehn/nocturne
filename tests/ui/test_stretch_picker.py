"""The visual stretch picker: six real previews of the user's own image.

Why it exists is in the spec. The short version: ladders of four of Andreas's
masters wanted 0.10, 0.10, 0.10 and 0.20-0.30, so one default cannot serve them
all and the choice has to be made by eye, on the image in hand.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.stretch_picker import (
    STRETCH_PICKS, Pick, StretchPickerDialog, _sky, brightness_pick,
    colour_pick,
)


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

# AVAILABLE geometry, not panel size: macOS excludes the menu bar, so the 2560
# x1440 monitor this overflowed on reports 1410 of usable height. Sizing against
# the raw panel number was part of how the first fix still overflowed -- the
# table said 1295 <= 1296 and the real ceiling was 1269.
_SCREENS = [
    ("MacBook Air floor", 1280, 775),      # the size floor this app targets
    ("MacBook Pro 14", 1512, 957),
    ("27 inch", 2560, 1410),               # the monitor it overflowed on
    ("5K", 5120, 2855),
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


def test_the_picture_is_the_button(qtbot):
    """No "Use this one" under each preview: you click the picture.

    A button per panel is a row of chrome per row of previews, and it was what
    tipped the grid off the bottom of a 1440 px screen even after the fit went
    in. AstroWizard has no such button either.
    """
    from PySide6.QtWidgets import QPushButton

    d = StretchPickerDialog(_linear())
    qtbot.addWidget(d)
    labels = [b.text() for b in d.findChildren(QPushButton) if b.text()]
    assert labels == ["Cancel"], labels

    clickable = d.findChildren(QPushButton, "pickPanel")
    assert len(clickable) == len(STRETCH_PICKS)
    clickable[2].click()
    assert d.result_option() == {"amount": STRETCH_PICKS[2][1]}


def test_the_fit_survives_the_real_stylesheet(qtbot):
    """The rendered grid must fit WITHOUT a scrollbar, on the real stylesheet.

    Asserted against the laid-out widgets rather than against `_chrome()`. The
    first version of this test compared the dialog size to `_chrome()`-derived
    numbers and passed happily with the bug restored: the fit is COMPUTED from
    `_chrome()`, so checking it with `_chrome()` is self-consistent no matter
    how wrong that measurement is. The viewport is an independent witness.

    Run under the real stylesheet because the themed #stageTitle is 20px + 8px
    padding against an unstyled 16px, and every size in the fit depends on it.
    """
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import apply_dark_theme

    app = QApplication.instance()
    previous = app.styleSheet()
    try:
        apply_dark_theme(app)
        d = StretchPickerDialog(_linear())
        qtbot.addWidget(d)
        d.show()
        qtbot.waitExposed(d)
        assert d._title.sizeHint().height() > 16, "stylesheet did not take"

        needed = d._grid_host.sizeHint()
        viewport = d._scroll.viewport().size()
        assert needed.height() <= viewport.height(), (
            f"grid needs {needed.height()}px in a {viewport.height()}px "
            "viewport - the previews were sized against undercounted chrome")
        assert needed.width() <= viewport.width()

        available = d._available()
        assert d.size().width() <= available.width()
        assert d.size().height() <= available.height()
    finally:
        app.setStyleSheet(previous)


# --- pick 1 of 2: the colour ---------------------------------------------
# AstroWizard asks colour BEFORE depth, renders both equally bright on purpose,
# and says "ignore brightness - depth is the next pick". One variable per
# question is the good idea worth copying; Andreas chose unlinked by eye twice.

def _wide_red_linear():
    """Red given the wider spread, as on the real data (R/G MAD 2.67 on
    IC 1396A). Channels that commute cannot tell the two stretches apart."""
    rng = np.random.default_rng(3)
    d = np.clip(rng.normal(0.02, 0.005, (200, 160, 3)), 0, 1).astype(np.float32)
    d[..., 0] = np.clip(0.02 + (d[..., 0] - 0.02) * 2.67, 0, 1)
    return AstroImage(d, is_linear=True)


def test_the_colour_pick_offers_exactly_two_named_coldly():
    """Cold naming on purpose: "Unlinked" describes the mechanism and stays true
    on every image, where "Warmer sky" is a claim that will be wrong on some
    other one. Neither may be labelled correct — the measurement that would
    justify that is still unresolved."""
    opts = colour_pick(_wide_red_linear()).options({})
    assert [n for n, _v, _i in opts] == ["Linked", "Unlinked"]
    assert [v for _n, v, _i in opts] == [True, False]


def test_neither_colour_panel_claims_to_be_the_correct_one():
    p = colour_pick(_wide_red_linear())
    text = " ".join(p.caption(n, v, i) for n, v, i in p.options({})).lower()
    for banned in ("true", "faithful", "correct", "photometric", "accurate"):
        assert banned not in text, banned


def test_both_colour_panels_render_at_the_same_brightness():
    """The pick is one-variable BY CONSTRUCTION — both stretches take the same
    target. Which is exactly why it needs a test: nothing else would notice if
    one of them stopped honouring it, and the whole decomposition would quietly
    become two variables at once."""
    skies = [_sky(i) for _n, _v, i in colour_pick(_wide_red_linear()).options({})]
    assert abs(skies[0] - skies[1]) < 0.02, skies


def test_the_two_colour_panels_are_different_pictures():
    opts = colour_pick(_wide_red_linear()).options({})
    assert not np.allclose(opts[0][2].data, opts[1][2].data)


def test_the_brightness_panels_honour_the_colour_choice():
    """The guard on options(state) being USED rather than merely accepted. This
    is the property the whole pick-sequence architecture exists for."""
    from nocturne.core.stretch import apply_stretch
    from nocturne.ui.preview import downscale

    base = _wide_red_linear()
    _name, amount, img = brightness_pick(base).options({"linked": False})[2]
    expected = apply_stretch(downscale(base, 640), amount, linked=False)
    assert np.array_equal(img.data, expected.data)


def test_the_brightness_panels_default_to_linked():
    from nocturne.core.stretch import apply_stretch
    from nocturne.ui.preview import downscale

    base = _wide_red_linear()
    _n, amount, img = brightness_pick(base).options({})[2]
    assert np.array_equal(img.data,
                          apply_stretch(downscale(base, 640), amount, linked=True).data)


def test_the_spcc_caveat_appears_only_when_spcc_ran():
    """An unlinked stretch annihilates a photometric calibration — measured at
    0.0004 of an 8-bit level, i.e. not at all. Saying so unconditionally would
    warn the many people who never ran it."""
    assert colour_pick(_wide_red_linear()).caveats == {}
    warned = colour_pick(_wide_red_linear(), spcc_applied=True).caveats
    assert list(warned) == [False]                       # only under Unlinked
    assert "calibration" in warned[False].lower()


def test_a_two_pick_sequence_accumulates_in_order(qtbot):
    base = _wide_red_linear()
    d = StretchPickerDialog(base, picks=[colour_pick(base), brightness_pick(base)])
    qtbot.addWidget(d)
    d.choose(1)                                  # Unlinked
    assert d.result_option() is None             # not finished: one pick left
    d.choose(2)                                  # Balanced
    assert d.result_option() == {"linked": False, "amount": 0.24}


def test_a_two_panel_pick_still_fits_the_screen(qtbot):
    """The colour pick is a 2-panel grid, not the 6-panel one the fitting maths
    was written and checked against on 2026-09-14."""
    base = _wide_red_linear()
    d = StretchPickerDialog(base, picks=[colour_pick(base), brightness_pick(base)])
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    assert d._grid_host.sizeHint().height() <= d._scroll.viewport().height()
    assert d.size().height() <= d._available().height()
