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


def test_every_line_is_stamped(tmp_path):
    """Found by rendering a real session rather than reading the code: the
    lines had no time on them at all. "When did it fail, and how long was it
    between steps" is half of what a log is read for — and the GUI history
    panel it mirrors has stamped every line since it was written.

    Seconds, not milliseconds: this measures a person's session, where the
    interesting gaps are tens of seconds.
    """
    import re
    sessionlog.start_session(str(tmp_path))
    sessionlog.write("step  Crop")
    line = sessionlog.read_session(str(tmp_path)).splitlines()[0]
    assert re.match(r"^\d{2}:\d{2}:\d{2}  step  Crop$", line), line


def test_a_multi_line_write_stamps_every_line(tmp_path):
    """_report_tool_error writes a whole stderr block in one call. Stamping
    once left the rest unstamped, and _trim's "never a half line" rule could
    then cut inside the block and leave a fragment reading like a new entry."""
    import re
    sessionlog.start_session(str(tmp_path))
    sessionlog.write("ERROR Star separation failed\nCommand: starnet2\nstderr:\nlzw_decode")
    lines = sessionlog.read_session(str(tmp_path)).splitlines()
    assert len(lines) == 4
    for line in lines:
        assert re.match(r"^\d{2}:\d{2}:\d{2}  ", line), line


def test_the_log_is_never_empty_midway_through_a_trim(tmp_path, monkeypatch):
    """`open(path, "w")` truncated first, so the file was ZERO BYTES for as
    long as it took to write ~500 KB back. A report opened in that window
    carried an empty log while the tick said it was included, and a kill
    mid-trim lost the log outright — the crash the two-session design exists
    for. Found by review 2026-09-22.

    Asserted by watching what a reader sees at the moment of the swap."""
    import os
    sessionlog.start_session(str(tmp_path))

    seen = []
    real_replace = os.replace

    def watching(src, dst):
        # Only the trim's own swap, not start_session's rotation.
        if str(src).endswith(".trim"):
            # What a reader would get: new file written, not yet swapped in.
            seen.append(len(sessionlog.read_session(str(tmp_path))))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", watching)
    for n in range(20000):
        sessionlog.write("x" * 80 + f" line {n}")
    # Two properties, and the first is the atomicity itself: a trim that
    # truncates in place performs no .trim swap, so an empty `seen` means
    # either the fixture never reached MAX_BYTES or the write is not atomic.
    assert seen, "no atomic swap observed: either the trim is in-place, or the fixture never reached MAX_BYTES"
    assert all(n > 0 for n in seen), f"the log was empty mid-trim: {seen}"
