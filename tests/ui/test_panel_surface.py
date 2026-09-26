"""His screenshot, 2026-09-25: the panel is #26282c but every label paints
#1e1f22 — patchwork. Grab the REAL panel and compare pixels: a property that
merely says 'transparent' cannot fool this."""
import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from nocturne.ui.theme import RULE, build_stylesheet
from tests.ui.test_main_window import _make_fits, _window


@pytest.fixture
def styled(qtbot):
    app = QApplication.instance(); old = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(old)


def test_labels_inside_every_step_card_show_the_card_colour(qtbot, tmp_path, styled):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1400, 900); win.show(); qtbot.waitExposed(win)
    bad = []
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        card = win._panel
        img = card.grab().toImage()
        card_px = img.pixelColor(2, img.height() // 2).name()     # card margin
        for lab in card.findChildren(QLabel):
            if not lab.isVisible() or lab.width() < 8:
                continue
            tl = lab.mapTo(card, lab.rect().topRight())
            px = img.pixelColor(max(0, tl.x() - 2), tl.y() + 1).name()   # label's empty corner
            if px != card_px:
                bad.append(f"{st.id}: {lab.objectName() or lab.text()[:20]!r} {px} vs card {card_px}")
    assert not bad, "\n".join(bad[:30])


def test_panel_rule_dividers_show_the_card_colour_not_a_bg1_band(qtbot, tmp_path, styled):
    """A QFrame#panelRule paints its own background too (it inherits the
    global QMainWindow, QWidget rule like any other widget) — a 1-px BG_1
    band above and below the actual line, inside a BG_2 card. Sample the row
    ABOVE the line itself (found by colour, not assumed geometry, since the
    style — not us — decides where inside the frame the line is drawn)."""
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1400, 900); win.show(); qtbot.waitExposed(win)
    bad = []
    checked = 0
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        card = win._panel
        rules = [f for f in card.findChildren(QFrame)
                 if f.objectName() == "panelRule" and f.isVisible()]
        if not rules:
            continue
        img = card.grab().toImage()
        card_px = img.pixelColor(2, img.height() // 2).name()
        for rule in rules:
            top = rule.mapTo(card, rule.rect().topLeft())
            x = top.x() + rule.width() // 2
            line_y = None
            for dy in range(rule.height()):
                y = top.y() + dy
                if 0 <= y < img.height() and img.pixelColor(x, y).name() == RULE:
                    line_y = y
                    break
            checked += 1
            if line_y is None or line_y - 1 < 0:
                bad.append(f"{st.id}: could not locate the rule's own line pixel")
                continue
            px = img.pixelColor(x, line_y - 1).name()
            if px != card_px:
                bad.append(f"{st.id}: row above panelRule {px} vs card {card_px}")
            # The band can sit on either side of the line the style actually
            # draws (found by colour, not assumed geometry) — a BG_1 band
            # below the line would be just as visible as one above it.
            if line_y + 1 < img.height():
                px_below = img.pixelColor(x, line_y + 1).name()
                if px_below != card_px:
                    bad.append(f"{st.id}: row below panelRule {px_below} vs card {card_px}")
    assert checked, "no visible panelRule dividers were found to check"
    assert not bad, "\n".join(bad[:30])


def _first_ink_x(img, rect, threshold=90):
    """First column (image coords) in `rect` holding a pixel brighter than
    `threshold` — where a label's text actually starts on screen."""
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            c = img.pixelColor(x, y)
            if (c.red() + c.green() + c.blue()) / 3 > threshold:
                return x
    return None


def test_the_step_frame_is_one_surface_header_included(qtbot, tmp_path, styled):
    """Ruling R6: the fixed header and the scrolling controls are ONE rounded
    BG_2 card. Grab the whole frame; every label's empty corner — the title
    and the description included — must show the frame colour, and the
    header's text must start in the same column as the controls'."""
    from PySide6.QtCore import QPoint, QRect
    from nocturne.ui.theme import BG_2
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    win.resize(1280, 800); win.show(); qtbot.waitExposed(win)
    frame = win._side.step_frame
    bad, checked = [], 0
    for i, st in enumerate(list(win._stages)):
        if not st.enabled:
            continue
        win._go_to(i, user_initiated=False); qtbot.wait(20)
        img = frame.grab().toImage()
        p = win._panel
        header_labels = [lab for lab in p.header.findChildren(QLabel) if lab.isVisible()]
        assert p.desc_box in header_labels, "precondition: the header is in the frame"
        for lab in header_labels + frame.findChildren(QLabel):
            if not lab.isVisible() or lab.width() < 8 or not frame.isAncestorOf(lab):
                continue
            tr = lab.mapTo(frame, lab.rect().topRight())
            if not (0 <= tr.y() + 1 < img.height()):
                continue            # scrolled out of the frame
            px = img.pixelColor(max(0, tr.x() - 2), tr.y() + 1).name()
            checked += 1
            if px != BG_2:
                bad.append(f"{st.id}: {lab.objectName() or lab.text()[:20]!r} {px} vs frame {BG_2}")
        # Same column: the title's and the description's ink start where the
        # controls do (their container's left edge + a glyph's side bearing).
        controls_x = p.controls.parentWidget().mapTo(frame, QPoint(0, 0)).x()
        title = p.help_link.parentWidget().findChildren(QLabel)[0]
        for lab in (title, p.desc_box):
            tl = lab.mapTo(frame, QPoint(0, 0))
            ink = _first_ink_x(img, QRect(tl.x(), tl.y(), lab.width(), lab.height()))
            if ink is None or abs(ink - controls_x) > 2:
                bad.append(f"{st.id}: {lab.objectName()} text starts at x={ink}, controls at {controls_x}")
    assert checked > 40
    assert not bad, "\n".join(bad[:30])
