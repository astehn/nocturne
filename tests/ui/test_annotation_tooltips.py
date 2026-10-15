"""The canvas shows the overlay's plain-words tips when the pointer rests on a label."""
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QToolTip

from PySide6 import QtGui
from PySide6.QtGui import QTextDocument

from nocturne.core.annotation_layout import GridLine, Label
from nocturne.ui.annotation_overlay import build_annotation_group


def _plain(tip: str) -> str:
    """A tip's words, as a person reads them: the items carry rich text so Qt
    wraps it (see test_tips_are_rich_text_so_qt_wraps_them)."""
    doc = QTextDocument()
    doc.setHtml(tip)
    return doc.toPlainText().strip()      # a table cell reads with blank lines round it


def test_labels_with_a_tip_carry_it_and_labels_without_do_not(qtbot):
    g = build_annotation_group([Label("15′", 10, 10, "#fff", tip="spans 15 arcminutes"),
                                Label("M 16", 10, 60, "#fff"),
                                GridLine([(0, 100), (200, 100)], "#888", "18h20m", "right ascension")],
                               (200, 200))
    tips = sorted({_plain(c.toolTip()) for c in g.childItems() if c.toolTip()})
    assert tips == ["right ascension", "spans 15 arcminutes"]
    plain = [c for c in g.childItems() if c.toolTip() == "" and hasattr(c, "childItems")
             and any(getattr(k, "text", lambda: "")() == "M 16" for k in c.childItems())]
    assert plain, "an object label without a tip stays tip-less"


def test_hovering_the_scale_bar_label_shows_its_tip(qtbot):
    scene = QGraphicsScene()
    scene.addItem(build_annotation_group(
        [Label("15′", 20, 20, "#fff", tip="spans 15 arcminutes")], (200, 200)))
    view = QGraphicsView(scene)
    qtbot.addWidget(view)
    view.resize(300, 300)
    view.show()
    qtbot.waitExposed(view)
    vp = view.mapFromScene(26, 28)
    QToolTip.hideText()
    qtbot.waitUntil(lambda: not QToolTip.isVisible(), timeout=1000)
    QApplication.sendEvent(view.viewport(),
                           QHelpEvent(QEvent.Type.ToolTip, vp, view.viewport().mapToGlobal(vp)))
    qtbot.waitUntil(lambda: QToolTip.isVisible() and _plain(QToolTip.text()) == "spans 15 arcminutes",
                    timeout=1000)


def test_the_real_canvas_shows_the_tip_over_the_picture(qtbot):
    # The ImageView adds the overlay under a clip item and has its own event
    # handling (gestures, hover readout); the tip must still get through.
    from PySide6.QtGui import QImage
    from nocturne.ui.image_view import ImageView
    view = ImageView()
    qtbot.addWidget(view)
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(0x202020)
    view.set_image(img)
    view.resize(600, 500)
    view.show()
    qtbot.waitExposed(view)
    view.set_annotations(build_annotation_group(
        [Label("15′", 40, 200, "#fff", tip="spans 15 arcminutes")], (300, 400)))
    vp = view.mapFromScene(46, 208)
    QToolTip.hideText()
    qtbot.waitUntil(lambda: not QToolTip.isVisible(), timeout=1000)
    QApplication.sendEvent(view.viewport(),
                           QHelpEvent(QEvent.Type.ToolTip, vp, view.viewport().mapToGlobal(vp)))
    qtbot.waitUntil(lambda: QToolTip.isVisible() and _plain(QToolTip.text()) == "spans 15 arcminutes",
                    timeout=1000)


LONG = ("This bar spans 15 arcminutes of sky — half the width of the full Moon. "
        "60 arcminutes make 1 degree, 60 arcseconds make 1 arcminute; the full Moon "
        "is about 30 arcminutes across.")


def test_tips_are_rich_text_so_qt_wraps_them(qtbot):
    """His screenshot (2026-10-14): the scale bar's tip was one line across the
    screen. Qt word-wraps a rich-text tooltip and never a plain one, so every
    tip the overlay sets — scale bar, grid labels, N — is rich text carrying
    the core's plain words unchanged (escaped, so a "<" stays a "<")."""
    g = build_annotation_group([Label("15′", 10, 10, "#fff", tip=LONG),
                                Label("N", 10, 60, "#fff", tip="North < on the sky"),
                                GridLine([(0, 100), (200, 100)], "#888", "18h20m",
                                         "right ascension")], (200, 200))
    items = [c for c in g.childItems() if c.toolTip()]
    items += [k for c in g.childItems() for k in c.childItems() if k.toolTip()]
    assert len(items) >= 9, "three labels: each group and its two glyph items"
    for it in items:
        assert QtGui.Qt.mightBeRichText(it.toolTip()), it.toolTip()
    assert {_plain(it.toolTip()) for it in items} == {LONG, "North < on the sky",
                                                      "right ascension"}


def test_the_shown_scale_bar_tip_is_a_short_paragraph(qtbot):
    scene = QGraphicsScene()
    scene.addItem(build_annotation_group([Label("15′", 20, 20, "#fff", tip=LONG)], (200, 200)))
    view = QGraphicsView(scene)
    qtbot.addWidget(view)
    view.resize(300, 300)
    view.show()
    qtbot.waitExposed(view)
    vp = view.mapFromScene(26, 28)
    QToolTip.hideText()
    qtbot.waitUntil(lambda: not QToolTip.isVisible(), timeout=1000)
    QApplication.sendEvent(view.viewport(),
                           QHelpEvent(QEvent.Type.ToolTip, vp, view.viewport().mapToGlobal(vp)))
    qtbot.waitUntil(lambda: QToolTip.isVisible() and _plain(QToolTip.text()) == LONG,
                    timeout=1000)
    shown = _tip_label()
    from PySide6.QtGui import QFontMetricsF
    from nocturne.ui.annotation_overlay import _TIP_CHARS
    want = round(QFontMetricsF(QToolTip.font()).averageCharWidth() * _TIP_CHARS)
    line = QFontMetricsF(shown.font()).lineSpacing()
    # The shown box is the table's measure plus the tip's own margins, and the
    # 176 characters sit in a few lines at ~60 a line (cocoa: 386x46, 3 lines).
    assert want <= shown.width() <= want + 40, (shown.width(), want)
    assert 2 * line < shown.height() < 6 * line, (shown.height(), line)
    QToolTip.hideText()


def _tip_label():
    return next(w for w in QApplication.topLevelWidgets()
                if w.objectName() == "qtooltip_label" and w.isVisible())


def test_a_long_tip_is_set_at_a_reading_measure(qtbot):
    """Qt's own wrap gave ~30 characters a line on macOS (144–174 px, six or
    seven lines for the scale bar). A long tip sits in a table about 60 average
    characters wide — on cocoa 386 px, three lines (2026-10-15). A short tip
    gets no box to pad it."""
    import re
    from PySide6.QtGui import QFontMetricsF
    from nocturne.ui.annotation_overlay import _TIP_CHARS
    g = build_annotation_group([Label("15′", 10, 10, "#fff", tip=LONG),
                                Label("x", 10, 60, "#fff", tip="right ascension")], (200, 200))
    tips = {_plain(c.toolTip()): c.toolTip() for c in g.childItems() if c.toolTip()}
    want = round(QFontMetricsF(QToolTip.font()).averageCharWidth() * _TIP_CHARS)
    m = re.match(r'<table width="(\d+)">', tips[LONG])
    assert m and int(m.group(1)) == want, tips[LONG]
    assert 55 <= _TIP_CHARS <= 65
    assert "<table" not in tips["right ascension"]
