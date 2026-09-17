from __future__ import annotations

import json
from pathlib import Path

import nocturne
from .. import APP_NAME, APP_TAGLINE, __version__, version_label

_DATA = Path(__file__).resolve().parent.parent / "assets" / "contributors.json"

_FALLBACK = {
    "creator": {"name": "Andreas Stehn",
                "role": "Creator, chief orchestrator & ideas department — "
                        "not a developer, and proud of it"},
    "ai": "Code wrangled in collaboration with Claude (Anthropic)",
    "built_with": [],
    "fonts": [],
    "works_with": [],
    "photon_donors": [],
}


def load_contributors(path: str | None = None) -> dict:
    """Read the contributors JSON. Returns a safe minimal dict on any error so
    the About page never crashes."""
    p = Path(path) if path else _DATA
    try:
        data = json.loads(p.read_text())
    except Exception:  # noqa: BLE001 — missing/corrupt file must never crash About
        return dict(_FALLBACK)
    for key, val in _FALLBACK.items():
        data.setdefault(key, val)
    return data


def _rows(items: list) -> str:
    return "".join(f"<li><b>{it['name']}</b> — {it['what']}</li>" for it in items)


def about_html(data: dict | None = None) -> str:
    if data is None:
        data = load_contributors()
    creator = data.get("creator", _FALLBACK["creator"])
    donors = data.get("photon_donors", [])
    donors_html = (
        "".join(f"<li>{name}</li>" for name in donors)
        if donors else
        "<li><i>Be the first to lend your light — share your subs and get "
        "immortalised here!</i></li>"
    )
    return (
        f"<h1>{APP_NAME}</h1>"
        f"<p><i>{APP_TAGLINE}</i><br>Version {version_label()}</p>"
        # nocturne.RELEASE_STAGE at CALL time, not a name bound at import:
        # a module-level copy cannot be cleared for a stable release, and that
        # is the exact drift tests/test_beta_disclosure.py guards against.
        + (f"<p><b>This is {nocturne.RELEASE_STAGE} software.</b> "
           f"{nocturne.BETA_NOTICE}.</p>" if nocturne.RELEASE_STAGE else "")
        + "<h3>✦ Dreamed up &amp; directed by</h3>"
        f"<p><b>{creator['name']}</b> — {creator['role']}</p>"
        "<h3>✦ Code</h3>"
        f"<p>{data.get('ai', _FALLBACK['ai'])}</p>"
        "<h3>✦ The crew</h3>"
        "<p>The open-source legends doing the real heavy lifting:</p>"
        f"<ul>{_rows(data.get('built_with', []))}</ul>"
        # The SIL OFL asks for the licence to travel with the fonts, which it
        # does in assets/fonts/. Naming the families is not required — it is
        # simply what you do when someone's work is set into every share.
        "<h3>✦ Type</h3>"
        "<p>The title plate is set in type that ships with Nocturne, so a share "
        "looks the same on any machine. All five under the "
        "<b>SIL Open Font License</b>, whose full text travels with them:</p>"
        f"<ul>{_rows(data.get('fonts', []))}</ul>"
        "<h3>✦ Plays nicely with</h3>"
        f"<ul>{_rows(data.get('works_with', []))}</ul>"
        "<h3>✦ Photon Donors</h3>"
        "<p>The absolute legends who lent their light for testing:</p>"
        f"<ul>{donors_html}</ul>"
        # Said IN THE APP, not only on the website. Nocturne asked GitHub for
        # the latest release on every launch from the day that check was added
        # until 2026-09-17, and nothing anywhere told anyone. A person who finds
        # a connection they were not told about is right to distrust everything
        # else, and "it is on our website" is not being told.
        "<h3>✦ Privacy</h3>"
        "<p>Your images never leave your Mac. Nocturne makes at most <b>two</b> "
        "network requests, and you can refuse both in Settings:</p>"
        "<p>1. At startup it asks github.com whether a newer version has been "
        "released. Your IP address reaches GitHub as part of that request, as it "
        "does for any web request — Nocturne itself receives nothing.</p>"
        "<p>2. If you said yes when asked on first run, once a day it sends "
        "<i>{\"event\": \"daily\", \"version\", \"id\"}</i> and nothing else. The id is "
        "a random number for this installation that changes every month; no IP "
        "address is stored. Nothing about your machine or your images is ever "
        "sent, whatever you choose.</p>"
        "<p><a href='https://nocturne.stehn.com/privacy.html'>"
        "nocturne.stehn.com/privacy.html</a></p>"
        "<hr>"
        "<p>Made under the stars. 🔭 Not affiliated with ZWO — just a fan with "
        "a Seestar and too many clear-sky ambitions.</p>"
    )
