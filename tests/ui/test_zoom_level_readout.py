"""The zoom pill says what the zoom actually is.

Andreas, 2026-09-13: "I think it would be useful for the user if we actually
showed zoom level somewhere when the user is zoomed into an image." It lives in
the existing ZoomPill rather than a new element, and it is shown ALWAYS rather
than only while zoomed — a control that appears and disappears draws the eye at
exactly the moment you are trying to look at the picture.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QImage

from nocturne.ui.image_view import ImageView
from nocturne.ui.zoom_pill import ZoomPill


@pytest.fixture
def view(qtbot):
    v = ImageView()
    qtbot.addWidget(v)
    img = QImage(64, 64, QImage.Format.Format_RGB888)
    img.fill(0x404040)
    v.set_image(img)
    v.resize(200, 200)
    return v


@pytest.mark.parametrize("scale,expect", [
    (1.0, "100%"),
    (0.5, "50%"),
    (0.128, "13%"),        # rounds, does not truncate
    (0.125, "12%"),        # ties go to even, which is Python's default and
                           # invisible on a zoom readout — pinned, not chosen
    (2.0, "200%"),
    (8.0, "800%"),
    (11.87, "1190%"),      # past 10x, to the nearest 10
    (32.0, "3200%"),       # the _MAX_ZOOM ceiling still fits the fixed width
    (0.0, "0%"),
])
def test_the_percentage_reads_the_scale(qtbot, scale, expect):
    pill = ZoomPill(lambda: None, lambda: None, lambda: None)
    qtbot.addWidget(pill)
    pill.set_zoom(scale)
    assert pill.level.text() == expect


def test_a_negative_scale_cannot_be_reached_but_does_not_render_negative(qtbot):
    pill = ZoomPill(lambda: None, lambda: None, lambda: None)
    qtbot.addWidget(pill)
    pill.set_zoom(-3.0)
    assert pill.level.text() == "0%"


def test_zooming_the_view_updates_the_readout(qtbot, view):
    """Through the real view, not the pill's setter — the wiring is the part
    that can rot."""
    view.fit()
    before = view._zoom_pill.level.text()
    view.zoom_in()
    after = view._zoom_pill.level.text()
    assert after != before, "the readout did not follow the zoom"
    assert after.endswith("%")


def test_the_readout_is_not_subject_to_the_2_percent_gate(qtbot, view):
    """`_note_zoom` throttles overlay rebuilds at 2%, which is right for an
    overlay and wrong for a number: it would sit up to 2% stale, and at
    whole-percent precision that is visible."""
    view.fit()
    view._last_zoom = view.zoom()          # pretend the gate just fired
    view.scale(1.01, 1.01)                 # a sub-threshold change
    view._note_zoom()
    expected = f"{view.zoom() * 100:.0f}%"
    assert view._zoom_pill.level.text() == expected


def test_the_width_does_not_change_with_the_value(qtbot):
    """The pill sits on the canvas; a control that breathes as you zoom is its
    own distraction."""
    pill = ZoomPill(lambda: None, lambda: None, lambda: None)
    qtbot.addWidget(pill)
    pill.set_zoom(1.0)
    narrow = pill.level.sizeHint().width()
    pill.set_zoom(32.0)
    assert pill.level.sizeHint().width() == narrow


def test_the_stylesheet_uses_no_properties_qt_rejects():
    """Qt Style Sheets are a SUBSET of CSS, and an unsupported property is not
    an error — Qt prints "Unknown property x" to stderr, once per widget the
    sheet touches, and carries on.

    Andreas saw eleven of those on startup because `font-variant-numeric:
    tabular-nums` went into the zoom label: a web habit Qt does not implement.
    It was redundant anyway — the label's fixed width is what stops the pill
    jittering.

    A STATIC scan of the built sheet, not a runtime probe. The runtime version
    of this test was written first and was toothless: Qt emits the warning when
    it polishes a widget against a freshly parsed rule, and re-setting the
    sheet inside a test that already has one produced no warning at all. It
    passed with the bad property restored, which is the worst kind of guard.

    A blocklist rather than a whitelist, and deliberately so: enumerating
    everything Qt DOES support would break on the next legitimate property,
    while these are the CSS names most likely to be reached for out of habit.
    """
    import re
    from nocturne.ui import theme

    # CSS properties Qt Style Sheets do not implement. Each would be silently
    # ignored, with a line of stderr noise per styled widget.
    unsupported = {
        "font-variant-numeric", "font-variant", "font-feature-settings",
        "box-shadow", "text-shadow", "transition", "transform", "animation",
        "filter", "backdrop-filter", "flex", "flex-direction", "gap",
        "grid-template-columns", "align-items", "justify-content",
        "cursor", "overflow", "z-index", "content", "user-select",
        "pointer-events", "object-fit", "aspect-ratio",
    }
    sheet = theme.build_stylesheet()
    used = {m.lower() for m in re.findall(r"(?m)^\s*([a-z-]+)\s*:", sheet)}
    # ...and properties inside a one-line rule body, which is most of this sheet.
    used |= {m.lower() for m in re.findall(r"[{;]\s*([a-z-]+)\s*:", sheet)}

    bad = sorted(used & unsupported)
    assert not bad, (
        f"Qt Style Sheets do not implement {bad} — it will be ignored and print "
        f"'Unknown property' once per styled widget on startup")


def test_that_scan_can_actually_fail():
    """Proves the regex reaches into a rule body. The property that caused this
    sits mid-line in a single-line rule, which a line-anchored scan misses."""
    import re
    sheet = "QLabel#x {{ color: #888; font-size: 12px; font-variant-numeric: tabular-nums; }}"
    used = {m.lower() for m in re.findall(r"[{;]\s*([a-z-]+)\s*:", sheet)}
    assert "font-variant-numeric" in used
