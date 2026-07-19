# Crop step rework — Design

**Date:** 2026-07-19 · **Status:** Approved (audit + design Q&A)
**Source:** `docs/audit/PIPELINE_AUDIT.md` → Step 2 (Crop).

Rework the Crop overlay so it's legible and unobtrusive, delivering on "trim the
ragged edges and frame your target." Display/interaction only — the crop engine
(`core/crop.py`) is unchanged.

## Interaction model (the core change)

- **Enter Crop:** crop *mode* is on but the overlay is **hidden**. The canvas
  shows the (optionally unlinked) preview, uncluttered. The detected content
  bounds (`detect_content_bounds`) are computed and stored, not drawn.
- **Click on the image:** the crop box **appears at the detected content edges**
  (auto-trim as the starting frame), with exterior dimming, the selected guides,
  and the size readout. "Apply Crop" becomes enabled.
- **Adjust:** drag the box / handles, choose an aspect ratio, choose guides.
- **Apply Crop:** commits the crop, then the overlay **hides again** and Apply
  disables. The next click re-shows the box at the new image's content edges
  (supports iterative cropping).
- **Rotate 90° / Flip H / Flip V:** apply **instantly**, independent of the box.
- **Leave Crop:** crop mode off, overlay torn down.

## Rendering when the box is visible

- **Drop the inside tint.** `_Body` fill → transparent (it currently reads as a
  colour cast). Keep a crisp accent-teal outline.
- **Dim the exterior.** Override `ImageView.drawForeground`: when crop mode is on
  and the box is visible, fill the viewport *outside* the crop rectangle with
  black at ~45% (alpha ≈ 120). Standard keep-vs-remove convention.
- **Composition guides.** When a guide is selected and the box is visible, draw
  thin translucent lines *inside* the crop rect (also in `drawForeground`):
  - **Rule of thirds:** verticals at 1/3, 2/3; horizontals at 1/3, 2/3.
  - **Center cross:** one vertical + one horizontal through the center.
  - **None** (default): no lines.

## Panel changes (`step_panels.py`, crop branch)

- **Guides selector:** `QComboBox` labelled "Guides" with `None`, `Rule of
  thirds`, `Center cross` → `on_guides_change(kind)` callback.
- **Selection readout:** a `QLabel` (`w.crop_size_label`) showing `"{w} × {h} px"`
  live; `"—"` when no box is shown.
- **Apply Crop starts disabled**, enabled once the box is visible.
- **Relabel** the checkbox "Unlink stretch (neutralize tint)" → **"Neutral
  preview (for framing)"** (keep the sub-caption).
- **Group** Rotate/Flip under a small "(applies instantly)" note, distinct from
  Apply Crop; Rotate label → **"Rotate 90° ↻"** (clockwise cue).

## Interfaces

`ImageView` (`image_view.py`):
- `set_crop_overlay(enabled: bool, content_bounds=None, aspect_ratio=None)` —
  toggles crop mode; stores `content_bounds`; does **not** draw the box.
- `show_crop_box()` — build/show body+handles at stored content bounds
  (idempotent); emits `cropBoxShown`.
- `hide_crop_box()` — remove body+handles, keep crop mode on.
- `crop_box_visible() -> bool`.
- `set_guides(kind: str)` — `"none" | "thirds" | "center"`; stores + `viewport().update()`.
- `mousePressEvent` — if crop mode on and not `crop_box_visible()` and the click
  maps onto the image, call `show_crop_box()` (then normal handling).
- `drawForeground(painter, rect)` — exterior dim + guides when box visible.
- Signals: existing `cropBoxChanged(t,b,l,r)`; new `cropBoxShown()`.

`MainWindow`:
- `_setup_crop_overlay`: `set_crop_overlay(True, content_bounds=detect_content_bounds(current), aspect_ratio=...)`; overlay hidden; Apply disabled; readout "—".
- Connect `cropBoxChanged` → `_update_crop_readout`; `cropBoxShown` → enable Apply + refresh readout.
- `_apply_crop`: after commit, `hide_crop_box()`, disable Apply, reset readout, recompute content bounds for the next click.
- `_on_guides_change(kind)` → `image_view.set_guides(...)`.

## Testing

- Overlay state machine (call methods directly, no synthetic mouse events):
  `set_crop_overlay(True, bounds)` → `crop_box_visible()` is False; `show_crop_box()`
  → True and bounds ≈ content bounds; `hide_crop_box()` → False; still in crop mode.
- `set_guides` stores the kind; `drawForeground` runs without error for each kind
  (smoke, via a `QPixmap`/painter or `viewport().grab()`).
- Readout: `_update_crop_readout(0, 100, 0, 200)` → panel label shows `"200 × 100 px"`.
- Panel: Guides combo present with the three items; Apply Crop starts disabled;
  checkbox label is "Neutral preview (for framing)"; Rotate label contains "↻".
- Full suite green.

## Out of scope

Diagonal/golden guides (chosen: thirds + center only); rule-of-thirds *snapping*;
any change to `core/crop.py`.
