# Crop-panel "Unlink stretch" toggle — Design

**Date:** 2026-07-19
**Status:** Approved (design Q&A 2026-07-19)

## Problem

When a stacked Seestar FITS is first opened, the image is still **linear**, so the
preview is produced by `autostretch` → `linked_stretch`: one transfer function is
derived from luminance and applied to all three channels. That preserves the
overall sky-colour cast (light-pollution blue/green, twilight, moon), so the
whole pre-Stretch preview looks strongly tinted. This makes it hard to see the
subject while framing in the **Crop** step. The user's own words: "the entire
image is blue… makes it kind of hard to see in the crop menu."

The cast disappears later once the Stretch step runs (display then switches to
`clip(data)` and shows real processed colour), and again once the Color step
neutralizes the data — but during Crop the user is stuck with the tint.

## Goal

Give the user a **manual, display-only** control — like PixInsight's STF
link/unlink (chain) toggle — that neutralizes the tint in the preview when they
want it, without changing the default and without ever touching pixel data.

## Key insight (why this is low-risk)

`to_qimage` only stretches when `img.is_linear` is true; otherwise it shows
`clip(img.data)` directly. `is_linear` is true **only** for the freshly-opened,
pre-Stretch image (the Crop stage). Therefore an unlink toggle can affect *only*
the pre-Stretch preview — it is structurally incapable of altering the colours
the user tunes in Stretch / Color / Saturation later, and it never affects export
(export runs the real pipeline on real data). Both stretch functions
(`linked_stretch`, `unlinked_stretch`) already exist and are tested.

## Design

**Behaviour:** Manual toggle, **off by default** (linked stays the default). The
user checks it when they notice a tint; it never changes the view on its own.
Matches PixInsight's manual STF chain button.

**Placement:** A checkbox in the **Crop step panel**, labelled
`Unlink stretch (neutralize tint)`, with a one-line description. This is where the
tinted preview is actually seen. (It is hidden when the user leaves Crop, which is
fine: the tint is only visible on the linear/pre-Stretch image, i.e. the Crop
stage.)

**State:** `MainWindow._display_unlinked: bool` (default `False`). Display
preference only — not part of the project/edit history, not persisted to settings
(session-scoped is sufficient for v1).

### Data flow

1. `to_qimage(img, unlinked=False)` — new optional param. When `img.is_linear`:
   `unlinked_stretch(img.data)` if `unlinked` else `linked_stretch(img.data, _TARGET_BG)`
   (via `autostretch`). When not linear: unchanged (`clip`), so the param is a
   no-op off the linear path.
2. `MainWindow._refresh()` passes `to_qimage(img, self._display_unlinked)`.
3. `build_panel(... on_unlink_toggle=None, unlinked_checked=False)` — the crop
   branch adds the checkbox, sets its initial checked state from
   `unlinked_checked` (so it survives panel rebuilds), and connects `toggled` to
   `on_unlink_toggle`.
4. `MainWindow._on_unlink_toggle(checked)` sets `self._display_unlinked` and calls
   `self._refresh()` to re-render immediately.

### Interfaces

- `to_qimage(img: AstroImage, unlinked: bool = False) -> QImage`
- `build_panel(..., on_unlink_toggle=None, unlinked_checked: bool = False)`
- `MainWindow._display_unlinked: bool`
- `MainWindow._on_unlink_toggle(self, checked: bool) -> None`

## Testing

- **preview:** `to_qimage` on a synthetic tinted **linear** image — the max
  per-channel median spread of the output is smaller with `unlinked=True` than
  with `unlinked=False` (cast neutralized). On a **non-linear** image the two
  produce identical output (param is a no-op off the linear path).
- **panel:** the crop panel exposes the checkbox; `unlinked_checked=True` builds it
  checked; toggling emits `on_unlink_toggle` with the new state.
- **window:** `_on_unlink_toggle(True)` sets `_display_unlinked` and re-renders;
  the checkbox's state survives a `_rebuild_panel()` (round-trips through
  `unlinked_checked`).

## Out of scope (v1)

- Auto-detecting the tint and auto-switching (offered, user chose manual).
- A global toolbar button (user chose the Crop-panel checkbox).
- Persisting the preference across sessions.
