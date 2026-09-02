"""Type that travels with the app.

Share's plate used QFont() — the bare system default, whatever that happened to
be on the machine. Two things follow from bundling instead: an export looks the
same on every machine (the WYSIWYG principle, applied to type), and the planned
Windows build has a face to draw with at all. A family that is merely REQUESTED
substitutes silently when absent, which is the worst failure available: the
export is wrong and nothing says so.

Five SIL OFL families, 1.7 MB with licences. Jost, Manrope and Cormorant carry
real variable weight axes; Marcellus and Barlow Condensed are single-weight by
design, which the plate does not need from every face.
"""
from __future__ import annotations

from pathlib import Path

# .resolve() is not cosmetic: QFontDatabase.addApplicationFont returns -1 for a
# RELATIVE path (measured 2026-09-02 — all five files load from an absolute path
# and all five fail from "nocturne/assets/fonts/..."), and the only symptom is a
# silently substituted system face.
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# (menu label, Qt family name). The label carries the mood, because "Jost" tells
# a novice nothing about what they are choosing. The family names are what Qt
# itself reports, not the filenames: a variable font registers one entry per
# named instance (Jost nine, Manrope seven, Cormorant five) and they all carry
# the same family, so the set below has one row per FILE.
PLATE_FAMILIES: list[tuple[str, str]] = [
    ("Geometric — Jost", "Jost"),
    ("Humanist — Manrope", "Manrope"),
    ("Serif — Cormorant Garamond", "Cormorant Garamond"),
    ("Inscription — Marcellus", "Marcellus"),
    ("Condensed — Barlow Condensed", "Barlow Condensed"),
]

_loaded: list[str] | None = None


def load_bundled_fonts() -> list[str]:
    """Register every bundled face; return the families Qt actually took.

    Idempotent — Qt would happily register the same file twice. Requires a live
    QApplication, so this is called from main() after the app is constructed and
    before any window exists.
    """
    global _loaded
    if _loaded is not None:
        return _loaded
    from PySide6.QtGui import QFontDatabase
    families: list[str] = []
    if FONT_DIR.is_dir():
        for path in sorted(FONT_DIR.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid != -1:
                families.extend(QFontDatabase.applicationFontFamilies(fid))
    _loaded = sorted(set(families))
    return _loaded


def available_families() -> list[tuple[str, str]]:
    """PLATE_FAMILIES filtered to what actually loaded — so a face that failed
    to register is not offered in a menu that then draws something else."""
    have = set(load_bundled_fonts())
    return [(label, fam) for label, fam in PLATE_FAMILIES if fam in have]
