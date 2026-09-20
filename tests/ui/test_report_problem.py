"""Help ▸ Report a problem — the route that actually matters.

The website form is where a report lands; this is what makes it worth reading.
A report saying "it doesn't fit my MacBook" costs several round trips with
someone who may never reply. One carrying version, OS, LOGICAL screen size and
window size is fixable without a reply at all.
"""
import os
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def main_window(qtbot, tmp_path):
    """Built the way every other UI test here builds one — no update check and
    no telemetry, so the test describes the app rather than the network."""
    from nocturne.ui.main_window import MainWindow
    win = MainWindow(settings_path=str(tmp_path / "settings.json"),
                     check_updates=False, telemetry=False)
    qtbot.addWidget(win)
    return win


def test_the_help_menu_offers_it(main_window):
    names = [a.text() for m in main_window.menuBar().actions()
             if m.menu() for a in m.menu().actions()]
    assert "Report a problem…" in names


def test_the_report_carries_what_the_reddit_reports_lacked(main_window):
    """Screen size, in LOGICAL units with the scale factor.

    "A MacBook Pro" is four panel sizes across several scaling settings, and
    the physical panel is irrelevant — the logical size is what decides whether
    a toolbar fits. Measured in TODO.md: at 1280x800 the toolbar wanted 2566px
    and had 1280.
    """
    import re
    ctx = main_window._report_context()
    assert ctx["app_version"]
    assert ctx["os"]
    # "1512 x 982 at 2x", optionally "(2 displays)". The scale factor is half
    # the answer: 1512 logical at 2x and 1512 logical at 1x are the same
    # problem for a toolbar, and a reporter who quotes 3024 has told us nothing.
    assert re.fullmatch(r"\d+ x \d+ at [\d.]+x( \(\d+ displays\))?", ctx["screen"]), \
        f"screen reads {ctx['screen']!r}"
    assert re.fullmatch(r"\d+ x \d+", ctx["window_size"]), \
        f"window reads {ctx['window_size']!r}"


def test_the_window_size_is_separate_from_the_screen(main_window):
    """A maximised window on a big display and a small window on the same
    display are different reports, and only one of them is our problem."""
    main_window.resize(900, 700)
    ctx = main_window._report_context()
    assert ctx["window_size"] == "900 x 700"
    assert ctx["window_size"] != ctx["screen"]


def test_it_OPENS_a_page_and_sends_nothing(main_window, monkeypatch):
    """NOTHING leaves the machine here.

    The browser opens a form the person reads and submits themselves, so every
    value is visible before it goes and any of it can be deleted — the log
    especially, which contains file paths and therefore folder names and
    therefore possibly their own name. Same principle as the telemetry prompt.
    An app that quietly posted a diagnostic bundle would be a different product
    from the one the privacy page describes.
    """
    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))

    posted = []
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: posted.append(a) or (_ for _ in ()).throw(
                            AssertionError("the app must not send the report itself")))

    main_window._report_problem()
    assert len(opened) == 1
    assert not posted, "no network request may be made from the app"

    url = urlparse(opened[0])
    assert url.scheme == "https" and url.netloc == "nocturne.stehn.com"
    assert url.path == "/support.html"
    q = parse_qs(url.query)
    assert q["app_version"][0]
    assert q["screen"][0]


def test_an_empty_field_is_omitted_rather_than_sent_blank(main_window, monkeypatch):
    """A fresh session has no diagnostic log. Sending `log=` would put an empty
    box in front of the reporter suggesting they failed to provide something."""
    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    main_window._last_diagnostic = ""
    main_window._report_problem()
    assert "log=" not in opened[0]
