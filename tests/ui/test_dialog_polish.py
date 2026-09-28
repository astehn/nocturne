"""Three things his website screenshots showed on 2026-09-27: Share's chosen
"Post as" shape looked like the others, Share's ↺ button was an empty square,
and Narrowband / Colour Balance kept Reset mid-form while Star Spikes pins it
beside Apply and Close. Each is checked the way he saw it: under the app's
own stylesheet, as rendered pixels or laid-out positions."""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QPushButton                      # noqa: E402

from nocturne.core.image import AstroImage                     # noqa: E402
from nocturne.settings import Settings                         # noqa: E402
from nocturne.ui.color_balance_dialog import ColorBalanceDialog  # noqa: E402
from nocturne.ui.narrowband_dialog import NarrowbandDialog     # noqa: E402
from nocturne.ui.share_dialog import ShareDialog               # noqa: E402
from nocturne.ui.theme import build_stylesheet                 # noqa: E402


def _mean(widget):
    img = widget.grab().toImage()
    w, h = img.width(), img.height()
    px = [img.pixelColor(x, y) for x in range(0, w, 3) for y in range(0, h, 3)]
    return np.array([[c.red(), c.green(), c.blue()] for c in px], float).mean(axis=0)


def _share(qtbot):
    rgb = np.full((400, 300, 3), 180, np.uint8)
    d = ShareDialog(rgb, {"target": "NGC 7000", "source_label": "x.fits"},
                    Settings(handle="me"))
    d.setStyleSheet(build_stylesheet())
    qtbot.addWidget(d)
    d.show()
    qtbot.wait(20)
    return d


def test_the_chosen_post_as_shape_is_lit(qtbot):
    d = _share(qtbot)
    buttons = list(d._aspect_buttons.values())
    chosen = [b for b in buttons if b.isChecked()]
    assert len(chosen) == 1
    other = next(b for b in buttons if not b.isChecked())
    # The chosen one is visibly different, not just flagged in the model.
    assert np.abs(_mean(chosen[0]) - _mean(other)).sum() > 60


def test_the_restore_glyph_is_drawn(qtbot):
    d = _share(qtbot)
    reset = next(b for b in d.findChildren(QPushButton) if b.text() == "↺")
    blank = QPushButton("", reset.parentWidget())
    blank.setObjectName(reset.objectName())
    blank.setFixedSize(reset.size())
    blank.show()
    qtbot.wait(10)
    # An empty square and the ↺ button must not render alike.
    assert np.abs(_mean(reset) - _mean(blank)).sum() > 3


def _nb_img():
    ha = np.full((40, 40), 0.5, np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def _in_one_row_left_of_apply(d):
    reset, apply = d.reset_btn, d.apply_btn
    r = reset.mapTo(d, reset.rect().center())
    a = apply.mapTo(d, apply.rect().center())
    assert abs(r.y() - a.y()) <= 2           # the same row
    assert r.x() < a.x()                     # Reset · Apply · Close


def test_narrowband_pins_reset_with_apply(qtbot):
    d = NarrowbandDialog(Settings(), _nb_img())
    qtbot.addWidget(d)
    d.show()
    qtbot.wait(10)
    _in_one_row_left_of_apply(d)


def test_colour_balance_pins_reset_with_apply(qtbot):
    img = AstroImage(np.full((40, 40, 3), 0.4, np.float32), is_linear=False)
    d = ColorBalanceDialog(Settings(), img)
    qtbot.addWidget(d)
    d.show()
    qtbot.wait(10)
    _in_one_row_left_of_apply(d)
