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
    assert checked, "no visible panelRule dividers were found to check"
    assert not bad, "\n".join(bad[:30])
