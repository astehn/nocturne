"""One Nocturne per user on Windows and Linux: a file opened while Nocturne runs
goes to the running window rather than starting a second one.

macOS already does this — a document opened while the app runs arrives as a
QFileOpenEvent (open_requests.py) — so nothing here runs there.

The second launch connects BEFORE it does anything else (no log, no settings,
no window), hands its path over, and exits. The running instance feeds the path
through OpenRequests.request, the door a macOS open-document event uses, so
busy, unsaved changes and unknown file types are decided in one place.

The wire: on connect the server writes `NOCTURNE <pid>\\n`; the client checks
the other end is this user's, lets that pid take the foreground, sends
`{"paths": [...], "sent": <wall clock>, "window_ms": <patience>,
"activation": {...}}\\n` and waits for `OK\\n` until `sent + window_ms`.
The server answers and acts only while the request is younger than that window
less a margin, so a sender that gave up and opened the file itself is never
doubled. Anything else and the launch goes ahead on its own: a hung or foreign
server costs a second window, never a lost file.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import stat
import sys
import time
import traceback

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

# What a Linux launcher hands the process it starts so that process may take
# the focus. Wayland (xdg-activation) refuses focus without the token; Qt reads
# XDG_ACTIVATION_TOKEN from the environment when a window asks to activate.
_ACTIVATION_KEYS = ("XDG_ACTIVATION_TOKEN", "DESKTOP_STARTUP_ID")

_HELLO = b"NOCTURNE"
_MAX_REQUEST = 64 * 1024

# A first launch must not wait: with nobody listening the connect fails at
# once. The hello can wait on a first instance still building its window
# (~1 s of blocked event loop at startup, measured 2026-08-23).
CONNECT_MS = 1000
HELLO_MS = 5000
ACK_MS = 5000
# A connection that has said nothing by now is dropped: a request is one line.
IDLE_MS = 5000
# Two first launches at once wait at most this long for each other.
LOCK_MS = 3000

# Things that went wrong before the session log existed, written once it does.
_failures: list[str] = []

_stat = os.stat


def enabled(argv: list[str], *, platform: str = sys.platform, environ=os.environ) -> bool:
    if platform == "darwin" and environ.get(_TEST_ENV) != "1":
        return False
    if any(a in _HEADLESS_FLAGS for a in argv[1:]):
        return False
    import multiprocessing
    return multiprocessing.parent_process() is None


def server_name(home: str | None = None, user: str | None = None, *,
                platform: str = sys.platform, environ=os.environ) -> str | None:
    """Per user, home and desktop session: a pipe name is machine-wide on
    Windows, and a throwaway home (tests, the self tests) must not find the
    user's window. On Linux in a directory only this user can enter — never
    bare /tmp, where another account could take the name first and be sent
    this user's paths. None when no such directory can be had."""
    home = home if home is not None else os.path.expanduser("~")
    if user is None:
        try:
            user = getpass.getuser()
        except Exception:                  # noqa: BLE001 — no user name is not a reason to fail
            user = ""
    key = "\0".join((os.path.normcase(os.path.realpath(home)), user,
                     _session(platform, environ)))
    name = "nocturne-" + hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()[:24]
    if not platform.startswith("linux"):
        return name
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if runtime and os.path.isdir(runtime):
        return os.path.join(runtime, name)
    private = _private_dir(environ.get("TMPDIR") or "/tmp")
    return os.path.join(private, name) if private else None


def _session(platform: str, environ) -> str:
    if platform == "win32":
        return _windows_session()
    if platform.startswith("linux"):
        return environ.get("WAYLAND_DISPLAY", "") + "|" + environ.get("DISPLAY", "")
    return ""


def _windows_session() -> str:
    try:
        import ctypes
        from ctypes import wintypes
        sid = wintypes.DWORD()
        k32 = ctypes.windll.kernel32
        if k32.ProcessIdToSessionId(k32.GetCurrentProcessId(), ctypes.byref(sid)):
            return str(sid.value)
    except Exception:                      # noqa: BLE001 — the name only gets less specific
        pass
    return ""


def _private_dir(base: str) -> str | None:
    d = os.path.join(base, f"nocturne-{os.getuid()}")
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return None
    try:
        st = os.lstat(d)
    except OSError:
        return None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        return None
    return d


def _activation(environ) -> dict[str, str]:
    return {k: environ[k] for k in _ACTIVATION_KEYS if environ.get(k)}


def _note_failure(where: str) -> None:
    _failures.append(f"single instance: {where} failed, carrying on without it\n"
                     + traceback.format_exc().rstrip())


def hand_over(argv: list[str], name: str | None = None, *, platform: str = sys.platform,
              environ=os.environ) -> bool:
    """True when a running Nocturne took this launch's file and this process
    should exit. A launch with no file is a second window, as before. Never
    raises: this runs before anything else, and must never stop a launch."""
    try:
        if not enabled(argv, platform=platform, environ=environ):
            return False
        path = path_from_argv(argv)
        if path is None:
            return False
        name = name or server_name(platform=platform, environ=environ)
        if name is None:
            return False
        return forward([path], name, activation=_activation(environ))
    except Exception:                      # noqa: BLE001 — see docstring
        _note_failure("hand-over")
        return False


def forward(paths: list[str], name: str, *, hello_ms: int = HELLO_MS,
            ack_ms: int = ACK_MS, activation: dict | None = None) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    if sys.platform != "win32" and not _owned_by_me(name):
        return False
    sock = QLocalSocket()
    sock.connectToServer(name)
    try:
        if not sock.waitForConnected(CONNECT_MS):
            return False
        hello = _read_line(sock, hello_ms)
        parts = hello.split() if hello else []
        if len(parts) != 2 or parts[0] != _HELLO or not parts[1].isdigit():
            return False
        pid = int(parts[1])
        if sys.platform == "win32":
            pid = _pipe_server_pid_if_mine(sock)
            if pid is None:
                return False
        _allow_foreground(pid)
        sent, t0 = time.time(), time.monotonic()
        sock.write(json.dumps({"paths": paths, "sent": sent, "window_ms": ack_ms,
                               "activation": activation or {}}).encode("utf-8") + b"\n")
        if not sock.waitForBytesWritten(ack_ms):
            return False
        left = ack_ms - int((time.monotonic() - t0) * 1000)
        return _read_line(sock, left) == b"OK"
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


def _socket_path(name: str) -> str:
    if os.path.isabs(name):
        return name
    from PySide6.QtCore import QDir
    return os.path.join(QDir.tempPath(), name)


def _owned_by_me(name: str) -> bool:
    """A socket file someone else made is not sent this user's paths."""
    try:
        st = _stat(_socket_path(name))
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def _process_user_sid(pid: int | None = None) -> str | None:
    """The account a process runs as (None: this one), as an S-1-… string."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    query_limited, token_query, token_user = 0x1000, 0x0008, 1
    proc = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(query_limited, False, pid)
    if not proc:
        return None
    token = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(proc, token_query, ctypes.byref(token)):
            return None
        try:
            size = wintypes.DWORD()
            adv.GetTokenInformation(token, token_user, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(token, token_user, buf, size, ctypes.byref(size)):
                return None
            # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is the PSID.
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(psid, ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                k32.LocalFree(text)
        finally:
            k32.CloseHandle(token)
    finally:
        if pid is not None:
            k32.CloseHandle(proc)


def _pipe_server_pid_if_mine(sock) -> int | None:
    """The process at the other end of the pipe, if it runs as this user. A
    pipe name is machine-wide; another account could have created it first."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE,
                                                    ctypes.POINTER(wintypes.ULONG)]
        pid = wintypes.ULONG()
        if not k32.GetNamedPipeServerProcessId(int(sock.socketDescriptor()), ctypes.byref(pid)):
            return None
        mine = _process_user_sid(None)
        if mine is None or _process_user_sid(pid.value) != mine:
            return None
        return pid.value
    except Exception:                      # noqa: BLE001 — unverifiable is not trusted
        return None


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


def _fresh(sent: float, window_ms: float) -> bool:
    """Still inside the sender's patience, with room for the OK to reach it.
    Past that the sender has opened the file itself."""
    window = min(max(window_ms, 0), ACK_MS) / 1000
    margin = min(1.0, window / 2)
    age = time.time() - sent
    return -1.0 < age < window - margin


def _parse(line: bytes):
    msg = json.loads(line.decode("utf-8"))
    paths, sent, window = msg["paths"], msg["sent"], msg["window_ms"]
    activation = msg.get("activation", {})
    number = (int, float)
    if (not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths)
            or not isinstance(sent, number) or isinstance(sent, bool)
            or not isinstance(window, number) or isinstance(window, bool)
            or not isinstance(activation, dict)
            or not all(isinstance(v, str) for v in activation.values())):
        raise TypeError("malformed request")
    return paths, float(sent), float(window), activation


class Server(QObject):
    """`on_path(path)` once per path, on the UI thread."""

    def __init__(self, name: str, on_path, parent=None, *, platform: str = sys.platform) -> None:
        from PySide6.QtNetwork import QLocalServer
        super().__init__(parent)
        self._name = name
        self._on_path = on_path
        self._platform = platform
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept)

    def listen(self) -> bool:
        if self._server.listen(self._name):
            return True
        # A crashed Nocturne can leave its socket file on Linux. Reached only
        # after serve() found nobody answering on it. (Qt 6 with
        # UserAccessOption renames its socket into place and so usually gets
        # past one by itself; this is for when it does not.)
        _remove_stale(self._name)
        return self._server.listen(self._name)

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        from PySide6.QtCore import QTimer
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            buf = bytearray()
            idle = QTimer(sock)
            idle.setSingleShot(True)
            idle.timeout.connect(sock.abort)
            idle.start(IDLE_MS)
            sock.readyRead.connect(lambda s=sock, b=buf, t=idle: self._read(s, b, t))
            sock.disconnected.connect(sock.deleteLater)
            sock.write(_HELLO + b" " + str(os.getpid()).encode() + b"\n")
            sock.flush()

    def _read(self, sock, buf: bytearray, idle) -> None:
        from PySide6.QtNetwork import QLocalSocket
        buf += bytes(sock.readAll())
        if b"\n" not in buf:
            if len(buf) > _MAX_REQUEST:
                idle.stop()
                sock.abort()
            return
        idle.stop()
        line = bytes(buf).split(b"\n", 1)[0]
        buf.clear()
        try:
            paths, sent, window, activation = _parse(line)
        except (ValueError, KeyError, TypeError, AttributeError):
            sock.abort()
            return
        # Not for a sender that has given up and opened the file itself.
        if (not _fresh(sent, window)
                or sock.state() != QLocalSocket.LocalSocketState.ConnectedState):
            sock.abort()
            return
        sock.write(b"OK\n")
        sock.flush()
        sock.disconnectFromServer()
        self._apply_activation(activation)
        for p in paths:
            self._on_path(p)

    def _apply_activation(self, activation: dict) -> None:
        """Before on_path: the open that follows raises and activates the
        window, and Qt's Wayland backend reads the token from the environment
        at that moment (then unsets it)."""
        if not self._platform.startswith("linux"):
            return
        for k in _ACTIVATION_KEYS:
            v = activation.get(k)
            if isinstance(v, str) and v:
                os.environ[k] = v


def _lock_path(name: str) -> str:
    return _socket_path(name) + ".lock"


def _someone_listening(name: str) -> bool:
    """Any listener at all, even a hung one: taking the name from a live
    window makes it unreachable once this one quits (on Linux the socket file
    is renamed over and later deleted)."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    try:
        return sock.waitForConnected(CONNECT_MS)
    finally:
        sock.abort()


def argv_path_after_window(argv: list[str], *, platform: str = sys.platform,
                           environ=os.environ) -> str | None:
    """The launch's own file for main() to request once the window exists —
    unless serve() already requested it, before listening, so that a file
    forwarded during startup comes after it and is the one kept."""
    if enabled(argv, platform=platform, environ=environ):
        return None
    return path_from_argv(argv)


def serve(open_requests, argv: list[str], name: str | None = None, *,
          platform: str = sys.platform, environ=os.environ) -> Server | None:
    """The running instance's half. None where it does not apply, when a
    Nocturne already listens (a second window without a file), or if the
    name cannot be had — then each launch is its own window, as before.
    Never raises."""
    if not enabled(argv, platform=platform, environ=environ):
        return None
    from ..core import sessionlog
    while _failures:
        sessionlog.write(_failures.pop(0))
    # Requested BEFORE listening: OpenRequests keeps only the latest, and a
    # file forwarded while this window is built is the later one. Requested
    # after, it would replace a file whose sender was told OK and has gone.
    own = path_from_argv(argv)
    if own:
        open_requests.request(own)
    try:
        from PySide6.QtCore import QLockFile
        name = name or server_name(platform=platform, environ=environ)
        if name is None:
            return None
        lock = QLockFile(_lock_path(name))
        locked = lock.tryLock(LOCK_MS)
        try:
            if _someone_listening(name):
                return None
            server = Server(name, open_requests.request, parent=open_requests,
                            platform=platform)
            if server.listen():
                return server
            server.close()
            return None
        finally:
            if locked:
                lock.unlock()
    except Exception:                      # noqa: BLE001 — never a reason not to start
        _note_failure("serve")
        while _failures:
            sessionlog.write(_failures.pop(0))
        return None
