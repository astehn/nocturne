from __future__ import annotations

import json
from pathlib import Path

from .. import APP_NAME, APP_TAGLINE, __version__

_DATA = Path(__file__).resolve().parent.parent / "assets" / "contributors.json"

_FALLBACK = {
    "creator": {"name": "Andreas Stehn",
                "role": "Creator, chief orchestrator & ideas department — "
                        "not a developer, and proud of it"},
    "ai": "Code wrangled in collaboration with Claude (Anthropic)",
    "built_with": [],
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
        f"<p><i>{APP_TAGLINE}</i><br>Version {__version__}</p>"
        "<h3>✦ Dreamed up &amp; directed by</h3>"
        f"<p><b>{creator['name']}</b> — {creator['role']}</p>"
        "<h3>✦ Code</h3>"
        f"<p>{data.get('ai', _FALLBACK['ai'])}</p>"
        "<h3>✦ The crew</h3>"
        "<p>The open-source legends doing the real heavy lifting:</p>"
        f"<ul>{_rows(data.get('built_with', []))}</ul>"
        "<h3>✦ Plays nicely with</h3>"
        f"<ul>{_rows(data.get('works_with', []))}</ul>"
        "<h3>✦ Photon Donors</h3>"
        "<p>The absolute legends who lent their light for testing:</p>"
        f"<ul>{donors_html}</ul>"
        "<hr>"
        "<p>Made under the stars. 🔭 Not affiliated with ZWO — just a fan with "
        "a Seestar and too many clear-sky ambitions.</p>"
    )
