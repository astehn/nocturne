"""Which filter a capture went through, read from its FILTER card.

Shared by Auto Enhance and the Color step: photometric colour means nothing
through the dual-band filter, and the Color step must not depend on Auto
Enhance to find that out."""
from __future__ import annotations


def detect_data_type(metadata: dict) -> str:
    """'dualband' if the Seestar LP (Ha/OIII) filter, 'broadband' if a known
    other filter, 'unknown' if absent (caller should ask)."""
    filt = str(metadata.get("filter") or "").strip().upper()
    if not filt:
        return "unknown"
    return "dualband" if "LP" in filt else "broadband"
