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
    win.resize(1280, 760)

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
