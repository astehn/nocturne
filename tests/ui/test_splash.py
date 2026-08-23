import pytest

pytest.importorskip("PySide6")

import ast
from pathlib import Path

import nocturne
from nocturne.ui.splash import (
    MIN_SPLASH_SECONDS,
    NocturneSplash,
    make_splash,
    remaining_hold,
    splash_caption,
)


def test_the_caption_reports_the_running_version():
    """Read from nocturne.__version__, never a second copy. A splash that keeps
    announcing 0.16.0 after a release is worse than no version at all."""
    assert splash_caption("1.2.3") == "v1.2.3"
    assert nocturne.__version__ in splash_caption(nocturne.__version__)


def test_the_hold_fills_only_the_time_startup_did_not_use():
    """The previous attempt failed because the app loaded before the splash was
    ever seen. The fix is a MINIMUM visible time, not a fixed delay added to
    startup: a slow start waits for nothing extra."""
    assert remaining_hold(0.0, minimum=2.0) == pytest.approx(2.0)
    assert remaining_hold(0.5, minimum=2.0) == pytest.approx(1.5)
    assert remaining_hold(2.0, minimum=2.0) == pytest.approx(0.0)
    # Never negative: a slow startup must not ask the caller to wait backwards.
    assert remaining_hold(9.0, minimum=2.0) == 0.0


def test_the_minimum_is_long_enough_to_actually_see():
    """Andreas' whole complaint: 'the application loaded so fast that the user
    never saw the splash'. Pinned so a future tidy-up can't quietly reduce it
    back to invisible."""
    assert MIN_SPLASH_SECONDS >= 1.5


def test_the_splash_carries_a_real_image_and_the_version(qtbot):
    sp = make_splash("9.9.9")
    qtbot.addWidget(sp)
    assert isinstance(sp, NocturneSplash)
    assert not sp.pixmap().isNull()
    assert sp.caption == "v9.9.9"


def test_the_splash_is_scaled_for_the_screen_not_left_at_source_size(qtbot):
    """The source art is 1254x1254. Shown unscaled it is a wall on a laptop, so
    the logical size must be sane — while devicePixelRatio keeps it crisp."""
    sp = make_splash("1.0.0")
    qtbot.addWidget(sp)
    pm = sp.pixmap()
    logical_w = pm.width() / max(pm.devicePixelRatio(), 1.0)
    assert 200 <= logical_w <= 700, f"logical width {logical_w} is not a sane splash size"


def test_the_caption_is_actually_painted(qtbot):
    """`caption` being right proves nothing about what reaches the screen — the
    whole point is that Andreas SEES the version. Render the widget and require
    the caption area to differ from the same splash rendered without one."""
    from PySide6.QtGui import QImage, QPainter

    def render(caption: str) -> QImage:
        sp = make_splash("1.0.0")
        qtbot.addWidget(sp)
        sp.caption = caption
        img = QImage(sp.pixmap().size(), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        sp.drawContents(p)
        p.end()
        return img

    with_text = render("v1.0.0")
    without = render("")
    assert with_text != without, "drawContents painted nothing for the caption"


def test_main_shows_the_splash_before_it_builds_the_window():
    """AST, not a text search: the freeze_support guard next door was once
    defeated by matching its own docstring. And it must be inside main(), not
    under `if __name__ == '__main__'` — the packaged app imports main() from an
    entry script, so everything under that guard is dead code in the bundle.
    """
    src = Path(nocturne.__file__).resolve().parent / "__main__.py"
    tree = ast.parse(src.read_text())
    main_fn = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "main")

    def first_call_line(name: str) -> int | None:
        for node in ast.walk(main_fn):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id == name:
                    return node.lineno
                if isinstance(f, ast.Attribute) and f.attr == name:
                    return node.lineno
        return None

    splash_line = first_call_line("make_splash")
    window_line = first_call_line("MainWindow")
    assert splash_line is not None, "main() never builds a splash"
    assert window_line is not None, "main() never builds the window"
    assert splash_line < window_line, (
        "the splash must be shown BEFORE the window is constructed — building "
        "the window first is the whole reason the earlier attempt was invisible"
    )


def test_clicking_the_splash_reports_a_dismissal(qtbot):
    """QSplashScreen's own click handling only HIDES the widget — it never
    destroys it. A caller that waited on `destroyed` would sit out the whole
    timer with nothing on screen, so the click would appear to do nothing. The
    explicit signal is what makes dismissal actually shorten the wait.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    sp = make_splash("1.0.0")
    qtbot.addWidget(sp)
    seen = []
    sp.dismissed.connect(lambda: seen.append(True))

    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPoint(5, 5), sp.mapToGlobal(QPoint(5, 5)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(sp, ev)
    assert seen == [True], "a click on the splash did not report a dismissal"


def test_main_waits_on_an_event_loop_and_never_sleeps():
    """time.sleep would block the event loop, so the splash never paints: macOS
    shows a white rectangle and then a beachball. That is worse than no splash,
    and it is the obvious way to write this — so it is pinned.
    """
    src = Path(nocturne.__file__).resolve().parent / "__main__.py"
    tree = ast.parse(src.read_text())
    main_fn = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {
        node.func.attr for node in ast.walk(main_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(main_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "sleep" not in called, "main() blocks the event loop with sleep"
    assert "QEventLoop" in called, "main() does not run a real event loop while holding"
