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
    ("applied", False, True, "applied"),
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
            rect = b.chip_geometry()
            if rect is None:
                continue  # busy: no chip text is painted, nothing to sample
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
