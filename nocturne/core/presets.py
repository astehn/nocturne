"""Named looks for the Share title plate.

A preset is the only thing that can hold a WHOLE combination — family, three
sizes, tracking, treatment, anchor, margin, colour — behind one click. Without
one, every export is re-dialled from scratch and a feed ends up looking like
five unrelated images rather than one person's work.

Pure: no Qt. The renderer reads these attributes; it does not import this.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class PlateStyle:
    name: str
    family: str
    # Fractions of the COMPOSITED HEIGHT, never pixels: an absolute size means
    # something different at 1080 and at 4096, and one of them is unreadable.
    size_title: float
    size_sub: float
    size_credit: float
    tracking_title: float      # percent added to normal spacing
    tracking_sub: float
    weight_title: int          # Qt weight number, e.g. 300 Light / 500 Medium
    weight_sub: int
    treatment: str             # scrim | shadow | band | none | matte
    anchor: str                # one of plate_render.ANCHORS keys
    margin: float              # fraction of the SHORT edge
    colour: str
    rule: bool                 # hairline between designation and common name
    keyline: bool              # inset border; independent of treatment


PRESETS: list[PlateStyle] = [
    PlateStyle("Scrim", "Manrope", 0.023, 0.040, 0.0155, 22, 2, 500, 300,
               "scrim", "bottom-centre", 0.048, "#F0E9E2", True, False),
    PlateStyle("Plate", "Jost", 0.030, 0.042, 0.0155, 14, 4, 500, 300,
               "shadow", "bottom-centre", 0.055, "#F0E9E2", True, False),
    PlateStyle("Keyline", "Cormorant Garamond", 0.021, 0.041, 0.0145, 26, 0, 500, 400,
               "shadow", "bottom-left", 0.032, "#F2ECE5", False, True),
    PlateStyle("Matte", "Jost", 0.0165, 0.030, 0.0115, 30, 6, 500, 300,
               "matte", "bottom-centre", 0.075, "#EFE8E0", False, False),
    # Today's output, kept so nothing regresses for anyone already using Share.
    # Every number here is READ from the code it reproduces, not chosen to look
    # right: 0.028 is share_render.FONT_FRAC (= share.DEFAULT_CAPTION_SIZE),
    # 0.03 is share_render.PAD_FRAC, #ffffff is share.DEFAULT_CAPTION_COLOUR,
    # and bottom-left is DEFAULT_PLACEMENT "on" + DEFAULT_ALIGNMENT "left".
    # One size for all three slots and no tracking, because the old renderer
    # drew a single `·`-joined line with a bare QFont() and no hierarchy.
    PlateStyle("Data", "Manrope", 0.028, 0.028, 0.028, 0, 0, 400, 400,
               "band", "bottom-left", 0.03, "#ffffff", False, False),
]

_BY_NAME = {p.name: p for p in PRESETS}


def preset_by_name(name: str) -> PlateStyle:
    """Falls back to the default rather than raising: a settings file naming a
    preset this build does not have must not stop Share from opening."""
    return _BY_NAME.get(name, PRESETS[0])


def style_to_dict(style: PlateStyle) -> dict:
    return asdict(style)


def style_from_dict(data: dict) -> PlateStyle:
    """Ignore keys we do not know, default the ones we do not get.

    Settings written by a newer build must not brick an older one, and a key
    added later must not make an older file unreadable.
    """
    known = {f.name for f in fields(PlateStyle)}
    base = asdict(preset_by_name(str(data.get("name", ""))))
    base.update({k: v for k, v in data.items() if k in known})
    return PlateStyle(**base)
