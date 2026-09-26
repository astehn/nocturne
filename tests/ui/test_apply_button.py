import pytest
from PySide6.QtWidgets import QWidget, QVBoxLayout

from nocturne.ui.apply_button import STATES, ApplyButton


def _btn(qtbot, label="Apply Levels", width=380):
    host = QWidget(); lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)  # so `width=` is the BUTTON's width,
    # not the host's minus the layout's default ~11px-per-side margin — a
    # label-fits regression test needs an exact button width.
    b = ApplyButton(label)
    lay.addWidget(b)
    qtbot.addWidget(host)
    host.resize(width, 200); host.show(); qtbot.waitExposed(host)
    # qtbot.addWidget() only keeps a weakref (for teardown), and `host` has no
    # C++ parent of its own, so Python owns it — without another strong
    # reference, host is garbage-collected the moment this helper returns,
    # which deletes its child `b` at the C++ level too ("libshiboken: Internal
    # C++ object already deleted" on the very next call). Tie host's lifetime
    # to the button we actually return.
    b._host = host
    return b


def test_the_height_never_changes_with_state(qtbot):
    b = _btn(qtbot)
    heights = set()
    for s in STATES:
        b.set_state(s); qtbot.wait(5)
        heights.add(b.height())
    assert len(heights) == 1


@pytest.mark.parametrize("state,green,enabled,words", [
    ("pending", True, True, "not applied"),
    ("not_run", True, True, "not run"),
    ("applied", False, True, "applied"),    # live unless verified unchanged (R13)
    ("no_change", False, False, "no changes"),
    ("busy", False, False, ""),
])
def test_each_state_reads_and_colours_as_ruled(qtbot, state, green, enabled, words):
    b = _btn(qtbot)
    b.set_state(state)
    assert b.state() == state
    assert b.property("pending") == ("true" if green else "false")
    assert b.isEnabled() is enabled
    assert words in b.status_text()
    assert b.label_text() == "Apply Levels"


@pytest.mark.parametrize("label", ["Apply Deconvolution", "Apply De-green Stars", "Apply Linear Denoise"])
def test_long_names_fit_the_button(qtbot, label):
    """Smoke check at a fixed width, unstyled. The real-width check under the
    real stylesheet is test_stable_frame's test_every_apply_label_fits_beside_reset."""
    from PySide6.QtGui import QFontMetrics
    b = _btn(qtbot, label=label, width=380)
    b.set_state("pending")
    bold, _ = b._fonts()
    assert QFontMetrics(bold).horizontalAdvance(b.label_text()) <= b.width(), (
        f"{label!r} is clipped at 380 px")


def test_applied_and_verified_unchanged_is_off_plain_and_says_applied(qtbot):
    """Andreas, 2026-09-25 23:27: an applied step whose controls ARE the commit
    cannot be pressed again. Only the caller's verification switches it off."""
    b = _btn(qtbot)
    b.set_state("applied", unchanged=True)
    assert b.state() == "applied" and not b.isEnabled()
    assert b.property("pending") == "false"
    assert "applied" in b.status_text()
    b.set_state("applied")
    assert b.isEnabled(), "an unverified applied must stay live"


def test_unchanged_qualifies_only_applied(qtbot):
    with pytest.raises(ValueError):
        _btn(qtbot).set_state("pending", unchanged=True)


def test_unchanged_never_overrides_tool_availability(qtbot):
    b = _btn(qtbot)
    b.setEnabled(False)                     # the tool is missing
    b.set_state("applied")
    assert not b.isEnabled()


def _status_ink(b):
    """The darkest-vs-body pixel of the status line, i.e. its text colour."""
    from PySide6.QtGui import QColor
    img = b.grab().toImage()
    fm_h = b.fontMetrics().height()
    top = 5 + fm_h + 2
    body = img.pixelColor(3, top + 2)
    best, dist = body, -1
    for x in range(0, img.width()):
        for y in range(top, img.height() - 2):
            px = img.pixelColor(x, y)
            d = sum((a - c) ** 2 for a, c in zip(px.getRgb()[:3], body.getRgb()[:3]))
            if d > dist:
                best, dist = px, d
    return QColor(best)


def test_disabled_applied_is_dim_not_green(qtbot):
    """Spec §4: applied-and-off is "plain, dim". SUCCESS green on a button you
    cannot press reads as "press me"."""
    from PySide6.QtGui import QColor
    from nocturne.ui.theme import SUCCESS
    b = _btn(qtbot)
    b.set_state("applied")
    live = _status_ink(b)
    b.set_state("applied", unchanged=True)
    off = _status_ink(b)
    green = QColor(SUCCESS)

    def dist(c):
        return sum((a - x) ** 2 for a, x in zip(c.getRgb()[:3], green.getRgb()[:3]))
    assert dist(live) < dist(off), (live.name(), off.name())
    assert off.green() <= off.red() + 40, f"disabled status still green: {off.name()}"


def test_unknown_state_is_refused(qtbot):
    with pytest.raises(ValueError):
        _btn(qtbot).set_state("maybe")


# --- controller review findings, 2026-09-25 -----------------------------

def _relative_luminance(color) -> float:
    def lin(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(color.red()) + 0.7152 * lin(color.green()) + 0.0722 * lin(color.blue())


def _contrast_ratio(c1, c2) -> float:
    """WCAG 2.x contrast ratio from two QColor, honest because both colours
    come from ACTUAL PAINTED PIXELS in the tests below, not from this
    module's own colour constants — a paintEvent bug that forgot to fill or
    draw would still be caught, which reading theme.py's own tokens could
    not do."""
    l1, l2 = sorted((_relative_luminance(c1), _relative_luminance(c2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_height_matches_a_live_recompute_after_show(qtbot):
    """Review Focus 3: the fixed height used to be computed once in
    __init__, before the widget had ever been polished under the real app
    stylesheet (45px measured there; 47px true) — and nothing re-triggered
    it afterwards, so a real shown button stayed 2px short of what its OWN
    _fit_height() computes once genuinely live and styled.
    """
    import nocturne.ui.theme as theme
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        b = _btn(qtbot)
        shown_height = b.height()
        b._fit_height()  # a fresh, live recompute — the ground truth
        assert b.height() == shown_height, (
            f"shown height {shown_height} != live recompute {b.height()}")
    finally:
        app.setStyleSheet("")


@pytest.mark.parametrize("before", ["pending", "not_run", "applied", "no_change"])
def test_busy_keeps_the_previous_words(qtbot, before):
    """Spec §4: busy is 'disabled, unchanged text'. A pending edit must still
    say 'not applied' while an unrelated operation runs, and come back as it
    was."""
    b = _btn(qtbot)
    b.set_state(before)
    words = b.status_text()
    b.set_state("busy")
    assert b.state() == "busy" and not b.isEnabled()
    assert b.status_text() == words
    b.set_state(before)
    assert b.status_text() == words


# --- D1 (Andreas, 2026-09-26): the status was unreadable at any size --------

def test_status_is_drawn_at_the_step_descriptions_size(qtbot):
    """His real window: the status (button font -2 pt, floored at 8 pt) read
    as ~7 px of ink. It is now the size of the description under the step
    title, read from the live stylesheet — so a stylesheet that changes that
    size changes the status and the fixed height with it."""
    import nocturne.ui.theme as theme
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance()
    sheet = theme.build_stylesheet()
    app.setStyleSheet(sheet)
    try:
        desc = QLabel("x"); desc.setObjectName("stepDesc"); desc.ensurePolished()
        assert desc.font().pixelSize() == 12, "precondition: the theme's description size"
        b = _btn(qtbot)
        _, small = b._fonts()
        assert small.pixelSize() == desc.font().pixelSize()
        assert QFontMetrics(small).height() == QFontMetrics(desc.font()).height()
        a = _btn(qtbot)
        h12 = a.height()
        # A bigger description (not a real theme value — a probe that the size
        # is READ, not copied) must reach the status line and the fixed height.
        rule = next(line for line in sheet.splitlines() if line.startswith("QLabel#stepDesc "))
        assert "font-size: 12px" in rule, "precondition"
        app.setStyleSheet(sheet.replace(rule, rule.replace("font-size: 12px", "font-size: 18px")))
        qtbot.wait(5)
        _, small = a._fonts()
        assert small.pixelSize() == 18
        assert a.height() > h12
    finally:
        app.setStyleSheet("")


def test_the_status_line_is_lighter_than_the_label(qtbot):
    """Andreas, 2026-09-26: in the green state both lines were heavy (label
    700, status 600 inherited from the stylesheet) in one ink — two
    headlines. The hierarchy comes from weight: the status is normal. Under
    the real stylesheet — without it the inherited 600 never arrives and
    this passes on the old code."""
    import nocturne.ui.theme as theme
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        b = _btn(qtbot)
        b.set_state("pending")
        b.ensurePolished()
        assert b.font().weight() > QFont.Weight.Normal, "precondition: the button font is heavy"
        bold, small = b._fonts()
        assert small.weight() == QFont.Weight.Normal
        assert bold.weight() > small.weight()
    finally:
        app.setStyleSheet("")


def test_the_green_body_is_the_darker_button_fill_and_its_ink_reads(qtbot):
    """The lit button alternates between green Apply and blue Next, so the
    green fill was taken down to Next's loudness (APPLY_FILL, B 73 -> 65).
    Sampled from the painted body under the real stylesheet, with the dark
    label ink still >= 4.5:1 on it."""
    import nocturne.ui.theme as theme
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        b = _btn(qtbot)
        b.set_state("pending")
        img = b.grab().toImage()
        body = img.pixelColor(4, img.height() // 2)
        assert body.name() == theme.APPLY_FILL, body.name()
        assert _contrast_ratio(body, QColor("#052611")) >= 4.5
    finally:
        app.setStyleSheet("")


@pytest.mark.parametrize("state,expected", [("applied", "BG_2"), ("pending", "APPLY_FILL_DOWN")])
def test_a_held_button_keeps_its_own_colour_family(qtbot, state, expected):
    """A plain Apply turned green while held: its TEXT label fell to 3.2:1 and
    a live "✓ applied" (SUCCESS) vanished into the green. Plain stays plain;
    green goes one shade darker."""
    import nocturne.ui.theme as theme
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        b = _btn(qtbot)
        b.set_state(state)            # "applied" here is the live (R13) one
        assert b.isEnabled()
        b.setDown(True)
        b.style().unpolish(b); b.style().polish(b)
        img = b.grab().toImage()
        assert img.pixelColor(4, img.height() // 2).name() == getattr(theme, expected)
    finally:
        app.setStyleSheet("")
