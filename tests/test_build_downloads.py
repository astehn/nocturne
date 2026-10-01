"""The Download page answers 'which file do I want' first (website audit
2026-10-01): the latest macOS and Linux builds as the main choice, what they
run on beside them, checksums, and the history folded away."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_downloads", Path(__file__).resolve().parent.parent / "packaging" / "build_downloads.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)


def _rel(v, date, digest=True):
    def a(name, plat, size):
        d = {"name": name, "size": size, "url": f"https://x/{name}", "platform": plat}
        if digest:
            d["digest"] = "sha256:" + ("ab" * 32)
        return d
    return {"version": v, "date": date, "assets": [
        a(f"Nocturne-{v}-linux-x86_64.tar.gz", "linux", 212_000_000),
        a(f"Nocturne-{v}.zip", "macos", 129_000_000)]}


RELEASES = [_rel("0.44.0", "2026-10-01"), _rel("0.43.0", "2026-09-29"),
            _rel("0.42.0", "2026-09-29", digest=False)]


def _page():
    return bd.page_html(RELEASES)


def test_the_latest_builds_are_the_main_choice():
    h = _page()
    main = h.split('dl-latest-block"', 1)[1].split("</section>", 1)[0]
    assert "get.php?f=Nocturne-0.44.0.zip" in main
    assert "get.php?f=Nocturne-0.44.0-linux-x86_64.tar.gz" in main
    assert "Apple Silicon" in main and "x86-64" in main
    assert "129 MB" in main and "212 MB" in main
    assert "0.43.0" not in main, "older releases are not part of the main choice"


def test_what_it_runs_on_is_said_before_the_buttons():
    h = _page()
    block = h.split('dl-latest-block"', 1)[1]
    req = block.index("glibc 2.39")
    assert req < block.index("get.php?f=Nocturne-0.44.0.zip")
    assert "Windows" in block[:req + 400] and "Intel" in block[:req + 400]


def test_older_releases_are_folded_away_but_all_there():
    h = _page()
    older = h.split('class="dl-older"', 1)[1].split("</details>", 1)[0]
    assert "Older releases (2)" in older
    assert "get.php?f=Nocturne-0.43.0.zip" in older and "get.php?f=Nocturne-0.42.0.zip" in older
    assert "get.php?f=Nocturne-0.44.0.zip" not in older


def test_checksums_are_shown_where_github_has_them():
    h = _page()
    assert "ab" * 32 in h.split('dl-latest-block"', 1)[1].split("</section>", 1)[0]


def test_it_points_to_whats_new_and_to_the_sample_data():
    main = _page().split('dl-latest-block"', 1)[1].split("</section>", 1)[0]
    assert 'href="changelog.html"' in main and 'href="sample-data.html"' in main


def test_refresh_keeps_the_checksum(monkeypatch, tmp_path):
    import json
    calls = []

    class R:
        def __init__(self, out): self.stdout = out

    def fake_run(args, **kw):
        calls.append(args)
        if args[:3] == ["gh", "release", "list"]:
            return R(json.dumps([{"tagName": "v0.44.0"}]))
        return R(json.dumps({"tagName": "v0.44.0", "publishedAt": "2026-10-01T16:00:00Z",
                             "assets": [{"name": "Nocturne-0.44.0.zip", "size": 1,
                                         "url": "u", "digest": "sha256:" + "cd" * 32}]}))
    monkeypatch.setattr(bd.subprocess, "run", fake_run)
    monkeypatch.setattr(bd, "MANIFEST", tmp_path / "releases.json")
    out = bd.refresh()
    assert out[0]["assets"][0]["digest"] == "sha256:" + "cd" * 32
    # gh's "assets" field already carries each asset's digest; nothing extra to ask for.
