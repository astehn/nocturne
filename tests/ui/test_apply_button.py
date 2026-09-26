import pytest
from PySide6.QtWidgets import QWidget, QVBoxLayout

from nocturne.ui.apply_button import STATES, ApplyButton


def _btn(qtbot, label="Apply Levels", look="A", width=380):
    host = QWidget(); lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)  # so `width=` is the BUTTON's width,
    # not the host's minus the layout's default ~11px-per-side margin — the
    # label_fits() regression test below needs an exact button width.
    b = ApplyButton(label, look=look)
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


@pytest.mark.parametrize("look", ["A", "B"])
def test_the_height_never_changes_with_state(qtbot, look):
    b = _btn(qtbot, look=look)
    heights = set()
    for s in STATES:
        b.set_state(s); qtbot.wait(5)
        heights.add(b.height())
    assert len(heights) == 1


def test_look_a_is_taller_than_look_b(qtbot):
    assert _btn(qtbot, look="A").height() > _btn(qtbot, look="B").height()


@pytest.mark.parametrize("state,green,enabled,words", [
    ("pending", True, True, "not applied"),
    ("not_run", True, True, "not run"),
    ("applied", False, True, "applied"),    # live unless verified unchanged (R13)
    ("no_change", False, False, "no changes"),
    ("busy", False, False, ""),
])
@pytest.mark.parametrize("look", ["A", "B"])
def test_each_state_reads_and_colours_as_ruled(qtbot, look, state, green, enabled, words):
    b = _btn(qtbot, look=look)
    b.set_state(state)
    assert b.state() == state
    assert b.property("pending") == ("true" if green else "false")
    assert b.isEnabled() is enabled
    assert words in b.status_text()
    assert b.label_text() == "Apply Levels"


@pytest.mark.parametrize("label", ["Apply Deconvolution", "Apply De-green Stars", "Apply Linear Denoise"])
def test_long_names_fit_with_the_chip(qtbot, label):
    """Review Focus 4: look B must not clip the step name against the chip."""
    b = _btn(qtbot, label=label, look="B", width=380)
    b.set_state("pending")
    assert b.label_fits(), f"{label!r} is clipped next to the chip at 380 px"


@pytest.mark.parametrize("look", ["A", "B"])
def test_applied_and_verified_unchanged_is_off_plain_and_says_applied(qtbot, look):
    """Andreas, 2026-09-25 23:27: an applied step whose controls ARE the commit
    cannot be pressed again. Only the caller's verification switches it off."""
    b = _btn(qtbot, look=look)
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
    """The darkest-vs-body pixel of look A's status line, i.e. its text colour."""
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


def test_look_a_paints_a_disabled_applied_dim_not_green(qtbot):
    """Spec §4: applied-and-off is "plain, dim". SUCCESS green on a button you
    cannot press reads as "press me"."""
    from PySide6.QtGui import QColor
    from nocturne.ui.theme import SUCCESS
    b = _btn(qtbot, look="A")
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
    draw would still be caught, which reading our own _CHIP_STYLE dict could
    not do."""
    l1, l2 = sorted((_relative_luminance(c1), _relative_luminance(c2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _text_pixel(img, rect, fill):
    """The chip-rect pixel farthest (by RGB distance) from the fill colour —
    the closest thing to pure text ink at a small anti-aliased font size. A
    partially-blended anti-aliased pixel UNDERSTATES the true ink-vs-fill
    contrast (it sits between the two colours), so a pass here is a safe
    lower bound on the real contrast, never an inflated one."""
    best, best_dist = fill, -1
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            px = img.pixelColor(x, y)
            dist = ((px.red() - fill.red()) ** 2 + (px.green() - fill.green()) ** 2
                    + (px.blue() - fill.blue()) ** 2)
            if dist > best_dist:
                best_dist, best = dist, px
    return best


def test_every_chip_state_is_legible_on_its_body(qtbot):
    """Review Focus 1 (CRITICAL): `not_run`'s chip had no fill of its own, so
    its TEXT_DIM text sat directly on the SUCCESS green body — pixel-sampled
    at 1.27:1. Every non-empty chip must now paint its own opaque fill, with
    real contrast >= 4.5:1 between that fill and its text, sampled from the
    actual rendered pixels under the real app stylesheet.
    """
    import nocturne.ui.theme as theme
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        for state in STATES:
            b = _btn(qtbot, look="B")
            b.set_state(state)
            rect = b.chip_geometry()   # busy keeps the previous state's chip
            img = b.grab().toImage()
            fill = img.pixelColor(rect.left() + 3, rect.center().y())
            text = _text_pixel(img, rect, fill)
            ratio = _contrast_ratio(fill, text)
            assert ratio >= 4.5, (
                f"{state}: fill={fill.name()} text={text.name()} contrast={ratio:.2f}:1")
    finally:
        app.setStyleSheet("")


def test_label_fits_uses_the_same_fonts_paintevent_draws_with(qtbot):
    """Review Focus 2: label_fits() used to measure the label in the REGULAR
    font while paintEvent draws it BOLD, and the chip at FULL size while
    paintEvent draws it SMALL (-2pt) — two errors in opposite directions that
    happened to cancel out for the three names in
    test_long_names_fit_with_the_chip. At button width 237, "Apply
    Deconvolution" needs 235px measured with those two wrong fonts (so the
    old formula answered True, "fits") but 239px measured with the fonts
    actually painted (so the true layout clips it).
    """
    b = _btn(qtbot, label="Apply Deconvolution", look="B", width=237)
    b.set_state("pending")
    assert not b.label_fits(), "237px fits by the old (wrong) fonts, not by the real ones"


def test_height_matches_a_live_recompute_after_show(qtbot):
    """Review Focus 3: the fixed height used to be computed once in
    __init__, before the widget had ever been polished under the real app
    stylesheet (45px measured there; 47px true) — and nothing re-triggered
    it afterwards, so a real shown button stayed 2px short of what its OWN
    set_look() computes once genuinely live and styled.
    """
    import nocturne.ui.theme as theme
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        for look in ("A", "B"):
            b = _btn(qtbot, look=look)
            shown_height = b.height()
            b.set_look(look)  # a fresh, live recompute — the ground truth
            assert b.height() == shown_height, (
                f"look {look}: shown height {shown_height} != live recompute {b.height()}")
    finally:
        app.setStyleSheet("")


@pytest.mark.parametrize("look", ["A", "B"])
@pytest.mark.parametrize("before", ["pending", "not_run", "applied", "no_change"])
def test_busy_keeps_the_previous_words(qtbot, look, before):
    """Spec §4: busy is 'disabled, unchanged text'. A pending edit must still
    say 'not applied' while an unrelated operation runs, and come back as it
    was."""
    b = _btn(qtbot, look=look)
    b.set_state(before)
    words, chip = b.status_text(), b.chip_geometry()
    b.set_state("busy")
    assert b.state() == "busy" and not b.isEnabled()
    assert b.status_text() == words
    assert b.chip_geometry() == chip
    b.set_state(before)
    assert b.status_text() == words


# --- D1 (Andreas, 2026-09-26): the status was unreadable at any size --------

def test_status_is_drawn_at_the_step_descriptions_size(qtbot):
    """His real window: the status (button font -2 pt, floored at 8 pt) read
    as ~7 px of ink in both looks. It is now the size of the description
    under the step title, read from the live stylesheet — so a stylesheet
    that changes that size changes the status and the fixed height with it."""
    import nocturne.ui.theme as theme
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance()
    sheet = theme.build_stylesheet()
    app.setStyleSheet(sheet)
    try:
        desc = QLabel("x"); desc.setObjectName("stepDesc"); desc.ensurePolished()
        assert desc.font().pixelSize() == 12, "precondition: the theme's description size"
        for look in ("A", "B"):
            b = _btn(qtbot, look=look)
            _, small = b._fonts()
            assert small.pixelSize() == desc.font().pixelSize(), look
            assert QFontMetrics(small).height() == QFontMetrics(desc.font()).height(), look
            if look == "B":
                assert b.chip_geometry().height() >= QFontMetrics(small).height(), "chip holds its text"
        a = _btn(qtbot, look="A")
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
