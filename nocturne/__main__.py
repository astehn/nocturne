import multiprocessing
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .core.applog import configure_logging
from .core.certs import configure_ssl
from .settings import autoconfigure_tools, resolve_settings_path
from .ui.fonts import load_bundled_fonts
from .ui.main_window import MainWindow
from .ui.splash import MIN_SPLASH_SECONDS, make_splash
from .ui.theme import apply_dark_theme

_ASSETS = Path(__file__).resolve().parent / "assets"


def _check_network() -> int:
    """Print where SSL will look for certificates and whether HTTPS works.

    Exit codes, so a release can be gated on the difference:

        0  HTTPS works.
        1  certificates are fine, the request failed anyway — no network, a
           captive portal, GitHub down. Not a build defect.
        2  NO USABLE CA BUNDLE. This build cannot do HTTPS on any machine and
           must not ship.

    The distinction matters because the failure being guarded against is silent:
    both features that need the network — the update check and SPCC's Gaia
    lookup — catch broadly and fail quiet, which is correct behaviour and is
    exactly why a 0.18.0 build ran all day against a 0.20.0 release without ever
    saying so. Blocking a release on a flaky connection would be a different
    kind of wrong.
    """
    import ssl
    import urllib.request

    from .core.certs import ca_path_is_usable

    paths = ssl.get_default_verify_paths()
    usable = ca_path_is_usable()
    print(f"frozen        : {getattr(sys, 'frozen', False)}")
    print(f"SSL_CERT_FILE : {os.environ.get('SSL_CERT_FILE') or '(unset)'}")
    for name, val in (("cafile", paths.cafile), ("capath", paths.capath)):
        print(f"{name:14}: {val}  exists={bool(val) and os.path.exists(val)}")
    print(f"usable CA path: {usable}")
    try:
        with urllib.request.urlopen("https://api.github.com/", timeout=15) as r:
            print(f"https probe   : OK (HTTP {r.status})")
        return 0
    except Exception as exc:                       # noqa: BLE001 - reporting tool
        print(f"https probe   : FAILED {type(exc).__name__}: {exc}")
        return 1 if usable else 2


# Height only. The WIDTH is asked of the window itself at startup — see
# preferred_size. Two hardcoded guesses at it were wrong in a row (1280 shipped
# for months; 1600 and 1760 were measured on the offscreen platform, which
# substitutes fonts and under-reported the toolbar by 642 points), so the number
# is no longer written down anywhere.
DEFAULT_HEIGHT = 1100

# Breathing room past the layout's exact requirement, so a one-point rounding
# difference does not push the last toolbar item into the overflow chevron.
_MARGIN = 24


def fit_to_screen(size: tuple[int, int], app) -> tuple[int, int]:
    """Shrink `size` to the available screen area, never grow it."""
    screen = app.primaryScreen()
    if screen is None:
        return size
    avail = screen.availableGeometry()
    return (min(size[0], avail.width()), min(size[1], avail.height()))


def preferred_size(win, app) -> tuple[int, int]:
    """Wide enough for the window's own layout, and no wider than the screen.

    The main toolbar carries 27 items and wants 2340 points with the fonts the
    app actually loads. Under the default 1280 only 16 of them were one click
    away; the rest lived behind the overflow chevron, on every screen, for every
    user, for months. Nobody reported it because a chevron is slow rather than
    broken.

    Asking the window rather than hardcoding a number is the point. Measured
    offscreen — which substitutes fonts and warns that it does — the same
    toolbar reports 1698, and a default set from that figure looks fixed while
    hiding a third of the tools. Andreas found both wrong versions by opening
    the app: "I cant even reach most of the tools."

    On a display too small for the layout the clamp wins and the chevron comes
    back. That is the small-screen problem, and this does not make it worse.
    """
    return fit_to_screen((win.sizeHint().width() + _MARGIN, DEFAULT_HEIGHT), app)


def window_size(argv: list[str]) -> tuple[int, int] | None:
    """`--size 1600x1000`, for captures that have to match each other.

    None means "no override" — the window is sized from its own layout instead.
    The website's screenshots are taken in sittings weeks apart, and a set shot
    at two window sizes cannot be topped up later without the new frames looking
    wrong beside the old. Anything unparseable falls back rather than refusing
    to start: a typo in a flag must not stop the app opening.
    """
    if "--size" not in argv:
        return None
    i = argv.index("--size")
    if i + 1 >= len(argv):
        return None
    try:
        w, h = argv[i + 1].lower().split("x")
        return max(640, int(w)), max(480, int(h))
    except ValueError:
        return None


def main() -> None:
    # BEFORE anything can open a connection. A bundle inherits the build
    # machine's OpenSSL cert path, which does not exist on a user's Mac, and
    # every HTTPS call then fails silently — see core/certs.py.
    configure_ssl()

    # A packaged app has no console, so the stacking phase timings had nowhere
    # to go: they were logged at INFO on a logger with no handler, and Python's
    # last-resort handler drops anything below WARNING. A 1233-frame drizzle ran
    # overnight on 2026-09-02, took ~4x the estimate, and left no record of
    # which phase was slow. ~/.nocturne/nocturne.log now holds it.
    configure_logging()

    # The check the packaged app could not do for itself. From source the build
    # machine's Homebrew cert store is present, so a bundle that works only here
    # looks perfectly healthy; the failure appears on a user's Mac as silence.
    # One command, no GUI, so a build can be verified before it ships:
    #     dist/Nocturne.app/Contents/MacOS/Nocturne --check-network
    if "--check-network" in sys.argv:
        raise SystemExit(_check_network())

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # After the QApplication (addApplicationFont needs one) and before any
    # window: a plate drawn before these families register silently substitutes
    # a system face, and nothing anywhere says so.
    load_bundled_fonts()

    icon_path = _ASSETS / "nocturne_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    apply_dark_theme(app)

    # Shown BEFORE any startup work, and timed from here — the point is that the
    # work happens while it is up. Built after apply_dark_theme so the caption
    # inherits the app palette. `--no-splash` exists because the person who
    # relaunches this app most is the one working on it.
    splash = None
    if "--no-splash" not in sys.argv:
        splash = make_splash(__version__)
        splash.show()
        app.processEvents()   # without this it is created but never painted

    # Before the window: a first run with the tools already installed should
    # need no trip to Settings at all. Only ever fills EMPTY paths.
    settings_path = resolve_settings_path()
    autoconfigure_tools(settings_path)

    win = MainWindow(settings_path=settings_path)
    requested = window_size(sys.argv)
    win.resize(*(fit_to_screen(requested, app) if requested
                 else preferred_size(win, app)))

    if splash is not None:
        # THE CLOCK STARTS HERE, once loading is finished — not when the splash
        # was shown.
        #
        # Building MainWindow blocks the event loop for ~1.1s of a ~2.3s
        # startup (measured 2026-08-23). Throughout that the splash is on
        # screen but FROZEN: never repainted, not composited, effectively not
        # there. Counting it as visible time left under a second of real
        # display and the splash appeared to flash and vanish — which is
        # exactly how the first attempt at this failed, and why "it was up for
        # two seconds" and "the user saw it for two seconds" are not the same
        # claim.
        #
        # So: finish loading, force one real paint, THEN hold the full minimum.
        splash.raise_()
        app.processEvents()

        # A nested QEventLoop, never time.sleep — sleeping blocks the event
        # loop, so the splash still would not paint and macOS shows a white
        # rectangle and then a beachball. A click ends the wait early.
        loop = QEventLoop()
        QTimer.singleShot(int(MIN_SPLASH_SECONDS * 1000), loop.quit)
        splash.dismissed.connect(loop.quit)
        loop.exec()
        splash.finish(win)

    win.show()

    if "--size" in sys.argv:
        # AFTER show, from a timer, so it reports the window that EXISTS. The
        # first version printed win.size() straight after resize() — which
        # echoes the request, not the result, and so agreed with itself while
        # Andreas was looking at a window that plainly did not match.
        def _report() -> None:
            s = win.size()
            print(f"window: {s.width()} x {s.height()} points "
                  f"({s.width() * win.devicePixelRatio():.0f} x "
                  f"{s.height() * win.devicePixelRatio():.0f} px when captured)")
        QTimer.singleShot(0, _report)

    sys.exit(app.exec())


if __name__ == "__main__":
    # MUST be the first thing, before Qt or anything else runs.
    #
    # Stacking registers frames in a process pool, and macOS SPAWNS rather than
    # forks — each worker re-imports the entry point. In a PyInstaller bundle
    # that means the app relaunching itself: a window per worker, recursively.
    # freeze_support() makes a spawned child run its task and exit instead.
    #
    # This fails ONLY in the shipped .app. A dev run and the whole test suite
    # are both silent about it, which is why it is pinned by a test that reads
    # this file rather than by anything that could observe the behaviour here.
    multiprocessing.freeze_support()
    main()
