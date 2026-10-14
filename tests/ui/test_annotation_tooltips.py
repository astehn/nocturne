"""The canvas shows the overlay's plain-words tips when the pointer rests on a label."""
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QToolTip

from nocturne.core.annotation_layout import GridLine, Label
from nocturne.ui.annotation_overlay import build_annotation_group


def test_labels_with_a_tip_carry_it_and_labels_without_do_not(qtbot):
    g = build_annotation_group([Label("15′", 10, 10, "#fff", tip="spans 15 arcminutes"),
                                Label("M 16", 10, 60, "#fff"),
                                GridLine([(0, 100), (200, 100)], "#888", "18h20m", "right ascension")],
                               (200, 200))
    tips = sorted({c.toolTip() for c in g.childItems() if c.toolTip()})
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
    qtbot.waitUntil(lambda: QToolTip.isVisible() and QToolTip.text() == "spans 15 arcminutes",
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
    qtbot.waitUntil(lambda: QToolTip.isVisible() and QToolTip.text() == "spans 15 arcminutes",
                    timeout=1000)
