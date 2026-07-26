# Nocturne — community announcement / data request

Draft copy for posting in Seestar / astrophotography communities while gathering test data.
Trademark-safe: describes compatibility ("for the Seestar S30 Pro"), not affiliation. Nocturne is
the app name.

---

## Full version (Facebook groups)

**Nocturne — a free processing app I'm building for the ZWO Seestar S30 Pro (looking for test data 🙏)**

Like a lot of you, I quickly outgrew the phone-app processing on my Seestar and ended up bouncing
between Siril, PixInsight, GraXpert and RC-Astro tools — repeating basically the same steps every
single time. So I've been building a small, native desktop app that turns that repetitive workflow
into a **guided, one-step-at-a-time process**, dedicated to the S30 Pro.

What it does today:
- 🎨 **Narrowband colour** — turns a dualband (Ha/OIII) master into a finished colour image with
  natural **HOO** or Hubble-style palettes. Stars are separated (StarXTerminator) and screened back
  automatically, with an **OIII boost** to bring out the oxygen. Live preview; sliders to taste.
- 🔭 **Real deconvolution, denoise & star tools** — integrates **GraXpert** (free) and **RC-Astro**
  (BlurX / NoiseX / StarX). **Choose your denoise engine** (GraXpert or NoiseX), with free fallbacks
  if you own neither.
- 🧱 **Built-in stacking** — point it at a folder of subs; it grades/rejects, registers (handles
  alt-az field rotation), and integrates a master.
- 🧭 **Plate solving & sky annotation** — solves your image against the sky (via **ASTAP**) and
  can label the stars, galaxies, and nebulae in it.
- 🪄 **Guided, non-destructive steps** — crop, background extraction, colour calibration
  (including a **photometric/SPCC** option alongside the manual approach), deconvolution, stretch,
  core recovery (HDR), curves, levels, saturation, green removal (with a strength dial), noise
  reduction, local contrast, star reduction — each with simple Light/Medium/Strong choices or
  sliders, a **live before/after preview**, and full undo / jump-back.
- 🎯 **One-tap Auto Enhance** — a fast, fully automatic pass for a finished look, or a solid
  starting point to fine-tune from.
- ✨ **Artistic finishing (Enhancements)** — a stack of tap-to-apply finishing moves: narrowband
  palettes, tasteful **diffraction star-spikes**, targeted colour boosts, and more.
- 🧳 **Save & share** — **Saved Projects** (`.nocturne` files) keep a whole editing session so you
  can pick up right where you left off, and one-tap **Share** export reframes and captions your
  image for posting straight to social.
- 🔍 **Upscale Crop & Provenance report** — a non-destructive 2× crop upscale for zooming in
  without turning to mush, plus an exportable record of everything done to your image.
- ♻️ **Recipes & batch** — save your steps and apply them to a whole folder.
- 💾 Export 16-bit TIFF / PNG / FITS (incl. starless + stars).

It's a personal project (I'm the "orchestrator," built with a lot of AI help — I'm not really a
developer 😅), and it's now out: **free, open-source (GPLv3), on GitHub** — macOS (Apple Silicon)
for now. Grab it here: [GITHUB LINK]. Here's my problem: **I only got my Seestar a few weeks
ago**, and between learning the ropes and a run of cloudy nights, I've captured just a handful of
targets. To keep testing and tuning it properly — especially the newer stuff like plate solving
and photometric colour calibration — I need **variety**: different objects, different skies,
different integration times — and I simply don't have that yet.

So I'm asking for help: **if you'd be willing to share a stacked dualband/LP FITS master** (and raw
subs if you save them), I'd be hugely grateful.
- 📤 **Upload directly here (no account needed):** [UPLOAD LINK]
- …or drop a comment / DM me.

Contributors get credited in the app's "About" page (as **Photon Donors** ⭐). Any target, any sky
quality — honestly, the messier the better for stress-testing!

🔒 **Your data will only ever be used to test and improve Nocturne — nothing else.** It won't be
shared, sold, re-published, or used for anything beyond development testing.

Thanks 🙌 clear skies.

---

## Short version (2–3 lines)

**Nocturne**, a free guided processing app for the ZWO Seestar S30 Pro, is out (free, GPLv3, macOS
Apple Silicon — [GITHUB LINK]) — guided dualband → narrowband colour, built-in stacking, plate
solving, and GraXpert/RC-Astro integration (with a choice of denoise engine). I only got my Seestar
a few weeks ago (and the skies have not cooperated 🌧️), so I'm still short on data to tune it. If
you can share a
stacked dualband/LP **FITS master** (raw subs a bonus), upload here (no account needed): **[UPLOAD
LINK]** — or comment/DM 🙏. Your data is used **only** to test/improve Nocturne — never shared or
published. Contributors credited as ⭐ Photon Donors. Clear skies!

---

## Notes before posting

- Replace **[UPLOAD LINK]** before posting (see "Upload folder" below).
- Replace **[GITHUB LINK]** with the actual GitHub releases page URL before posting.
- Some groups restrict self-promotion — lead with the **data request**, not the tool, and avoid
  posting download/links unless the group allows it.
- Reassure on privacy: you're using their data only to test/tune, and crediting them (Photon Donors).
- Tailor tone per community (Reddit r/AskAstrophotography is more technical/no-hype than FB groups).

## Upload folder (recommended: Dropbox File Request)

For collecting files from lots of strangers, a **Dropbox "File Request"** is the cleanest option:
- Recipients **don't need a Dropbox account** and just drag files in.
- They **can't see each other's uploads** (privacy), and everything lands in one folder you control.
- You can set it up in Dropbox → **File requests → Create a request** → title it e.g. "Nocturne test
  data (Seestar dualband FITS)", pick a destination folder, and share the link.

Alternatives: a **Google Drive** folder set to "anyone with the link can upload" (but requires a
Google account and uploaders may see the folder), or a **Google Form** with a file-upload field
(good if you also want to capture target name / integration time / filter alongside each file).

Tip: ask contributors to include the **target, total integration time, and filter (LP/dualband vs
broadband)** in the filename or a comment — it makes the data far more useful for tuning.
