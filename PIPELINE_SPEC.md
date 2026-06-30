# Seestar S30 Pro — Guided Editing Pipeline Spec

This document defines the editing workflow for the application. It is the source of
truth for **what each step does, what it hands to the next step, and what choices the
user gets**. Implement steps in this exact order. Do not invent extra user-facing options.

---

## Core concepts (read first)

1. **The data starts linear.** A stacked FITS from the Seestar looks almost black until
   it is *stretched*. Any preview shown before the stretch step must use a **temporary,
   non-destructive auto-stretch** for display only — the underlying data stays linear.

2. **Order is non-negotiable.** Some operations must run on linear data, some only after
   the stretch:
   - **Before stretch (linear):** crop, background/gradient removal, color calibration.
   - **The stretch:** converts linear → display data.
   - **After stretch (cosmetic):** saturation, noise reduction, sharpening.
   Running these out of order produces wrong results.

3. **One meaningful control per step, maximum.** The target user is a novice. The app
   does the heavy lifting automatically and exposes at most one slider or one 3-way
   preset per step. Never surface raw algorithm parameters.

4. **The pipeline has a shared core, then branches by destination.** An early choice
   decides how far the app processes and what it exports.

---

## Input assumptions

- Primary input: a **single stacked FITS** file (the Seestar live-stacks on-device, so
  most users import one already-stacked file).
- Sensor is **one-shot-color (OSC)** — color calibration / white balance is required.
- Stacking of raw subframes is **out of scope** for this spec (the device handles it).

---

## Step-by-step contract

### Step 1 — Import & assess
- **Purpose:** Load the stacked FITS, read its headers, and show the user a first preview.
- **Input:** A `.fit` / `.fits` file.
- **Process:** Validate the file; parse metadata (exposure, gain, target name, frame
  count, dimensions, bit depth); render a **temporary auto-stretched preview** for display.
- **Output / hand-off:** Validated **linear** image + parsed metadata.
- **User options:** None.

### Step 2 — Choose destination (the branch)
- **Purpose:** Decide where the workflow ends. Declared up front; the export itself
  happens at the final step.
- **User options (pick one):**
  - **A — Continue in external software** (e.g. Photoshop). App runs the shared core,
    then exports 16-bit TIFF and stops.
  - **B — Finish here.** App runs the full pipeline to a share-ready image.
- **Output / hand-off:** A `destination` flag (`external` | `in_app`) carried through
  the session.

---

### Shared core — Steps 3–6 (run on linear data, both destinations)

### Step 3 — Crop edges
- **Purpose:** Remove the ragged border left by stacking/dithering.
- **Input:** Linear image.
- **Process:** Auto-detect the usable rectangle and trim the artifact border.
- **Output / hand-off:** Clean-framed linear image.
- **User options:** Accept the auto-crop, or nudge the crop box.

### Step 4 — Background / gradient removal
- **Purpose:** Model and subtract light-pollution gradients so the background is even.
- **Input:** Cropped linear image.
- **Process:** Fit a background model and subtract it.
- **Output / hand-off:** Flattened linear image.
- **User options:** Strength — **off / light / strong**.

### Step 5 — Color calibration
- **Purpose:** Neutralize the background and set white balance (required for OSC).
- **Input:** Flattened linear image.
- **Process:** Automatic background-neutralization + white balance.
- **Output / hand-off:** Color-correct **linear** image.
- **User options:** None (automatic).

### Step 6 — Stretch
- **Purpose:** The "wow" step — convert linear → display data and reveal faint detail.
- **Input:** Color-correct linear image.
- **Process:** Auto-stretch with a live **before/after** preview.
- **Output / hand-off:** Nonlinear, **display-ready** image.
- **User options:** One control — an aggressiveness slider **or** a 3-way preset
  (**gentle / balanced / punchy**). This is the single most important user control.

---

## Branch: destination = `external`  → export and STOP

After Step 6, do **not** run the cosmetic steps. Go straight to export.

### Final step (external) — Export 16-bit TIFF
- **Purpose:** Hand off to external software for further post-processing.
- **User options (pick one):**
  1. **Single 16-bit TIFF** — stars + background together.
  2. **Two 16-bit TIFFs** — a **starless** image and a **stars-only** image.
- **Note:** Star/starless separation is an **export production option here — not an
  editing step.** It only exists on this path.
- **Output:** TIFF file(s); workflow ends.

---

## Branch: destination = `in_app`  → continue, Steps 7–9

### Step 7 — Color & saturation
- **Purpose:** Boost color now that it is visible (post-stretch).
- **Input:** Display-ready image.
- **Process:** Apply saturation/color enhancement.
- **Output / hand-off:** Color-enhanced image.
- **User options:** Saturation slider.

### Step 8 — Noise reduction & sharpening
- **Purpose:** Clean grain and recover detail.
- **Input:** Color-enhanced image.
- **Process:** Apply noise reduction + sharpening together.
- **Output / hand-off:** Cleaned, sharpened image.
- **User options:** **light / medium / strong**.

> **OPEN DECISION (default = no):** Optional in-app star-reduction step. Current spec
> leaves stars untouched on this path for simplicity; star separation lives only on the
> external path. Flip this default only if in-app star reduction is explicitly wanted.

### Step 9 — Final export
- **Purpose:** Produce the finished, share-ready file.
- **Input:** Final edited image.
- **Process:** Apply any final framing/crop, then export.
- **User options:** Format — **new FITS / PNG / 16-bit TIFF**.
- **Output:** Exported file; workflow ends.

---

## Summary of user-facing choices (the only ones that exist)

| Step | Choice |
|------|--------|
| 2 | Destination: external vs. finish in-app |
| 3 | Accept / adjust crop |
| 4 | Gradient removal: off / light / strong |
| 6 | Stretch: aggressiveness slider or gentle / balanced / punchy |
| External export | Single TIFF, or split starless + stars-only TIFFs |
| 7 | Saturation slider |
| 8 | Noise + sharpening: light / medium / strong |
| 9 | Export format: FITS / PNG / TIFF |

Every other parameter is automatic. Do not add controls not listed here.
