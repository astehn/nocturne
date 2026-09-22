import os

from nocturne.core import sessionlog


def test_a_new_session_rotates_the_previous_one_aside(tmp_path):
    """Deleting at quit was proposed and rejected: the sequence is always app
    dies -> user relaunches -> THEN they report, so a quit-wipe means every
    crash report describes a fresh, healthy session. The Share segfault of
    2026-09-21 is the worked example."""
    sessionlog.start_session(str(tmp_path))
    sessionlog.write("first session")
    sessionlog.start_session(str(tmp_path))          # a relaunch
    sessionlog.write("second session")
    assert "second session" in sessionlog.read_session(str(tmp_path))
    assert "first session" in sessionlog.read_previous(str(tmp_path))
    assert "first session" not in sessionlog.read_session(str(tmp_path))


def test_only_two_sessions_are_kept(tmp_path):
    for n in range(4):
        sessionlog.start_session(str(tmp_path))
        sessionlog.write(f"session {n}")
    assert "session 3" in sessionlog.read_session(str(tmp_path))
    assert "session 2" in sessionlog.read_previous(str(tmp_path))
    assert "session 1" not in sessionlog.read_previous(str(tmp_path))
    kept = [f for f in os.listdir(tmp_path / ".nocturne") if "session" in f]
    assert len(kept) == 2, kept


def test_the_file_is_capped_and_drops_the_OLDEST_lines(tmp_path):
    """Oldest, because the interesting part of a log is what happened last.
    Truncating the tail would discard the failure and keep the startup.

    The padding is what makes this reach the real MAX_BYTES rather than a
    shrunken stand-in: a step line is about 80 bytes, so 20 000 of them is
    ~1.8 MB against a 1 MB cap. The marker is at the END of each line so that
    "line 0" is absent only because it was trimmed, never because the padding
    moved the newline."""
    sessionlog.start_session(str(tmp_path))
    for n in range(20000):
        sessionlog.write("x" * 80 + f" line {n}")
    text = sessionlog.read_session(str(tmp_path))
    assert len(text.encode()) <= sessionlog.MAX_BYTES
    assert "line 19999" in text
    assert "line 0\n" not in text
    # "line 0" alone has NO teeth: _trim drops a half line at the cut, so a
    # head-keeping trim loses the first line on every pass and would pass this
    # too. What tells the two apart is WHICH lines survived -- the oldest one
    # kept must come from the end of the run, not the start. Measured by
    # mutation 2026-09-22: keeping text[:MAX_BYTES // 2] left a log that
    # started at "line 2" and still satisfied every other assertion here.
    oldest_kept = int(text.splitlines()[0].rsplit(" ", 1)[1])
    assert oldest_kept > 10000, f"the head was kept, not the tail: {oldest_kept}"


def test_writing_never_raises_when_the_file_cannot_be_opened(tmp_path):
    """A log is a diagnostic, never a reason for the app to misbehave."""
    sessionlog.start_session(str(tmp_path / "nope" / "\0bad"))
    sessionlog.write("this must not raise")


def test_reading_a_session_that_never_happened_is_empty_not_an_error(tmp_path):
    assert sessionlog.read_session(str(tmp_path)) == ""
    assert sessionlog.read_previous(str(tmp_path)) == ""


def test_it_imports_without_qt():
    """core/ is Qt-free. Asserted by import, not by grep: a transitive Qt
    import through a helper would not show up in this file's own text."""
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.modules['PySide6']=None; "
         "import nocturne.core.sessionlog"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
