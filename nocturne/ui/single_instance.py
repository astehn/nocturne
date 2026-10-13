"""One Nocturne per user on Windows and Linux: a file opened while Nocturne runs
goes to the running window rather than starting a second one.

macOS already does this — a document opened while the app runs arrives as a
QFileOpenEvent (open_requests.py) — so nothing here runs there.

The second launch connects BEFORE it does anything else (no log, no settings,
no window), hands its path over, and exits. The running instance feeds the path
through OpenRequests.request, the door a macOS open-document event uses, so
busy, unsaved changes and unknown file types are decided in one place.

The wire: on connect the server writes `NOCTURNE <pid>\\n`; the client lets that
pid take the foreground, sends `{"paths": [...]}\\n` and waits for `OK\\n`.
Anything else and the launch goes ahead on its own: a hung or foreign server
costs a second window, never a lost file.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import time

from PySide6.QtCore import QObject

from .open_requests import path_from_argv

# QtNetwork is imported where it is used: on macOS nothing here runs, and
# nothing there should load it.

# Headless runs of the same executable. A --stack-job child is handed paths
# of its own; forwarding them would open a background stack's files in the
# user's window.
_HEADLESS_FLAGS = ("--stack-job", "--check-network", "--check-codecs", "--check-tools")

# Lets the suite drive the real entry point on a Mac. Nothing sets it otherwise.
_TEST_ENV = "NOCTURNE_TEST_SINGLE_INSTANCE"

_HELLO = b"NOCTURNE"
_MAX_REQUEST = 64 * 1024

# A first launch must not wait: with nobody listening the connect fails at
# once. The hello can wait on a first instance still building its window
# (~1 s of blocked event loop at startup, measured 2026-08-23).
CONNECT_MS = 1000
HELLO_MS = 5000
ACK_MS = 5000


def enabled(argv: list[str], *, platform: str = sys.platform, environ=os.environ) -> bool:
    if platform == "darwin" and environ.get(_TEST_ENV) != "1":
        return False
    if any(a in _HEADLESS_FLAGS for a in argv[1:]):
        return False
    import multiprocessing
    return multiprocessing.parent_process() is None


def server_name(home: str | None = None, user: str | None = None, *,
                platform: str = sys.platform, environ=os.environ) -> str:
    """Per user AND per home: a pipe name is machine-wide on Windows, and a
    throwaway home (tests, the self tests) must not find the user's window.
    On Linux in the user's own runtime directory when there is one, not the
    shared /tmp, where another account could take the name first."""
    home = home if home is not None else os.path.expanduser("~")
    if user is None:
        try:
            user = getpass.getuser()
        except Exception:                  # noqa: BLE001 — no user name is not a reason to fail
            user = ""
    key = os.path.normcase(os.path.realpath(home)) + "\0" + user
    name = "nocturne-" + hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()[:24]
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if platform.startswith("linux") and runtime and os.path.isdir(runtime):
        return os.path.join(runtime, name)
    return name


def hand_over(argv: list[str], name: str | None = None, *, platform: str = sys.platform,
              environ=os.environ) -> bool:
    """True when a running Nocturne took this launch's file and this process
    should exit. A launch with no file is a second window, as before."""
    if not enabled(argv, platform=platform, environ=environ):
        return False
    path = path_from_argv(argv)
    if path is None:
        return False
    return forward([path], name or server_name())


def forward(paths: list[str], name: str, *, hello_ms: int = HELLO_MS,
            ack_ms: int = ACK_MS) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    try:
        if not sock.waitForConnected(CONNECT_MS):
            return False
        hello = _read_line(sock, hello_ms)
        parts = hello.split() if hello else []
        if len(parts) != 2 or parts[0] != _HELLO or not parts[1].isdigit():
            return False
        _allow_foreground(int(parts[1]))
        sock.write(json.dumps({"paths": paths}).encode("utf-8") + b"\n")
        if not sock.waitForBytesWritten(ack_ms):
            return False
        return _read_line(sock, ack_ms) == b"OK"
    finally:
        sock.abort()


def _read_line(sock, ms: int) -> bytes | None:
    buf = b""
    deadline = time.monotonic() + ms / 1000
    while b"\n" not in buf:
        left = int((deadline - time.monotonic()) * 1000)
        if left <= 0:
            return None
        if sock.bytesAvailable() == 0 and not sock.waitForReadyRead(left):
            return None
        buf += bytes(sock.readAll())
    return buf.split(b"\n", 1)[0].strip()


def _allow_foreground(pid: int) -> None:
    """Windows lets only the process the user just launched take the
    foreground; without this the running window's activateWindow() only
    flashes its taskbar button."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(pid)
    except Exception:                      # noqa: BLE001 — focus is a nicety
        pass


def _remove_stale(name: str) -> None:
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(name)


class Server(QObject):
    """`on_path(path)` once per path, on the UI thread."""

    def __init__(self, name: str, on_path, parent=None) -> None:
        from PySide6.QtNetwork import QLocalServer
        super().__init__(parent)
        self._name = name
        self._on_path = on_path
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        if self._server.listen(self._name):
            return True
        # A crashed Nocturne can leave its socket file on Linux. Reached only
        # after hand_over found nobody answering on it. (Qt 6 with
        # UserAccessOption renames its socket into place and so usually gets
        # past one by itself; this is for when it does not.)
        _remove_stale(self._name)
        return self._server.listen(self._name)

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            buf = bytearray()
            sock.readyRead.connect(lambda s=sock, b=buf: self._read(s, b))
            sock.disconnected.connect(sock.deleteLater)
            sock.write(_HELLO + b" " + str(os.getpid()).encode() + b"\n")
            sock.flush()

    def _read(self, sock, buf: bytearray) -> None:
        buf += bytes(sock.readAll())
        if b"\n" not in buf:
            if len(buf) > _MAX_REQUEST:
                sock.abort()
            return
        line = bytes(buf).split(b"\n", 1)[0]
        buf.clear()
        try:
            paths = json.loads(line.decode("utf-8"))["paths"]
            paths = [p for p in paths if isinstance(p, str) and p]
        except (ValueError, KeyError, TypeError):
            sock.abort()
            return
        sock.write(b"OK\n")
        sock.flush()
        sock.disconnectFromServer()
        for p in paths:
            self._on_path(p)


def serve(open_requests, argv: list[str]) -> Server | None:
    """The running instance's half. None where it does not apply, or if the
    name cannot be had — then each launch is its own window, as before."""
    if not enabled(argv):
        return None
    server = Server(server_name(), open_requests.request, parent=open_requests)
    return server if server.listen() else None
