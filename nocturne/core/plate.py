"""The Share title plate's text, and where each line comes from.

Pure — no Qt. `ui/plate_render.py` paints what this returns.

The app already computed both lines and threw the structure away:
`catalog.identify_target` ranks the field and returns
"IC 1396A · Elephant's Trunk Nebula", then `share.caption_line` joined THAT
into a longer `·` strip. Recovering the pair is most of the feature.
"""
from __future__ import annotations

from dataclasses import dataclass

from .catalog import common_name_for
from .share import caption_line


@dataclass(frozen=True)
class PlateText:
    designation: str        # "IC 1396A"
    common: str             # "Elephant's Trunk Nebula"
    credit: str             # "5h 39m · 2037 × 10s · 2026-08-31 · @andreas"


def plate_text(metadata: dict, handle: str) -> PlateText:
    """Fill each slot independently, and never invent.

    Any slot may come back empty; the renderer omits an empty slot and closes
    the gap. Everything here is a STARTING POINT — the dialog lets the user
    edit or clear all three.
    """
    desig = str(metadata.get("target_designation") or "").strip()
    common = str(metadata.get("target_common") or "").strip()

    if not desig:
        # " · " is exactly what catalog.identify_target joins the pair with, and
        # what a pre-plate bundle stored in target_solved.
        joined = str(metadata.get("target") or metadata.get("target_solved") or "").strip()
        if " · " in joined:
            desig, _, rest = joined.partition(" · ")
            desig, common = desig.strip(), (common or rest.strip())
        else:
            desig = joined

    if desig and not common:
        common = common_name_for(desig)

    return PlateText(desig, common, caption_line(metadata, handle, include_target=False))
