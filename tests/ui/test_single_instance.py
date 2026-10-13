"""A file opened while Nocturne runs goes to the running window (Windows, Linux).

Andreas, 2026-10-12, on Windows: with Nocturne open he chose Open with ▸
Nocturne on a .fits, and a second window came up showing the start screen. The
picture HAD loaded — in a second process whose window came up behind the
first, at exactly its place (both restore the same saved geometry), and
Windows left the old one active. Reproduced on the VM with Explorer as the
launcher, 2026-10-13; whether a new window wins the foreground varied run to
run. One window per user removes the question of which one it went to.
"""
import json
import multiprocessing
import os
import pathlib
import socket
import stat
import subprocess
import sys
import threading
import time

import pytest
from PySide6.QtCore import QDir, QLockFile, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from nocturne.core import sessionlog
from nocturne.ui import single_instance as si
from nocturne.ui.open_requests import OpenRequests

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Win(QObject):
    def __init__(self):
        super().__init__()
        self.opened = []

    def open_requested(self, path):
        self.opened.append(path)


def _fits(tmp_path, name="m31.fits"):
    p = tmp_path / name
    p.write_bytes(b"SIMPLE  =                    T" + b" " * 2850)
    return str(p)


def _in_thread(fn):
    """For a client that needs no Python on the server side. A blocking
    QLocalSocket call holds the GIL, so a Python slot in this thread cannot
    answer a client in another one — those go through _client or _raw."""
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn()), daemon=True)
    t.start()
    return t, out


_CLIENT = """
import json, sys
from nocturne.ui import single_instance as si
si._allow_foreground = lambda pid: print("allow", pid)
ack = int(sys.argv[3]) if len(sys.argv) > 3 else si.ACK_MS
print("result", si.forward(json.loads(sys.argv[1]), sys.argv[2], ack_ms=ack))
"""

# The launcher's real entry, with this process's environment, as a Linux one.
_HAND_OVER = """
import sys
from nocturne.ui import single_instance as si
print("result", si.hand_over(["nocturne", sys.argv[1]], sys.argv[2], platform="linux"))
"""


def _spawn(qtbot, args, env=None):
    proc = subprocess.Popen([sys.executable, *args], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        qtbot.waitUntil(lambda: proc.poll() is not None, timeout=60000)
        return proc.stdout.read().decode(errors="replace") + f"\nexit {proc.returncode}"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)


def _client(qtbot, paths, name, *extra):
    """The sending launch, as a process of its own (as it is for real)."""
    return _spawn(qtbot, ["-c", _CLIENT, json.dumps(paths), name, *extra])


def _line(paths, *, sent=None, window=5000, **extra):
    msg = {"paths": paths, "sent": time.time() if sent is None else sent, "window_ms": window}
    msg.update(extra)
    return json.dumps(msg).encode() + b"\n"


def _raw(qtbot, name, payload):
    """A client in THIS thread's event loop, so the server's slots run while it
    waits. Returns all the server said before the connection ended."""
    s = QLocalSocket()
    got = bytearray()
    s.readyRead.connect(lambda: got.extend(bytes(s.readAll())))
    s.connectToServer(name)
    qtbot.waitUntil(lambda: b"\n" in got, timeout=5000)        # the hello
    s.write(payload)
    s.flush()
    qtbot.waitUntil(lambda: s.state() == QLocalSocket.LocalSocketState.UnconnectedState,
                    timeout=8000)
    return bytes(got)


@pytest.fixture
def name(tmp_path):
    n = si.server_name(home=str(tmp_path / "home"))
    yield n
    QLocalServer.removeServer(n)


@pytest.fixture
def servers():
    made = []

    def make(*args, **kw):
        s = si.Server(*args, **kw)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


@pytest.fixture
def requests_to(qtbot):
    made = []

    def make(attach=True):
        req = OpenRequests(QApplication.instance())
        win = _Win()
        if attach:
            req.attach(win)
        made.append(req)
        return req, win
    yield make
    for req in made:
        QApplication.instance().removeEventFilter(req)


# --- who takes part ---------------------------------------------------------
def test_never_on_macos_where_the_system_routes_documents_itself():
    assert si.enabled(["nocturne", "/x/a.fits"], platform="darwin", environ={}) is False
    assert si.enabled(["nocturne", "/x/a.fits"], platform="win32", environ={}) is True
    assert si.enabled(["nocturne", "/x/a.fits"], platform="linux", environ={}) is True


@pytest.mark.parametrize("flag", ["--stack-job", "--check-network", "--check-codecs",
                                  "--check-tools"])
def test_headless_children_never_take_part(flag):
    """A --stack-job child is handed a path; forwarding it would turn a
    background stack into an open request in the user's window."""
    assert si.enabled(["Nocturne.exe", flag, "/x/a.fits"], platform="win32", environ={}) is False


def _enabled_in_child(q):
    q.put(si.enabled(["nocturne", "/x/a.fits"], platform="win32", environ={}))


def test_a_multiprocessing_worker_never_takes_part():
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_enabled_in_child, args=(q,))
    p.start()
    try:
        assert q.get(timeout=60) is False
    finally:
        p.join(30)
        if p.is_alive():
            p.kill()


def test_the_name_is_per_home_and_stable(tmp_path):
    a = si.server_name(home=str(tmp_path / "a"), user="u")
    assert a == si.server_name(home=str(tmp_path / "a"), user="u")
    assert a != si.server_name(home=str(tmp_path / "b"), user="u")
    assert a != si.server_name(home=str(tmp_path / "a"), user="v")
    assert a.startswith("nocturne-") and len(a) < 48


def test_on_linux_the_name_is_per_display(tmp_path):
    """Two desktops of one user (a second seat, or X and Wayland side by side)
    each get their own window, not each other's."""
    run = tmp_path / "run"
    run.mkdir()
    base = {"XDG_RUNTIME_DIR": str(run)}
    names = {si.server_name(home="/h", user="u", platform="linux", environ=dict(base, **e))
             for e in ({"DISPLAY": ":0"}, {"DISPLAY": ":1"}, {"WAYLAND_DISPLAY": "wayland-0"},
                       {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"})}
    assert len(names) == 4


def test_on_windows_the_name_is_per_session(monkeypatch):
    """A pipe name is machine-wide: a second user's session (fast user
    switching, RDP) under the same account must not reach this window."""
    monkeypatch.setattr(si, "_windows_session", lambda: "1")
    a = si.server_name(home="C:/h", user="u", platform="win32", environ={})
    monkeypatch.setattr(si, "_windows_session", lambda: "2")
    assert a != si.server_name(home="C:/h", user="u", platform="win32", environ={})


def test_on_linux_the_socket_lives_in_the_users_runtime_dir(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    n = si.server_name(home="/h", user="u", platform="linux", environ={"XDG_RUNTIME_DIR": str(run)})
    assert os.path.dirname(n) == str(run)
    assert os.path.basename(n).startswith("nocturne-")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_without_a_runtime_dir_the_socket_goes_in_a_private_dir_not_bare_tmp(tmp_path):
    """Bare /tmp is shared: another account could create the name first and
    receive this user's file paths."""
    n = si.server_name(home="/h", user="u", platform="linux", environ={"TMPDIR": str(tmp_path)})
    d = os.path.dirname(n)
    assert d == os.path.join(str(tmp_path), f"nocturne-{os.getuid()}")
    st = os.lstat(d)
    assert stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and st.st_mode & 0o077 == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_private_dir_someone_else_can_enter_is_not_used(tmp_path):
    d = tmp_path / f"nocturne-{os.getuid()}"
    d.mkdir()
    d.chmod(0o777)
    assert si.server_name(home="/h", user="u", platform="linux",
                          environ={"TMPDIR": str(tmp_path)}) is None


def test_macos_never_loads_qtnetwork_for_this(tmp_path):
    """Nothing here runs on macOS; importing it there must not pull QtNetwork in.
    With a real .fits, so it is the platform gate that stops it, not a missing
    file."""
    fits = _fits(tmp_path)
    code = ("import sys; from nocturne.ui import single_instance as si; "
            "from nocturne.ui.open_requests import path_from_argv; "
            f"assert path_from_argv(['n', {fits!r}]) is not None; "
            f"assert si.hand_over(['n', {fits!r}], platform='darwin', environ={{}}) is False; "
            "print('PySide6.QtNetwork' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=120)
    assert out.stdout.strip() == "False", out.stdout + out.stderr


# --- the hand-over ----------------------------------------------------------
def test_a_forwarded_file_goes_through_the_open_request_door(qtbot, name, tmp_path, requests_to,
                                                               servers):
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen()
    fits = _fits(tmp_path)
    out = _client(qtbot, [fits], name)
    assert "result True" in out, out
    qtbot.waitUntil(lambda: win.opened == [fits], timeout=10000)


def test_the_server_says_which_process_it_is(qtbot, name, tmp_path, requests_to, servers):
    """The sender lets THAT process take the foreground (Windows refuses a
    background process otherwise and only flashes the taskbar)."""
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen()
    out = _client(qtbot, [_fits(tmp_path)], name)
    assert f"allow {os.getpid()}" in out, out


def test_nothing_running_means_no_hand_over(name, tmp_path):
    t0 = time.monotonic()
    assert si.forward([_fits(tmp_path)], name) is False
    assert time.monotonic() - t0 < 2.0, "a first launch must not wait for nobody"


def test_a_launch_without_a_file_is_a_normal_second_window(qtbot, name, tmp_path, requests_to,
                                                           servers):
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen()
    connected = []
    server._server.newConnection.connect(lambda: connected.append(1))
    for argv in (["nocturne"], ["nocturne", "--no-splash"],
                 ["nocturne", str(tmp_path / "missing.fits")]):
        assert si.hand_over(argv, name, platform="win32", environ={}) is False
    qtbot.wait(100)
    assert connected == [] and win.opened == []


def test_a_server_that_never_answers_is_not_waited_on_forever(qtbot, name, tmp_path):
    """Connected but silent — hung, or not Nocturne — and the launch goes ahead
    on its own rather than handing its file into nowhere."""
    mute = QLocalServer()
    assert mute.listen(name)
    try:
        t, out = _in_thread(lambda: si.forward([_fits(tmp_path)], name, hello_ms=300, ack_ms=300))
        qtbot.waitUntil(lambda: "r" in out, timeout=5000)
        assert out["r"] is False
    finally:
        mute.close()


def test_a_hand_over_that_is_never_confirmed_is_not_counted(qtbot, name, tmp_path):
    """Said hello, took the request, never said OK: the launch opens the file
    itself rather than trust that it arrived."""
    held = []
    half = QLocalServer()

    def hello():
        sock = half.nextPendingConnection()
        held.append(sock)
        sock.write(b"NOCTURNE 1\n")
        sock.flush()
    half.newConnection.connect(hello)
    assert half.listen(name)
    try:
        out = _client(qtbot, [_fits(tmp_path)], name, "500")
        assert "result False" in out, out
    finally:
        half.close()


def test_a_name_that_cannot_be_had_is_cleared_once_and_retried(name, monkeypatch, servers):
    server = servers(name, lambda p: None)
    real = server._server
    tries, removed = [], []

    class _Refuses:
        def listen(self, n):
            tries.append(n)
            return len(tries) > 1

        def close(self):
            real.close()
    server._server = _Refuses()
    monkeypatch.setattr(si, "_remove_stale", removed.append)
    assert server.listen() is True
    assert removed == [name] and tries == [name, name]


# --- what the server accepts ------------------------------------------------
def test_a_well_formed_request_through_the_raw_client_is_opened(qtbot, name, tmp_path,
                                                                requests_to, servers):
    """The control for the garbage cases below: the same client, a good line,
    and the server does answer and open — so their silence is the parser's."""
    req, win = requests_to()
    assert servers(name, req.request).listen()
    fits = _fits(tmp_path)
    said = _raw(qtbot, name, _line([fits]))
    assert said.endswith(b"OK\n"), said
    qtbot.waitUntil(lambda: win.opened == [fits], timeout=5000)


@pytest.mark.parametrize("payload", [
    b"{not json\n",
    b"[1, 2]\n",
    b"\xff\xfe\n",
    _line("/x/a.fits"),               # a str, which must not be read char by char
    _line(["/x/a.fits", 3]),
    _line(["/x/a.fits"], sent="now"),
    _line(["/x/a.fits"], activation=["XDG_ACTIVATION_TOKEN"]),
    b'{"paths": ["/x/a.fits"]}\n',    # no send time: cannot tell if its sender gave up
], ids=["json", "list", "bytes", "str-paths", "int-path", "str-sent", "list-activation", "no-sent"])
def test_garbage_from_a_client_opens_nothing(qtbot, name, requests_to, servers, payload):
    req, win = requests_to()
    assert servers(name, req.request).listen()
    said = _raw(qtbot, name, payload)
    assert b"OK" not in said, said
    qtbot.wait(50)
    assert win.opened == []


def test_an_idle_connection_is_dropped(qtbot, name, requests_to, servers, monkeypatch):
    """A client that connects and says nothing must not hold a socket open in
    the running window for ever."""
    monkeypatch.setattr(si, "IDLE_MS", 300)
    req, win = requests_to()
    assert servers(name, req.request).listen()
    s = QLocalSocket()
    s.connectToServer(name)
    qtbot.waitUntil(lambda: s.state() == QLocalSocket.LocalSocketState.ConnectedState, timeout=5000)
    qtbot.waitUntil(lambda: s.state() == QLocalSocket.LocalSocketState.UnconnectedState,
                    timeout=3000)


def test_a_request_older_than_its_senders_patience_is_not_acted_on(qtbot, name, tmp_path,
                                                                  requests_to, servers):
    """Its sender has already opened the file itself; acting too would open it
    twice."""
    req, win = requests_to()
    assert servers(name, req.request).listen()
    said = _raw(qtbot, name, _line([_fits(tmp_path)], sent=time.time() - 4.5, window=5000))
    assert b"OK" not in said, said
    qtbot.wait(50)
    assert win.opened == []


def test_a_window_that_stalls_after_hello_does_not_open_the_file_twice(qtbot, name, tmp_path,
                                                                      requests_to, servers):
    """Hello sent, then the UI thread blocks past the sender's patience: the
    sender opens the file itself, so the running window must not."""
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen()
    # After Server._accept has written the hello (slots run in connect order).
    server._server.newConnection.connect(lambda: time.sleep(1.5))
    fits = _fits(tmp_path)
    out = _client(qtbot, [fits], name, "500")
    qtbot.wait(500)
    sender_opened = "result False" in out
    assert sender_opened != (win.opened == [fits]), (out, win.opened)
    if sys.platform != "win32":
        # Here the hello is written before the stall, so this is the case
        # under test, not a lucky ordering that never reached it.
        assert sender_opened, out


# --- Linux focus ------------------------------------------------------------
def test_only_the_activation_variables_are_carried():
    env = {"XDG_ACTIVATION_TOKEN": "tok", "DESKTOP_STARTUP_ID": "sid", "PATH": "/bin", "HOME": "/h"}
    assert si._activation(env) == {"XDG_ACTIVATION_TOKEN": "tok", "DESKTOP_STARTUP_ID": "sid"}
    assert si._activation({}) == {}


def test_the_launchers_focus_token_reaches_the_window_before_it_raises(qtbot, name, tmp_path,
                                                                        requests_to, servers,
                                                                        monkeypatch):
    """Wayland gives focus only to a window that presents the token its
    launcher was handed; Qt reads it from the environment when it activates."""
    for k in si._ACTIVATION_KEYS:
        monkeypatch.delenv(k, raising=False)
    seen = []
    server = servers(name, lambda p: seen.append((p, os.environ.get("XDG_ACTIVATION_TOKEN"),
                                                  os.environ.get("DESKTOP_STARTUP_ID"))),
                     platform="linux")
    assert server.listen()
    fits = _fits(tmp_path)
    env = dict(os.environ, XDG_ACTIVATION_TOKEN="tok-123", DESKTOP_STARTUP_ID="sid-9")
    out = _spawn(qtbot, ["-c", _HAND_OVER, fits, name], env=env)
    assert "result True" in out, out
    qtbot.waitUntil(lambda: seen == [(fits, "tok-123", "sid-9")], timeout=5000)


def test_activation_variables_are_not_set_off_linux(qtbot, name, tmp_path, requests_to, servers,
                                                    monkeypatch):
    for k in si._ACTIVATION_KEYS:
        monkeypatch.delenv(k, raising=False)
    opened = []
    assert servers(name, opened.append, platform="win32").listen()
    said = _raw(qtbot, name, _line([_fits(tmp_path)], activation={"XDG_ACTIVATION_TOKEN": "t"}))
    assert said.endswith(b"OK\n")
    qtbot.waitUntil(lambda: len(opened) == 1, timeout=5000)
    assert "XDG_ACTIVATION_TOKEN" not in os.environ


# --- who is on the other end ------------------------------------------------
@pytest.mark.skipif(sys.platform == "win32", reason="a socket file's owner")
def test_a_socket_owned_by_another_account_is_not_sent_to(qtbot, name, tmp_path, requests_to,
                                                          servers, monkeypatch):
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen()
    connected = []
    server._server.newConnection.connect(lambda: connected.append(1))
    real = os.stat

    class _Theirs:
        def __init__(self, st):
            self.st_mode, self.st_uid = st.st_mode, os.getuid() + 1
    monkeypatch.setattr(si, "_stat", lambda p: _Theirs(real(p)))
    t, out = _in_thread(lambda: si.forward([_fits(tmp_path)], name))
    qtbot.waitUntil(lambda: "r" in out, timeout=5000)
    assert out["r"] is False
    qtbot.wait(100)
    assert connected == [] and win.opened == []


@pytest.mark.skipif(sys.platform == "win32", reason="a socket file's owner")
def test_a_name_that_is_not_a_socket_is_not_sent_to(name, tmp_path, monkeypatch):
    class _File:
        def __init__(self):
            self.st_mode, self.st_uid = stat.S_IFREG | 0o600, os.getuid()
    monkeypatch.setattr(si, "_stat", lambda p: _File())
    assert si._owned_by_me(name) is False


@pytest.mark.skipif(sys.platform != "win32", reason="named pipes")
def test_on_windows_the_pipe_server_must_be_this_user(qtbot, name, tmp_path, requests_to, servers,
                                                      monkeypatch):
    req, win = requests_to()
    assert servers(name, req.request).listen()
    # The real check, on a real pipe: our own server is ours.
    s = QLocalSocket()
    s.connectToServer(name)
    assert s.waitForConnected(2000)
    try:
        assert si._pipe_server_pid_if_mine(s) == os.getpid()
    finally:
        s.abort()
    # And a server run by someone else is not sent to.
    real = si._process_user_sid
    monkeypatch.setattr(si, "_process_user_sid",
                        lambda pid=None: "S-1-5-21-other" if pid else real(None))
    t, out = _in_thread(lambda: si.forward([_fits(tmp_path)], name))
    qtbot.waitUntil(lambda: "r" in out, timeout=8000)
    assert out["r"] is False
    qtbot.wait(100)
    assert win.opened == []


# --- the running instance's half --------------------------------------------
def test_a_second_window_without_a_file_does_not_take_the_name(qtbot, name, tmp_path, requests_to,
                                                               servers):
    """B, launched with no file, used to listen on A's name: on Linux it
    renamed its socket over A's, and when B quit it deleted it — A unreachable,
    the original bug back. On Windows it added a second pipe server."""
    req, win = requests_to()
    assert servers(name, req.request).listen()
    req2, win2 = requests_to()
    second = si.serve(req2, ["nocturne"], name, platform="linux", environ={})
    try:
        assert second is None
    finally:
        if second is not None:
            second.close()          # B quits
    fits = _fits(tmp_path)
    out = _client(qtbot, [fits], name)
    assert "result True" in out, out
    qtbot.waitUntil(lambda: win.opened == [fits], timeout=10000)
    assert win2.opened == []


def test_the_first_window_does_take_the_name(qtbot, name, tmp_path, requests_to):
    req, win = requests_to()
    first = si.serve(req, ["nocturne"], name, platform="linux", environ={})
    try:
        assert first is not None
        fits = _fits(tmp_path)
        assert "result True" in _client(qtbot, [fits], name)
        qtbot.waitUntil(lambda: win.opened == [fits], timeout=10000)
    finally:
        if first is not None:
            first.close()


def test_the_check_and_the_listen_happen_under_one_lock(name, requests_to, monkeypatch):
    """Two first launches at once (a multi-select Open with) must not both
    find nobody and both listen."""
    held = []

    def probe(n):
        other = QLockFile(si._lock_path(n))
        held.append(not other.tryLock(0))
        return False
    monkeypatch.setattr(si, "_someone_listening", probe)
    req, win = requests_to()
    first = si.serve(req, ["nocturne"], name, platform="linux", environ={})
    try:
        assert held == [True]
    finally:
        if first is not None:
            first.close()


def test_a_lock_that_cannot_be_had_never_blocks_a_launch(name, requests_to, monkeypatch):
    monkeypatch.setattr(si, "LOCK_MS", 100)
    other = QLockFile(si._lock_path(name))
    assert other.tryLock(0)
    try:
        req, win = requests_to()
        t0 = time.monotonic()
        first = si.serve(req, ["nocturne"], name, platform="linux", environ={})
        assert time.monotonic() - t0 < 2.0
        assert first is not None
        first.close()
    finally:
        other.unlock()


def test_a_file_forwarded_while_the_first_window_is_starting_is_not_replaced(qtbot, name, tmp_path,
                                                                            requests_to):
    """The first launch's own file used to be requested after the window was
    built, replacing a file forwarded during startup — whose sender had
    already been told OK and exited."""
    mine, theirs = _fits(tmp_path, "mine.fits"), _fits(tmp_path, "theirs.fits")
    argv = ["nocturne", mine]
    req, win = requests_to(attach=False)            # the window is still being built
    server = si.serve(req, argv, name, platform="linux", environ={})
    try:
        assert server is not None
        assert "result True" in _client(qtbot, [theirs], name)
        qtbot.wait(50)
        # main(), once the window exists:
        late = si.argv_path_after_window(argv, platform="linux", environ={})
        if late:
            req.request(late)
        req.attach(win)
        qtbot.waitUntil(lambda: win.opened != [], timeout=5000)
        qtbot.wait(50)
        assert win.opened == [theirs]
    finally:
        if server is not None:
            server.close()


def test_with_nothing_forwarded_the_launchs_own_file_still_opens(qtbot, name, tmp_path, requests_to):
    mine = _fits(tmp_path, "mine.fits")
    argv = ["nocturne", mine]
    req, win = requests_to(attach=False)
    server = si.serve(req, argv, name, platform="linux", environ={})
    try:
        late = si.argv_path_after_window(argv, platform="linux", environ={})
        if late:
            req.request(late)
        req.attach(win)
        qtbot.waitUntil(lambda: win.opened == [mine], timeout=5000)
    finally:
        if server is not None:
            server.close()


def test_on_macos_the_launchs_own_file_is_requested_where_it_always_was(tmp_path):
    mine = _fits(tmp_path, "mine.fits")
    assert si.argv_path_after_window(["nocturne", mine], platform="darwin", environ={}) == mine


# --- never a reason not to start ----------------------------------------------
def test_a_failing_hand_over_is_a_normal_launch_and_is_logged_later(tmp_path, monkeypatch,
                                                                     requests_to, name):
    def boom(*a, **k):
        raise RuntimeError("pipe exploded")
    monkeypatch.setattr(si, "forward", boom)
    monkeypatch.setattr(si, "_failures", [])
    assert si.hand_over(["nocturne", _fits(tmp_path)], name, platform="linux", environ={}) is False
    monkeypatch.setattr(sessionlog, "_active", None)
    monkeypatch.setattr(sessionlog, "_started_at", None, raising=False)
    home = tmp_path / "home"
    assert sessionlog.start_session(home=str(home))
    req, win = requests_to()
    server = si.serve(req, ["nocturne"], name, platform="linux", environ={})
    if server is not None:
        server.close()
    assert "pipe exploded" in sessionlog.read_session(home=str(home))


def test_a_failing_serve_is_a_window_without_a_server(tmp_path, monkeypatch, requests_to, name):
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no sockets today")
    monkeypatch.setattr(si, "Server", _Boom)
    monkeypatch.setattr(si, "_failures", [])
    monkeypatch.setattr(sessionlog, "_active", None)
    monkeypatch.setattr(sessionlog, "_started_at", None, raising=False)
    home = tmp_path / "home"
    assert sessionlog.start_session(home=str(home))
    req, win = requests_to()
    assert si.serve(req, ["nocturne"], name, platform="linux", environ={}) is None
    assert "no sockets today" in sessionlog.read_session(home=str(home))


@pytest.mark.skipif(sys.platform == "win32", reason="a named pipe dies with its process")
def test_a_stale_socket_from_a_crashed_instance_does_not_block_startup(qtbot, name, tmp_path,
                                                                       requests_to, servers):
    path = os.path.join(QDir.tempPath(), name)
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)          # bound, never listening, closed: what a crash leaves
    s.close()
    assert os.path.exists(path)
    assert si.forward([_fits(tmp_path)], name) is False
    assert si._someone_listening(name) is False
    req, win = requests_to()
    server = servers(name, req.request)
    assert server.listen(), "the dead instance's socket kept the name"
    fits = _fits(tmp_path)
    assert "result True" in _client(qtbot, [fits], name)
    qtbot.waitUntil(lambda: win.opened == [fits], timeout=10000)


# --- for real: a second `python -m nocturne <file>` ------------------------------
def test_a_second_launch_hands_its_file_to_the_first_and_exits(qtbot, tmp_path):
    """The first instance here is this process: a real MainWindow behind a real
    server. The second is a real interpreter running the real entry point, in
    the same throwaway home, so it computes the same name."""
    from tests.ui.test_main_window import _make_fits, _window
    home = tmp_path / "home"
    home.mkdir()
    name = si.server_name(home=str(home))
    win = _window(qtbot, tmp_path)
    req = OpenRequests(QApplication.instance())
    req.attach(win)
    server = si.Server(name, req.request)
    try:
        assert server.listen()
        fits = _make_fits(tmp_path)
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                   QT_QPA_PLATFORM="offscreen", NOCTURNE_TEST_SINGLE_INSTANCE="1")
        out = _spawn(qtbot, ["-m", "nocturne", fits, "--no-splash"], env=env)
        assert out.endswith("exit 0"), out
        qtbot.waitUntil(lambda: win.project is not None, timeout=20000)
        # It left before starting anything: no session log rotated, no settings.
        assert not (home / ".nocturne").exists(), sorted(os.listdir(home / ".nocturne"))
    finally:
        server.close()
        QApplication.instance().removeEventFilter(req)


# --- where main() does it ---------------------------------------------------
def _main_source():
    return (ROOT / "nocturne" / "__main__.py").read_text(encoding="utf-8")


def test_the_hand_over_comes_before_anything_writes_to_the_home():
    """A forwarding launch must not rotate session.log under the running
    window, or the report it sends later carries the wrong session."""
    src = _main_source()
    at = src.index("single_instance.hand_over(")
    assert at < src.index("configure_logging()")
    assert at < src.index("sessionlog.start_session()")
    assert at < src.index("QApplication(sys.argv)")


def test_the_server_starts_beside_the_open_requests():
    src = _main_source()
    assert src.index("OpenRequests(app)") < src.index("single_instance.serve(") \
        < src.index("MainWindow(settings_path")


def test_main_asks_for_the_launchs_own_file_through_the_one_place_that_knows():
    src = _main_source()
    assert "argv_path = single_instance.argv_path_after_window(sys.argv)" in src
    assert "argv_path = path_from_argv(sys.argv)" not in src
