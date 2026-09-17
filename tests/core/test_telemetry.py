"""The rules that make the telemetry honest. See nocturne/core/telemetry.py."""
import datetime

import pytest

from nocturne.core import telemetry as t


def test_the_payload_is_a_closed_set():
    """The promise on the privacy page is that this is everything. A field added
    later without thinking would break that silently, so the set is pinned here
    and `build_payload` checks itself against it.
    """
    assert t.ALLOWED_KEYS == {"event", "version", "id"}
    assert set(t.build_payload("first-run", "0.34.0")) <= t.ALLOWED_KEYS
    assert set(t.build_payload("daily", "0.34.0", "abc")) <= t.ALLOWED_KEYS


def test_first_run_carries_no_identifier_at_all():
    """It answers "did this download ever launch", which needs no id — and an id
    on a once-ever event would be the one datum that could be correlated with a
    download."""
    assert t.build_payload("first-run", "0.34.0") == {"event": "first-run",
                                                      "version": "0.34.0"}


def test_an_unknown_event_is_refused_rather_than_invented():
    with pytest.raises(ValueError):
        t.build_payload("crash", "0.34.0")


def test_the_id_is_stable_within_a_month():
    """Distinct ids in a month = installs active that month. If it rotated more
    often the count would inflate, which is the failure that would flatter the
    numbers rather than deflate them."""
    first, month = t.rotate_id("", "", datetime.date(2026, 9, 1))
    same, _ = t.rotate_id(first, month, datetime.date(2026, 9, 30))
    assert same == first
    assert month == "2026-09"


def test_the_id_changes_at_the_month_boundary():
    """The link across months is severed by construction — no cohort, no
    retention curve, no per-user history, however much someone later wishes for
    one."""
    first, month = t.rotate_id("", "", datetime.date(2026, 9, 30))
    later, new_month = t.rotate_id(first, month, datetime.date(2026, 10, 1))
    assert later != first
    assert new_month == "2026-10"


def test_an_id_from_a_year_ago_in_the_same_month_number_still_rotates():
    """September 2025 and September 2026 must not share an id. The month key
    carries the year for exactly this reason."""
    old, _ = t.rotate_id("", "", datetime.date(2025, 9, 15))
    new, _ = t.rotate_id(old, "2025-09", datetime.date(2026, 9, 15))
    assert new != old


def test_one_daily_per_calendar_day():
    today = datetime.date(2026, 9, 17)
    assert t.should_send_daily("2026-09-16", today) is True
    assert t.should_send_daily("2026-09-17", today) is False
    assert t.should_send_daily("", today) is True          # never sent
    assert t.should_send_daily("not a date", today) is True  # corrupt, not stuck


def test_send_posts_json_to_the_documented_endpoint():
    seen = {}

    class _Resp:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = req.data
        return _Resp()

    assert t.send({"event": "daily", "version": "0.34.0", "id": "x"}, opener=opener) is True
    assert seen["url"] == t.PING_URL
    assert seen["method"] == "POST"
    import json
    assert json.loads(seen["body"]) == {"event": "daily", "version": "0.34.0", "id": "x"}


@pytest.mark.parametrize("boom", [
    TimeoutError("timed out"),
    OSError("dns"),
    ValueError("html where json was expected"),
])
def test_every_failure_is_silent(boom):
    """A stack that has been running for two hours must not die over a counter,
    and a user must never see a dialog about it."""
    def opener(req, timeout=None):
        raise boom
    assert t.send({"event": "daily", "version": "0.34.0", "id": "x"}, opener=opener) is False


def test_a_non_2xx_response_is_not_counted_as_sent():
    class _Resp:
        status = 500
        def __enter__(self): return self
        def __exit__(self, *a): return False
    assert t.send({"event": "daily", "version": "0", "id": "x"},
                  opener=lambda req, timeout=None: _Resp()) is False
