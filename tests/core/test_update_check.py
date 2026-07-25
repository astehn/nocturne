from nocturne.core import update_check
from nocturne.core.update_check import is_newer


def test_is_newer_compares_semver():
    assert is_newer("0.4.2", "0.4.1") is True
    assert is_newer("v0.4.2", "0.4.1") is True      # leading v tolerated
    assert is_newer("0.5.0", "0.4.9") is True
    assert is_newer("0.4.1", "0.4.1") is False       # equal
    assert is_newer("0.4.0", "0.4.1") is False       # older
    assert is_newer("garbage", "0.4.1") is False     # malformed latest
    assert is_newer("0.4.2", "nope") is False        # malformed current


class _FakeResp:
    def __init__(self, body): self._body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._body


def test_latest_release_version_parses_tag():
    opener = lambda req, timeout=10: _FakeResp(b'{"tag_name": "v0.4.2"}')
    assert update_check.latest_release_version(opener=opener) == "v0.4.2"


def test_latest_release_version_fail_silent_on_error():
    def boom(req, timeout=10):
        raise OSError("no network")
    assert update_check.latest_release_version(opener=boom) is None


def test_latest_release_version_fail_silent_on_bad_json():
    opener = lambda req, timeout=10: _FakeResp(b'not json at all')
    assert update_check.latest_release_version(opener=opener) is None


def test_latest_release_version_none_when_tag_missing():
    opener = lambda req, timeout=10: _FakeResp(b'{"nope": 1}')
    assert update_check.latest_release_version(opener=opener) is None
