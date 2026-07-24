from __future__ import annotations


def detect_data_type(metadata: dict) -> str:
    """'dualband' if the Seestar LP (Ha/OIII) filter, 'broadband' if a known
    other filter, 'unknown' if absent (caller should ask)."""
    filt = str(metadata.get("filter") or "").strip().upper()
    if not filt:
        return "unknown"
    return "dualband" if "LP" in filt else "broadband"
