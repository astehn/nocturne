"""The phase timings must land somewhere a user can read after the fact.

`drizzle_stack` has logged per-pass timings since 2026-09-01, but no handler was
ever configured, so Python's last-resort handler (WARNING and above) dropped
every one. A 1233-frame overnight drizzle on 2026-09-02 ran ~4x the estimate and
left no record of which phase was slow.
"""
import logging

from nocturne.core.applog import configure_logging, log_path


def _fresh(monkeypatch):
    import nocturne.core.applog as m
    monkeypatch.setattr(m, "_configured", False)
    root = logging.getLogger("nocturne")
    for h in list(root.handlers):
        root.removeHandler(h)
    return m


def test_an_info_line_reaches_the_file(tmp_path, monkeypatch):
    """The exact call drizzle_stack makes — .info() on a child logger."""
    _fresh(monkeypatch)
    p = tmp_path / "nocturne.log"
    assert configure_logging(str(p)) == str(p)
    logging.getLogger("nocturne.drizzle").info("pass 2 (drizzle): %d frames in %.0f s", 1233, 26700)
    logging.shutdown()
    text = p.read_text()
    assert "pass 2 (drizzle): 1233 frames in 26700 s" in text
    assert "nocturne.drizzle" in text


def test_calling_it_twice_does_not_write_everything_twice(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    p = tmp_path / "n.log"
    configure_logging(str(p))
    configure_logging(str(p))
    logging.getLogger("nocturne.drizzle").info("once")
    logging.shutdown()
    assert p.read_text().count("once") == 1


def test_an_unwritable_path_does_not_stop_the_app(tmp_path, monkeypatch):
    """Startup calls this. A log file is a diagnostic, never a launch failure."""
    _fresh(monkeypatch)
    assert configure_logging("/nonexistent-root-dir/deeper/n.log") is None


def test_it_does_not_leak_into_the_root_logger(tmp_path, monkeypatch):
    """propagate=False, or every unrelated test's output fills with stack logs."""
    _fresh(monkeypatch)
    configure_logging(str(tmp_path / "n.log"))
    assert logging.getLogger("nocturne").propagate is False


def test_the_default_path_sits_beside_settings(monkeypatch):
    assert log_path("/home/x") == "/home/x/.nocturne/nocturne.log"


def test_startup_configures_it(monkeypatch):
    """Wired, not merely written — the failure being fixed was a logger with no
    handler, which looks identical to a working one until you go to read it."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "__main__.py").read_text()
    assert "configure_logging()" in src


def test_the_drizzle_timings_are_still_info_level():
    """If these ever drop to debug the file goes quiet again, silently."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "stacking" / "drizzle_stack.py").read_text()
    assert src.count("_log.info(") >= 3, "the per-pass timings lost their log calls"
