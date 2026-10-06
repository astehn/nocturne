"""Files the system asks Nocturne to open — a Finder double-click, "Open With",
the Dock icon (QFileOpenEvent on macOS) or the command line. Andreas,
2026-10-06: Nocturne could not be chosen in "Open With" at all."""
import pathlib
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication, QDialog

from nocturne.ui.open_requests import OpenRequests, path_from_argv
from tests.ui.test_main_window import _make_fits, _window


class _Win(QObject):
    def __init__(self):
        super().__init__()
        self.opened = []

    def open_requested(self, path):
        self.opened.append(path)


def _send_open(path):
    QApplication.sendEvent(QApplication.instance(), QFileOpenEvent(path))


def test_a_file_sent_before_the_window_exists_opens_when_it_does(qtbot):
    """A double-click on a project when Nocturne is not running starts the app
    AND asks it to open the file — before any window exists."""
    req = OpenRequests(QApplication.instance())
    try:
        _send_open("/tmp/first.fits")
        _send_open("/tmp/second.fits")
        win = _Win()
        req.attach(win)
        qtbot.waitUntil(lambda: win.opened == ["/tmp/second.fits"], timeout=2000)
        _send_open("/tmp/third.nocturne")
        qtbot.waitUntil(lambda: win.opened[-1] == "/tmp/third.nocturne", timeout=2000)
    finally:
        QApplication.instance().removeEventFilter(req)


def test_other_events_pass_through(qtbot):
    req = OpenRequests(QApplication.instance())
    try:
        assert req.eventFilter(None, QEvent(QEvent.Type.Show)) is False
    finally:
        QApplication.instance().removeEventFilter(req)


def test_the_command_line_names_the_file(tmp_path):
    f = tmp_path / "m 31.fits"
    f.write_text("x")
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    assert path_from_argv(["nocturne", "--no-splash", str(txt), str(f)]) == str(f)
    assert path_from_argv(["nocturne", "--size", "1280x800"]) is None
    assert path_from_argv(["nocturne"]) is None


# --- the window's door ---------------------------------------------------------
def test_an_image_request_opens_it(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_requested(_make_fits(tmp_path))
    assert win.project is not None and win.current_stage_id() == "load"


def test_a_project_request_goes_through_the_project_door(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    p = tmp_path / "x.nocturne"
    p.write_text("x")
    opened = []
    monkeypatch.setattr(win, "_open_project", lambda path=None: opened.append(path))
    win.open_requested(str(p))
    assert opened == [str(p)]


def test_a_file_nocturne_cannot_open_is_said_plainly(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    p = tmp_path / "x.jpg"
    p.write_text("x")
    warned = []
    win._show_warning = warned.append
    win.open_requested(str(p))
    assert win.project is None and warned and "cannot open x.jpg" in warned[0]


def test_a_request_while_working_or_under_a_tool_window_asks_to_try_again(qtbot, tmp_path, monkeypatch):
    win = _window(qtbot, tmp_path)
    fits = _make_fits(tmp_path)
    opened, warned = [], []
    monkeypatch.setattr(win, "open_any", lambda p: opened.append(p))
    win._show_warning = warned.append
    win._set_busy(True)
    win.open_requested(fits)
    win._set_busy(False)
    dlg = QDialog(win)
    dlg.setModal(True)
    dlg.show()
    qtbot.waitUntil(lambda: QApplication.activeModalWidget() is dlg, timeout=2000)
    win.open_requested(fits)
    dlg.close()
    assert opened == [] and len(warned) == 2
    win.open_requested(fits)
    assert opened == [fits]


# --- the macOS package ---------------------------------------------------------
def _spec():
    return (pathlib.Path(__file__).resolve().parents[2] / "packaging" / "nocturne.spec").read_text()


def test_the_app_package_says_what_it_opens():
    """Without document types macOS greys Nocturne out in "Open With"."""
    s = _spec()
    assert '"CFBundleDocumentTypes"' in s
    assert '"com.nocturneastro.project"' in s and '["nocturne"]' in s
    assert '["fit", "fits", "fts"]' in s
    # The identifier the astronomy apps share; a private one loses .fits to them.
    assert '"gov.nasa.gsfc.fits"' in s and '"gov.nasa.fits"' not in s
    assert '"public.tiff"' in s
    tiff = re.search(r'\{[^{}]*"public\.tiff"[^{}]*\}', s).group(0)
    assert '"Alternate"' in tiff, "Nocturne must not claim every TIFF on the Mac"


def test_argv_emulation_is_off():
    """It consumed the open-document event at launch, so Qt never delivered it."""
    assert re.search(r"argv_emulation\s*=\s*False", _spec())


def test_several_files_at_once_open_only_the_last(qtbot):
    """Three files opened together from the Finder are three events; loading
    each only for the last to replace it helps nobody."""
    req = OpenRequests(QApplication.instance())
    try:
        win = _Win()
        req.attach(win)
        for n in ("a", "b", "c"):
            _send_open(f"/tmp/{n}.fits")
        qtbot.wait(50)
        assert win.opened == ["/tmp/c.fits"]
    finally:
        QApplication.instance().removeEventFilter(req)


def test_the_file_open_event_is_taken(qtbot):
    req = OpenRequests(QApplication.instance())
    try:
        assert req.eventFilter(None, QFileOpenEvent("/tmp/x.fits")) is True
    finally:
        QApplication.instance().removeEventFilter(req)


def test_a_minimised_window_comes_back_for_the_file(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.show()
    qtbot.waitExposed(win)
    win.showMinimized()
    qtbot.waitUntil(win.isMinimized, timeout=2000)
    win.open_requested(_make_fits(tmp_path))
    assert not win.isMinimized()
