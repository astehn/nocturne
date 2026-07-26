# Nocturne — Testers' Guide

*Guided astrophotography processing for the ZWO Seestar S30 Pro.*

## What it is

Nocturne turns the images your Seestar captures into finished, good-looking photos —
without you needing to learn complicated programs like PixInsight or Siril. It walks you
through the process one step at a time, shows you a live preview, and lets you undo anything.
It's made specifically for the Seestar S30 Pro, so a lot of the guesswork is already handled
for you.

## What you can feed it

- A single stacked image from the Seestar app (a `.fit` or `.fits` file), **or**
- A folder of individual frames ("subs"), if you turned on the Seestar's *save every frame*
  option. This unlocks the more powerful tools below.

## What you need installed

- **GraXpert** (free) — used for cleaning up the sky background. Recommended.
- **RC-Astro** tools (paid, optional) — make noise reduction, sharpening, and the star tools
  better. Everything still works without them, just with simpler built-in versions. There's a
  free trial if you want to try them.

Nocturne has a Settings page where you point it at these programs; a green check means it
found them, red means it didn't.

---

## The three main tools

### 1. Stack ("Stack…")
Combines many individual frames into one clean image — this is what makes faint nebulae and
galaxies show up. Point it at your folder of frames and it:
- Scores every frame and suggests throwing out the bad ones (clouds, wind, bad tracking).
  You get a checklist and can override its choices.
- Lines all the frames up perfectly (even as the sky slowly rotates during the night).
- Merges them while automatically removing satellite trails, aeroplanes, and hot pixels.
- Trims the ragged edges so you get a clean rectangle.

The result opens straight in the editor, ready to process.

### 2. Ha/OIII Extract ("Ha/OIII…")
A specialist tool for glowing gas clouds (emission nebulae) shot with the Seestar's built-in
dual-band filter. Instead of mixing the light into normal colour, it separates the two kinds
of light the nebula emits (**Ha** and **OIII**) and stacks each one on its own for a cleaner,
stronger result, then combines them into one image you can colour however you like. Also works
from a folder of frames.

### 3. Narrowband Palette ("Palette…")
Turns an emission-nebula image into the striking gold-and-teal "Hubble" look you see in famous
space photos. It:
- Removes the stars temporarily so they don't get in the way.
- Lets you recolour the nebula with simple sliders for each colour channel.
- Puts the stars back as clean white points on top.

You tweak it live until it looks the way you want.

---

## Other tools worth knowing about

Beyond the three tools above, a few other features are worth trying:

- **Auto Enhance** — a one-tap "just make it look good" pass, either as a fast finished result
  or a solid starting point to fine-tune from.
- **Plate Solve** — figures out exactly where your image is pointed (via ASTAP) and can
  annotate it with labelled stars, galaxies, and nebulae.
- **Saved Projects** — save your work as a `.nocturne` project file so you can close Nocturne
  and pick up exactly where you left off, edits and all.
- **Share** — a quick social-ready export: reframes your image and adds a caption band, ready
  to post.
- **Upscale Crop** — a non-destructive 2× upscale for when you want to zoom in on a crop
  without it turning to mush.
- **Provenance report** — exports a readable record of exactly what was done to your image,
  from capture through every processing step.

---

## The step-by-step editor

After you load or stack an image, Nocturne guides you through these steps, in order, one at a
time — and you can go back and redo any of them. Each shows a live preview and a before/after
comparison.

- **Import** — load a stacked image or a folder of frames to get started.
- **Crop** — trim the edges / rotate / flip. Drag a box on the image.
- **Background** — remove light pollution and uneven sky glow (uses GraXpert).
- **Color** — fix the colour so the background is neutral and stars look natural, with an
  optional **Photometric (SPCC)** mode that calibrates colour against real star catalogue data.
- **Deconvolution** — sharpen detail before stretching (RC-Astro BlurX-style), pulling in
  tighter stars and more resolved structure.
- **Stretch** — brighten the faint stuff so the nebula/galaxy becomes visible. One slider from
  gentle to strong.
- **Recover Core** — pull back blown-out bright cores (bright stars, galaxy centres) that
  stretching can clip to white.
- **Levels** — fine-tune brightness (black point, midtones, white point).
- **Curves** — an interactive tone curve for finer control over contrast and brightness.
- **Saturation** — boost colour intensity.
- **Remove Green Fringe** — de-green the halo that sometimes shows up around stars.
- **Noise Reduction** — smooth out graininess (better with RC-Astro, has a free fallback).
- **Local Contrast** — add "punch" and structure to the nebula.
- **Star Reduction** — shrink bright stars so the nebula stands out (uses RC-Astro).
- **Enhancements** — a set of tap-to-stack finishing moves (diffraction spikes, colour boosts,
  and more) you can layer on at the end.
- **Export** — save your finished image (see "Saving your work" below).

Helpful things throughout:
- **Undo / Redo** on everything.
- **Before/After** slider to compare.
- A live **histogram** (a graph of the image's brightness).
- A **log** that lists every step you did and how much it changed the image.
- Zoom and pan; "Fit" and "100%" buttons.
- A dark theme that's easy on the eyes at night.

---

## Doing many images at once

**Save Recipe + Batch** ("Save Recipe" and "Batch…") — once you've found a set of steps you
like, save them as a "recipe," then apply that same recipe automatically to a whole folder of
images. Great for processing several nights or targets the same way without repeating yourself.

## Saving your work

Export your finished image as:
- **TIFF** (best quality, for further editing)
- **PNG** (easy to share)
- **FITS** (keeps all the data, for re-processing later)

---

## A note for testers

This is early software and I'm testing it with real data from real Seestars — that's where you
come in. The most useful things you can share are:
- A **folder of individual frames** (*save every frame* on), **or**
- A **stacked `.fit` / `.fits` file** from the Seestar app.

Emission nebulae (like the North America Nebula, Orion, the Lagoon) are especially useful for
testing the colour tools. Thank you — your files directly help make this better!
