import threading
from nocturne.core.tasks import CancelToken, Cancelled, set_ambient, clear_ambient, current

def test_check_raises_after_cancel():
    t = CancelToken()
    assert t.cancelled is False
    t.check()                 # no raise before cancel
    t.cancel()
    assert t.cancelled is True
    import pytest
    with pytest.raises(Cancelled):
        t.check()

def test_ambient_token_roundtrip():
    assert current() is None
    t = CancelToken()
    set_ambient(t)
    try:
        assert current() is t
    finally:
        clear_ambient()
    assert current() is None

def test_ambient_is_thread_local():
    seen = {}
    set_ambient(CancelToken())
    def worker():
        seen["child"] = current()      # a fresh thread has no ambient token
    th = threading.Thread(target=worker); th.start(); th.join()
    clear_ambient()
    assert seen["child"] is None

class _FakeProc:
    def __init__(self): self.pid = 999; self.killed = False; self.terminated = False
    def terminate(self): self.terminated = True

def test_bind_after_cancel_kills_immediately(monkeypatch):
    import nocturne.core.tasks as tasks
    killed = {}
    monkeypatch.setattr(tasks, "kill_process", lambda p: killed.setdefault("p", p))
    t = CancelToken(); t.cancel()
    p = _FakeProc()
    t.bind_process(p)             # already cancelled -> kill on bind
    assert killed["p"] is p
