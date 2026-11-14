from nocturne.ui import theme


def test_tokens_defined():
    for name in ("BG_0", "BG_1", "BG_2", "BG_3", "ACCENT", "SUCCESS",
                 "WARNING", "DANGER", "TEXT", "TEXT_DIM", "TEXT_FAINT"):
        val = getattr(theme, name)
        assert isinstance(val, str) and val.startswith("#")


def test_build_stylesheet_uses_tokens():
    qss = theme.build_stylesheet()
    assert isinstance(qss, str) and len(qss) > 500
    # semantic colours flow into the stylesheet
    assert theme.ACCENT in qss
    assert theme.BG_1 in qss
    # slider + progressbar polish present
    assert "QSlider" in qss and "QProgressBar" in qss
    assert "::sub-page" in qss  # accent-filled slider track


def test_tooltips_are_readable_under_a_light_system_palette(qtbot):
    """GitHub #2: in macOS light mode the tooltip took the system's white
    background while the stylesheet's `*` rule made its text light grey."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QLabel, QToolTip
    from nocturne.ui.theme import build_stylesheet

    app = QApplication.instance()
    old_pal, old_css = app.palette(), app.styleSheet()
    light = QPalette(old_pal)
    light.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    light.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    try:
        app.setPalette(light)
        app.setStyleSheet(build_stylesheet())
        w = QLabel("x")
        qtbot.addWidget(w)
        w.show()
        QToolTip.showText(w.mapToGlobal(QPoint(5, 5)), "Readable tooltip text", w)
        tip = next(t for t in app.topLevelWidgets()
                   if t.metaObject().className() == "QTipLabel" and t.isVisible())
        img = tip.grab().toImage()
        bg = img.pixelColor(img.width() - 3, img.height() // 2)
        fg = tip.palette().color(tip.foregroundRole())
        assert abs(bg.lightnessF() - fg.lightnessF()) > 0.5
    finally:
        QToolTip.hideText()
        app.setStyleSheet(old_css)
        app.setPalette(old_pal)
