"""Generate the Downloads page from a release manifest.

    .venv/bin/python packaging/build_downloads.py [--refresh]

`site/_src/releases.json` is the manifest: one entry per release, with its
assets. `--refresh` rebuilds it from GitHub (`gh`), which is where every release
and every asset already lives — there is no second source of truth to keep in
step, and no risk of the page advertising a file that was never published.

WITHOUT --refresh THIS SCRIPT TOUCHES NO NETWORK. That is the point of the split:
rendering happens in every site build, and a site build must never depend on
GitHub being reachable or on `gh` being authenticated. Refreshing is a separate,
deliberate act — deploy.py does it when it cuts a release, and a human can do it
any time the manifest and reality drift.

Why a page rather than the homepage button: with two platforms and a growing
history, one button cannot serve a Linux visitor, someone on an older macOS, or
anyone who wants the version they were using last week.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
MANIFEST = SITE / "_src" / "releases.json"
PAGE = SITE / "_src" / "download.html"

# Which platform an asset filename belongs to. Order matters: the Linux tarball
# also contains "Nocturne-<version>", so the more specific test comes first.
def platform_of(name: str) -> str:
    low = name.lower()
    if "linux" in low:
        return "linux"
    if low.endswith(".zip"):
        return "macos"
    return "other"


_LABEL = {"macos": "macOS (Apple Silicon)", "linux": "Linux (x86-64)"}


def human_size(n: int) -> str:
    return f"{n / 1_000_000:.0f} MB" if n >= 1_000_000 else f"{n / 1_000:.0f} KB"


def refresh() -> list[dict]:
    """Rebuild the manifest from GitHub. Needs `gh` and the network."""
    tags = subprocess.run(["gh", "release", "list", "--limit", "100",
                           "--json", "tagName"], capture_output=True, text=True,
                          check=True, cwd=ROOT).stdout
    out = []
    for row in json.loads(tags):
        tag = row["tagName"]
        raw = subprocess.run(["gh", "release", "view", tag, "--json",
                              "tagName,publishedAt,assets"],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        rel = json.loads(raw)
        assets = []
        for a in rel.get("assets", []):
            entry = {"name": a["name"], "size": a["size"], "url": a["url"],
                     "platform": platform_of(a["name"])}
            # GitHub computes a SHA-256 for every asset; shown on the page so a
            # download can be checked (website audit 2026-10-01).
            if isinstance(a.get("digest"), str) and a["digest"].startswith("sha256:"):
                entry["digest"] = a["digest"]
            assets.append(entry)
        if not assets:
            continue                      # a tag with nothing to download is not a download
        out.append({
            "version": rel["tagName"].lstrip("v"),
            "date": rel["publishedAt"][:10],
            "assets": sorted(assets, key=lambda a: a["platform"]),
        })
    out.sort(key=lambda r: [int(p) for p in r["version"].split(".")], reverse=True)
    MANIFEST.write_text(json.dumps(out, indent=2) + "\n")
    return out


def load() -> list[dict]:
    if not MANIFEST.exists():
        raise SystemExit(f"no manifest at {MANIFEST} — run with --refresh once")
    return json.loads(MANIFEST.read_text())


def _rows(releases: list[dict]) -> str:
    out = []
    for i, rel in enumerate(releases):
        links = []
        for a in rel["assets"]:
            label = _LABEL.get(a["platform"], a["platform"])
            # Through get.php so the download is counted, exactly as the
            # homepage button is. `f` names the asset; the counter validates it
            # against this same manifest, so an unknown name cannot redirect
            # anywhere.
            links.append(
                f'<a href="get.php?f={a["name"]}">{label}</a> '
                f'<span class="dl-size">{human_size(a["size"])}</span>')
        latest = ""                      # the latest has its own block above
        out.append(
            f'          <tr>\n'
            f'            <td class="dl-version">{rel["version"]}{latest}</td>\n'
            f'            <td class="dl-date">{rel["date"]}</td>\n'
            f'            <td class="dl-links">{"<br>".join(links)}</td>\n'
            f'          </tr>')
    return "\n".join(out)


_BUTTON = {"macos": ("macOS", "Apple Silicon (M1 or newer)"),
           "linux": ("Linux", "x86-64, glibc 2.39 or newer")}


def _latest_block(rel: dict) -> str:
    """The answer to "which file do I want": the newest build per platform,
    what it runs on said BEFORE the buttons (website audit 2026-10-01)."""
    buttons, sums = [], []
    for plat in ("macos", "linux"):
        a = next((x for x in rel["assets"] if x["platform"] == plat), None)
        if a is None:
            continue
        name, needs = _BUTTON[plat]
        buttons.append(
            f'          <a class="btn btn-primary dl-button" href="get.php?f={a["name"]}">\n'
            f'            Download for {name}\n'
            f'            <span class="btn-sub">{needs} &middot; {human_size(a["size"])}</span>\n'
            f'          </a>')
        if a.get("digest"):
            sums.append(f'          <li><code>{a["name"]}</code><br>'
                        f'<code class="dl-sum">{a["digest"].split(":", 1)[1]}</code></li>')
    checks = ""
    if sums:
        checks = ('        <details class="dl-sums">\n'
                  '          <summary>SHA-256 checksums</summary>\n'
                  '          <ul>\n' + "\n".join(sums) + '\n          </ul>\n'
                  '        </details>\n')
    return f"""    <section class="section-shot dl-latest-block">
      <div class="wrap prose">
        <h2>Nocturne {rel["version"]} <span class="dl-date">released {rel["date"]}</span></h2>
        <p>Runs on <strong>macOS with Apple Silicon</strong> (M1 or newer) and on
          <strong>64-bit Linux</strong> with glibc 2.39 or newer, such as Ubuntu 24.04.
          There is no Windows or Intel Mac build yet.</p>
        <p class="dl-buttons">
{chr(10).join(buttons)}
        </p>
        <p class="fine"><a href="changelog.html">What&rsquo;s new in {rel["version"]}</a> &middot;
          First time? <a href="start-here.html">Start here</a> walks you through a first picture
          with a free <a href="sample-data.html">sample file</a>.</p>
{checks}      </div>
    </section>
"""


def page_html(releases: list[dict]) -> str:
    latest = releases[0] if releases else None
    plats = {a["platform"] for a in (latest["assets"] if latest else [])}
    older = releases[1:]
    older_html = ""
    if older:
        older_html = f"""
        <details class="dl-older">
          <summary>Older releases ({len(older)})</summary>
          <p class="fine">Kept so you can go back to the version you were using.</p>
          <table class="dl-table">
            <thead>
              <tr><th>Version</th><th>Released</th><th>Download</th></tr>
            </thead>
            <tbody>
{_rows(older)}
            </tbody>
          </table>
        </details>
"""
    return f"""---
title: Download Nocturne — macOS and Linux
description: Download Nocturne, the free guided astrophotography app for Seestar telescopes. The latest build for macOS and Linux, and every earlier release.
scripts: main.js
---
<main id="top">
    <section class="page-head">
      <div class="wrap prose">
        <p class="eyebrow">Download</p>
        <h1>Get Nocturne</h1>
        <p>Free and open source, under the GPL. No account, no licence key.</p>
      </div>
    </section>

{_latest_block(latest) if latest else ""}
    <section class="section-shot">
      <div class="wrap prose">
        <h2>Before you run it</h2>
        <p><strong>macOS</strong> — it is not notarized, so on first launch macOS may
          block it: right-click the app → <b>Open</b> → <b>Open</b>, or allow it under
          <b>System&nbsp;Settings → Privacy&nbsp;&amp;&nbsp;Security</b>. You only do this once.</p>
        <p><strong>Linux</strong> — unpack the tarball anywhere and run
          <code>Nocturne/Nocturne</code>; there is nothing to install.
          {"" if "linux" in plats else "(No Linux build in the newest release yet.)"}</p>
        <p class="fine">See what it produces in the <a href="gallery.html">gallery</a>, and
          <a href="setup.html">Install &amp; set up</a> for the free tools worth adding.</p>
{older_html}      </div>
    </section>
</main>
"""


def main(argv: list[str]) -> int:
    releases = refresh() if "--refresh" in argv else load()
    if not releases:
        print("no releases with assets")
        return 1
    PAGE.write_text(page_html(releases))
    plats = sorted({a["platform"] for r in releases for a in r["assets"]})
    print(f"wrote {PAGE.relative_to(ROOT)} — {len(releases)} releases, platforms: {', '.join(plats)}")
    print("now run: .venv/bin/python packaging/build_site.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
