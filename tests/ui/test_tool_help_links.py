"""Every tool window reaches its own help: "How this works ↗" just above the
closing buttons, aligned right (Andreas, 2026-10-05) — opening, and pressed
again closing, a help window that belongs to the tool window, so the tool's
modality cannot block it."""
import numpy as np
import pytest
from PySide6.QtCore import QByteArray, QPoint, QRect, Qt
from PySide6.QtWidgets import QPushButton, QWidget

from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.ui.help_dialog import HelpDialog
from nocturne.ui.help_link import HelpLink


def _img(h=96, w=128):
    a = np.full((h, w, 3), 0.2, np.float32)
    a[40:43, 60:63] = 0.95
    return AstroImage(a, is_linear=False, metadata={})


def _narrowband(parent):
    from nocturne.ui.narrowband_dialog import NarrowbandDialog
    return NarrowbandDialog(Settings(), _img(), parent=parent)


def _colour_balance(parent):
    from nocturne.ui.color_balance_dialog import ColorBalanceDialog
    return ColorBalanceDialog(Settings(), _img(), parent=parent)


def _spikes(parent):
    from nocturne.ui.star_spikes_dialog import StarSpikesDialog
    return StarSpikesDialog(_img(), parent=parent)


def _starless(parent):
    from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog
    stars = AstroImage(np.zeros((96, 128, 3), np.float32), is_linear=False, metadata={})
    return StarlessLevelsDialog(_img(), stars, parent=parent)


def _trim(parent):
    from nocturne.ui.trim_dialog import TrimDialog
    return TrimDialog(_img(), parent=parent)


def _upscale(parent):
    from nocturne.ui.upscale_dialog import UpscaleDialog
    return UpscaleDialog(_img(), {}, Settings(), parent=parent)


def _share(parent):
    from nocturne.ui.share_dialog import ShareDialog
    rgb = (np.random.default_rng(0).random((300, 400, 3)) * 255).astype(np.uint8)
    return ShareDialog(rgb, {"target": "NGC 7000"}, Settings(), parent=parent)


TOOLS = [
    (_narrowband, "narrowband", "Close"),
    (_colour_balance, "color_balance", "Close"),
    (_spikes, "star_spikes", "Close"),
    (_starless, "starless_levels", "Cancel"),
    (_trim, "trim", "Apply Trim"),
    (_upscale, "upscale", "Close"),
    (_share, "share", "Close"),
]
IDS = [t[1] for t in TOOLS]


class _Owner(QWidget):
    """Stands in for MainWindow: the keeper of the help window's place."""
    def __init__(self, geometry=""):
        super().__init__()
        self.geometry_hex = geometry
        self.remembered = []

    def help_geometry(self):
        return self.geometry_hex

    def remember_help_geometry(self, dlg):
        self.remembered.append(bytes(dlg.saveGeometry().toHex()).decode())


def _open(qtbot, build, owner=None):
    owner = owner or _Owner()
    qtbot.addWidget(owner)
    d = build(owner)
    d.resize(1100, 760)
    d._test_owner = owner        # qtbot holds widgets weakly; keep the parent alive
    d.show()
    qtbot.waitExposed(d)
    return d


def _in_dialog(d, w) -> QRect:
    return QRect(w.mapTo(d, QPoint(0, 0)), w.size())


@pytest.mark.parametrize("build,topic,last_btn", TOOLS, ids=IDS)
def test_link_opens_this_tools_help_and_closes_it_again(qtbot, build, topic, last_btn):
    d = _open(qtbot, build)
    link = d.findChild(HelpLink)
    assert link is not None and link.isVisible()
    assert "How this works" in link.text()

    link.linkActivated.emit("#")
    help_dlg = link.help_window()
    assert help_dlg is not None and help_dlg.isVisible()
    assert help_dlg.current_topic() == topic
    # Owned by the TOOL window, so the tool's modality does not block it.
    assert help_dlg.parentWidget() is d
    assert not help_dlg.isModal()
    assert help_dlg.windowType() == Qt.WindowType.Tool, "stays above Nocturne"

    link.linkActivated.emit("#")
    assert not help_dlg.isVisible()
    link.linkActivated.emit("#")
    assert link.help_window().isVisible(), "and opens again"
    d.reject()


@pytest.mark.parametrize("build,topic,last_btn", TOOLS, ids=IDS)
def test_link_sits_just_above_the_closing_buttons_aligned_right(qtbot, build, topic, last_btn):
    d = _open(qtbot, build)
    link = d.findChild(HelpLink)
    btn = next(b for b in d.findChildren(QPushButton)
               if b.text() == last_btn and b.isVisible())
    lr, br = _in_dialog(d, link), _in_dialog(d, btn)
    assert lr.bottom() < br.top(), "above the buttons"
    assert br.top() - lr.bottom() < 40, "directly above, not adrift"
    assert abs(lr.right() - br.right()) <= 2, "right edge lines up with the last button"
    d.reject()


@pytest.mark.parametrize("build,topic,last_btn", TOOLS, ids=IDS)
def test_closing_the_tool_closes_its_help(qtbot, build, topic, last_btn):
    d = _open(qtbot, build)
    link = d.findChild(HelpLink)
    link.toggle()
    help_dlg = link.help_window()
    assert help_dlg.isVisible()
    d.reject()
    assert not help_dlg.isVisible()


def test_help_opens_where_the_main_help_window_was_left_and_remembers(qtbot):
    probe = HelpDialog(); qtbot.addWidget(probe)
    probe.setGeometry(40, 50, 780, 580)
    saved = bytes(probe.saveGeometry().toHex()).decode()
    owner = _Owner(saved)
    d = _open(qtbot, _trim, owner)
    link = d.findChild(HelpLink)
    link.toggle()
    # Exactly where the main window's own help window would open from it.
    ref = HelpDialog(); qtbot.addWidget(ref)
    ref.restoreGeometry(QByteArray.fromHex(saved.encode())); ref.show()
    assert link.help_window().size() == ref.size() == probe.size()
    assert link.help_window().pos() == ref.pos()
    assert owner.remembered == []
    link.toggle()
    assert len(owner.remembered) == 1, "its place is handed back on close"
    QByteArray.fromHex(owner.remembered[0].encode())   # valid hex
    d.reject()


def test_main_window_shares_the_help_geometry(qtbot, tmp_path):
    """MainWindow is the owner HelpLink finds up the parent chain."""
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    probe = HelpDialog(); qtbot.addWidget(probe)
    probe.setGeometry(60, 70, 760, 560)
    win.remember_help_geometry(probe)
    assert win.help_geometry() == bytes(probe.saveGeometry().toHex()).decode()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_the_keyboard_opens_it_and_does_not_reach_the_default_button(qtbot, key):
    """Starless Levels' default button is OK: Return on the link applied the
    step and closed the window."""
    owner = _Owner(); qtbot.addWidget(owner)
    from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog
    stars = AstroImage(np.zeros((96, 128, 3), np.float32), is_linear=False, metadata={})
    d = StarlessLevelsDialog(_img(), stars, parent=owner)
    d._test_owner = owner
    # Modal, as exec() makes it: the main window's app-wide Space peek stands
    # aside only while a modal window is up, which is the real situation.
    d.setModal(True); d.show(); qtbot.waitExposed(d)
    link = d.findChild(HelpLink)
    link.setFocus()
    qtbot.keyClick(link, key)
    assert d.isVisible() and d.result() == 0, "the dialog was not accepted"
    assert link.help_window() is not None and link.help_window().isVisible()
    qtbot.keyClick(link, key)
    assert not link.help_window().isVisible(), "and the key closes it again"
    d.reject()


def test_an_open_main_help_window_is_covered_not_doubled(qtbot, tmp_path):
    """A tool window's modality freezes the main help window; the tool's own
    opens exactly over it, from where it IS, not where it was last closed."""
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "s.json"))
    qtbot.addWidget(win)
    main_help = win._open_help("getting-started")
    main_help.setGeometry(90, 80, 780, 580)
    assert win.help_geometry() == bytes(main_help.saveGeometry().toHex()).decode()
    main_help.reject()
    assert win.help_geometry() == win.settings.help_window_geometry, "closed: the saved place"
