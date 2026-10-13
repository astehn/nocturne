"""A file opened while Nocturne runs goes to the running window (Windows, Linux).

Andreas, 2026-10-12, on Windows: with Nocturne open he chose Open with ▸
Nocturne on a .fits, and a second window came up showing the start screen. The
picture HAD loaded — in a second process whose window came up behind the
first, at exactly its place (both restore the same saved geometry), and
Windows left the old one active. Reproduced on the VM with Explorer as the
launcher, 2026-10-13; whether a new window wins the foreground varied run to
run. One window per user removes the question of which one it went to.
"""
import multiprocessing
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

import pytest
from PySide6.QtCore import QDir, QObject
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

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
    answer a client in another one — those go through _client below."""
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


def _client(qtbot, paths, name, *extra):
    """The sending launch, as a process of its own (as it is for real)."""
    import json
    proc = subprocess.Popen([sys.executable, "-c", _CLIENT, json.dumps(paths), name, *extra],
                            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    qtbot.waitUntil(lambda: proc.poll() is not None, timeout=60000)
    return proc.stdout.read().decode(errors="replace")


@pytest.fixture
def name(tmp_path):
    n = si.server_name(home=str(tmp_path / "home"))
    yield n
    QLocalServer.removeServer(n)


@pytest.fixture
def requests_to(qtbot):
    made = []

    def make():
        req = OpenRequests(QApplication.instance())
        win = _Win()
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


def test_the_name_is_per_home_and_stable(tmp_path):
    a = si.server_name(home=str(tmp_path / "a"), user="u")
    assert a == si.server_name(home=str(tmp_path / "a"), user="u")
    assert a != si.server_name(home=str(tmp_path / "b"), user="u")
    assert a != si.server_name(home=str(tmp_path / "a"), user="v")
    assert a.startswith("nocturne-") and len(a) < 48


def test_on_linux_the_socket_lives_in_the_users_runtime_dir(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    n = si.server_name(home="/h", user="u", platform="linux", environ={"XDG_RUNTIME_DIR": str(run)})
    assert os.path.dirname(n) == str(run)
    assert os.path.basename(n) == si.server_name(home="/h", user="u", platform="win32", environ={})
    # No runtime dir: Qt's own default place, by bare name.
    assert "/" not in si.server_name(home="/h", user="u", platform="linux", environ={})


def test_macos_never_loads_qtnetwork_for_this():
    """Nothing here runs on macOS; importing it there must not pull QtNetwork in."""
    code = ("import sys; from nocturne.ui import single_instance as si; "
            "assert si.hand_over(['n', 'nocturne/__main__.py'], platform='darwin', environ={}) is False; "
            "print('PySide6.QtNetwork' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=120)
    assert out.stdout.strip() == "False", out.stdout + out.stderr


# --- the hand-over ----------------------------------------------------------
def test_a_forwarded_file_goes_through_the_open_request_door(qtbot, name, tmp_path, requests_to):
    req, win = requests_to()
    server = si.Server(name, req.request)
    assert server.listen()
    fits = _fits(tmp_path)
    out = _client(qtbot, [fits], name)
    assert "result True" in out, out
    qtbot.waitUntil(lambda: win.opened == [fits], timeout=10000)


def test_the_server_says_which_process_it_is(qtbot, name, tmp_path, requests_to):
    """The sender lets THAT process take the foreground (Windows refuses a
    background process otherwise and only flashes the taskbar)."""
    req, win = requests_to()
    server = si.Server(name, req.request)
    assert server.listen()
    out = _client(qtbot, [_fits(tmp_path)], name)
    assert f"allow {os.getpid()}" in out, out


def test_nothing_running_means_no_hand_over(name, tmp_path):
    t0 = time.monotonic()
    assert si.forward([_fits(tmp_path)], name) is False
    assert time.monotonic() - t0 < 2.0, "a first launch must not wait for nobody"


def test_a_launch_without_a_file_is_a_normal_second_window(qtbot, name, tmp_path, requests_to):
    req, win = requests_to()
    server = si.Server(name, req.request)
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
    t, out = _in_thread(lambda: si.forward([_fits(tmp_path)], name, hello_ms=300, ack_ms=300))
    qtbot.waitUntil(lambda: "r" in out, timeout=5000)
    assert out["r"] is False
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
    out = _client(qtbot, [_fits(tmp_path)], name, "500")
    assert "result False" in out, out
    half.close()


def test_a_name_that_cannot_be_had_is_cleared_once_and_retried(name, monkeypatch):
    server = si.Server(name, lambda p: None)
    tries, removed = [], []

    class _Refuses:
        def listen(self, n):
            tries.append(n)
            return len(tries) > 1
    server._server = _Refuses()
    monkeypatch.setattr(si, "_remove_stale", removed.append)
    assert server.listen() is True
    assert removed == [name] and tries == [name, name]


def test_garbage_from_a_client_opens_nothing(qtbot, name, requests_to):
    from PySide6.QtNetwork import QLocalSocket
    req, win = requests_to()
    server = si.Server(name, req.request)
    assert server.listen()

    def junk():
        s = QLocalSocket()
        s.connectToServer(name)
        s.waitForConnected(2000)
        s.write(b"{not json\n")
        s.waitForBytesWritten(2000)
        s.waitForDisconnected(2000)
        return True
    t, out = _in_thread(junk)
    qtbot.waitUntil(lambda: "r" in out, timeout=5000)
    qtbot.wait(50)
    assert win.opened == []


@pytest.mark.skipif(sys.platform == "win32", reason="a named pipe dies with its process")
def test_a_stale_socket_from_a_crashed_instance_does_not_block_startup(qtbot, name, tmp_path, requests_to):
    path = os.path.join(QDir.tempPath(), name)
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)          # bound, never listening, closed: what a crash leaves
    s.close()
    assert os.path.exists(path)
    assert si.forward([_fits(tmp_path)], name) is False
    req, win = requests_to()
    server = si.Server(name, req.request)
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
        proc = subprocess.Popen([sys.executable, "-m", "nocturne", fits, "--no-splash"],
                                cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # The child blocks on us; keep this thread's event loop turning.
        qtbot.waitUntil(lambda: proc.poll() is not None, timeout=120000)
        out = proc.stdout.read().decode(errors="replace")
        assert proc.returncode == 0, out
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
