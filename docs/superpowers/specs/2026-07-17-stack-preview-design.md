# Stack dialog: judgeable preview + layout polish

**Date:** 2026-07-17
**Status:** Approved (approach A confirmed by user)
**Scope:** `nocturne/ui/stack_dialog.py`, `nocturne/core/autostretch.py`, small additions to `tests/`

## Problem

The stack dialog's frame preview is a fixed 300×220 QLabel showing a ~512 px
downsampled thumbnail with the *linked* display autostretch. Real Seestar subs
carry a strong sky-colour cast (blue/green/red depending on LP/twilight/moon),
so the thumbnail renders as a tiny tinted postage stamp. The preview exists so
the user can judge whether a rejection ("Stars softer…") is fair — at this size,
colour, and resolution that judgement is impossible. The dialog layout also
wastes space: the table can't trade space with the preview and the window opens
small.

## Design

### 1. Preview widget: reuse the editor's `ImageView`

Replace the `QLabel` preview with an `ImageView` (`nocturne/ui/image_view.py`)
instance. This brings, with zero new interaction code: cursor-centred wheel
zoom, drag-to-pan, fit-to-window, the floating −/fit/+ zoom pill, and the app's
canvas styling. Crop-overlay and before/after-compare features stay dormant
(never enabled by the dialog). On new image: `set_image(qimage)` — ImageView
fits on the first image or a size change and otherwise keeps the zoom/pan
transform, so same-size subs can be blink-compared at 1:1.

The empty state ("Select a frame to preview it") and the error state
("Preview failed: could not read frame") render as a centred overlay label on
top of the view (a plain QLabel in a stacked layout), since QGraphicsView has
no placeholder text.

### 2. Colour neutralization: unlinked autostretch

Add to `nocturne/core/autostretch.py`:

```python
def unlinked_stretch(data: np.ndarray, target: float = _TARGET_BG) -> np.ndarray:
    """Per-channel display stretch: each channel independently stretched to the
    same target background. Neutralizes any uniform sky-colour cast (the
    Siril-style preview stretch). 2D input falls back to linked_stretch."""
```

Implementation: for 3-channel input, apply the existing `_stretch_params` /
`_apply_params` per channel; for 2D input, delegate to `linked_stretch`.
The stack preview loader uses `unlinked_stretch`; the editor's display
autostretch stays linked (faithful colour) — no behaviour change outside the
stack dialog.

### 3. Full-resolution previews with a small LRU cache

`_load_preview_array` stops downsampling (the FITS read + debayer already
dominates; resolution was being thrown away). The QImage is built at full
sensor resolution so 1:1 zoom shows actual star shapes — the evidence needed to
accept or override a "soft stars" verdict.

Memory: a full-res RGB8 image is ~24 MB, so the cache changes from
"clear at >32" to a true LRU of 4 entries (`OrderedDict`, move-to-end on hit,
popitem(last=False) beyond 4 ≈ ~100 MB worst case). The cache stores full-res
`QImage`s — that is what `ImageView.set_image(qimage)` consumes (the old code
cached label-scaled `QPixmap`s; that scaling step disappears). Stale-result
guard and "never touch `_set_busy`" behaviour are unchanged.

### 4. Layout polish

- Table and preview live in a horizontal `QSplitter`; initial sizes ~55/45,
  user-draggable, preview pane absorbs extra width on resize
  (`setStretchFactor`).
- Dialog: `resize(1100, 700)` default (was min-width 560 only); fully
  resizable; minimum size 800×500.
- Table columns: File column `Stretch`; Use/Stars/FWHM/Bg
  `ResizeToContents`; Verdict takes remaining width. Every cell gets its full
  text as tooltip (long verdicts).
- Row navigation: no new code — ↑/↓ already move the current row and the
  preview follows, giving Siril-style blink review.

### 5. Error handling

- Unlinked stretch on an all-zero/constant channel: `_stretch_params` already
  guards degenerate inputs (existing behaviour); a channel that can't stretch
  renders as-is rather than crashing.
- Preview load failure: overlay label shows the failure text (stale-guarded,
  as fixed in the previous session).
- LRU eviction never evicts the currently displayed pixmap mid-view: eviction
  only trims the cache dict; the `ImageView` holds its own reference to the
  displayed QImage/pixmap, so display is unaffected.

### 6. Testing

- Unit (`tests/core/test_autostretch.py`): `unlinked_stretch` neutralizes a
  synthetic cast (channel medians equal after stretch, within tolerance);
  2D input delegates to linked; constant-channel input doesn't crash.
- UI (`tests/ui/test_stack_dialog.py`): preview pane is an `ImageView` and
  receives an image on row select (existing injectable-loader test adapted);
  LRU capped at 4 (5th load evicts oldest, re-select of evicted path reloads);
  splitter present with table and preview as its two widgets; empty-state
  overlay visible before any selection, hidden after a preview loads.
- Manual validation: NGC 7000 folder — confirm the blue cast is gone, zoom to
  1:1 on a "soft stars" reject vs a kept frame and confirm the difference is
  visible; drag the splitter; resize the dialog.

## Out of scope (deliberate)

- Editor `ImageView` refactor/extraction (approach C — rejected as YAGNI).
- Any change to the editor's linked display stretch.
- haoiii dialog preview (gets this for free only if it later reuses the same
  panel — tracked separately in TODO).
- A linked/unlinked toggle in the preview (YAGNI until asked; neutral is the
  right default for frame judgement).
