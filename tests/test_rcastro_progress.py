"""RC-Astro reports progress, for every tool that reaches it.

Measured on RC-Astro 2.6.6, 2026-09-11. Its default output writes a progress bar
with CARRIAGE RETURNS — one long line — so line-based streaming sees nothing
until the operation ends. Its `--json` mode is newline-delimited instead:

    {"event":"progress","done":11.1,"mpPerSec":0.6,"eta":1.1}
    {"event":"status","phase":"saving","message":"Saving"}
    {"event":"error","message":"no input files matched"}

which carries a percentage, an ETA, phase names and a schemaVersion — a contract
rather than a scrape. One change in `_run` covers Deconvolution, Noise Reduction,
Star Reduction, Saturation, De-green Stars, Narrowband, Colour Balance and
Starless Levels, because every RC-Astro operation funnels through it.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.core.tasks import CancelToken, clear_ambient, set_ambient
from nocturne.tools.rcastro import RCAstro, parse_rc_event


def _img():
    return AstroImage(np.zeros((4, 4, 3), np.float32), is_linear=False, metadata={})


def test_progress_events_are_understood():
    assert parse_rc_event('{"event":"progress","done":11.1,"mpPerSec":0.6,"eta":1.1}') \
        == ("progress", 11)
    assert parse_rc_event('{"event":"progress","done":100.0,"eta":0.0}') == ("progress", 100)


def test_other_events_are_classified_not_guessed():
    assert parse_rc_event('{"event":"status","phase":"saving","message":"Saving"}') \
        == ("status", "Saving")
    assert parse_rc_event('{"event":"error","message":"no input files matched"}') \
        == ("error", "no input files matched")


def test_junk_is_ignored_rather_than_crashing_a_run():
    """A tool's chatter must never take down the operation."""
    assert parse_rc_event("not json at all") is None
    assert parse_rc_event("") is None
    assert parse_rc_event('{"event":"progress"}') is None       # no percentage
    assert parse_rc_event('{"nope":1}') is None


def test_a_run_reports_progress_to_the_ambient_sink(monkeypatch):
    import nocturne.tools.rcastro as rc

    monkeypatch.setattr(rc, "_supports_json", lambda *a, **k: True)
    got = []
    token = CancelToken()
    token.on_progress = lambda d, t: got.append(d)
    set_ambient(token)

    captured = {}

    def fake_runner(args, **kw):
        captured["args"] = args
        for pct in (11.1, 55.6, 100.0):
            kw["on_line"](f'{{"event":"progress","done":{pct},"eta":0.1}}')

    try:
        try:
            RCAstro("/nowhere/rc-astro").denoise(_img(), 0.9, runner=fake_runner)
        except Exception:
            pass          # the fake writes no output file; progress is the subject
    finally:
        clear_ambient()

    assert "--json" in captured["args"], "JSON mode was not requested"
    assert got == [11, 56, 100]


def test_without_json_support_the_run_is_unchanged(monkeypatch):
    """An older RC-Astro must keep working — without progress, not broken."""
    import nocturne.tools.rcastro as rc

    monkeypatch.setattr(rc, "_supports_json", lambda *a, **k: False)
    captured = {}

    def fake_runner(args, **kw):
        captured["args"] = args
        captured["on_line"] = kw.get("on_line")

    try:
        RCAstro("/nowhere/rc-astro").denoise(_img(), 0.9, runner=fake_runner)
    except Exception:
        pass
    assert "--json" not in captured["args"]
    assert captured.get("on_line") is None, "streaming was requested with nothing to parse"


def test_the_star_split_reports_progress_too(monkeypatch):
    """StarXTerminator does NOT go through `_run`, and it is the slow one — the
    split that Narrowband, Colour Balance, Starless Levels, Star Reduction,
    Saturation and De-green Stars all wait on. A fix that only covered
    `_run` would have missed the wait people actually feel."""
    import nocturne.tools.rcastro as rc

    monkeypatch.setattr(rc, "_supports_json", lambda *a, **k: True)
    got = []
    token = CancelToken()
    token.on_progress = lambda d, t: got.append(d)
    set_ambient(token)

    captured = {}

    def fake_runner(args, **kw):
        captured["args"] = args
        kw["on_line"]('{"event":"progress","done":40.0,"eta":2.0}')

    try:
        try:
            RCAstro("/nowhere/rc-astro").remove_stars(_img(), runner=fake_runner)
        except Exception:
            pass
    finally:
        clear_ambient()
    assert "--json" in captured["args"]
    assert "sxt" in captured["args"], "this must be the star split, not another product"
    assert got == [40]
