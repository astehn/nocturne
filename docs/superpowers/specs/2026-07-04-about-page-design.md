# Quirky About Page — Design

**Date:** 2026-07-04
**App:** Nocturne (package `seestar_processor`)
**Status:** Approved (autonomous — user gave standing authorization to design, build, and merge;
all decisions locked in discussion, see below).

## Motivation

Nocturne's current About is a bare system message box (name, tagline, version, one line). The
user wants a **fun, quirky, data-driven credits page** that honours the open-source libraries
the app stands on, credits the creator honestly (ideas/orchestrator, *not* a developer),
credits the AI collaborator, and thanks the testers who donate real data. It gets its own
toolbar button (a nicer entry point than a buried menu item).

## Decisions (locked in discussion)

- **Tone:** full quirky/fun — playful astronomy framing, tasteful.
- **Placement:** a new **About** toolbar button on the right, immediately **left of the
  GraXpert/RC-Astro status chips**. (A Help button will join it later, when Help *content* is
  written — deferred per TODO.)
- **Data-driven:** contributors live in a JSON file (`assets/contributors.json`) read at
  display time, so adding a library or a tester is a data edit, not code.
- **Creator credit:** Andreas — *creator, ideas & orchestration*; explicitly "not a developer."
- **AI credit:** "in collaboration with Claude (Anthropic)," — a lighter line.
- **Testers:** a **"Photon Donors"** section, populated from the JSON. Ships **empty** (a
  friendly "be the first" line) until the user gets each person's consent to be named.
- **Presentation:** a **custom styled dialog** (dark theme, Nocturne wordmark, sections,
  scrollable), not the plain message box.
- Help content stays deferred (TODO: DO-LAST); only the About is built now.

## Scope

**In scope**
- `assets/contributors.json` — creator, AI credit, built-with libraries, works-with tools,
  photon-donors (empty).
- `ui/about.py` — `load_contributors()` + a rewritten, fun, data-driven `about_html()` (pure,
  testable). `help_html()` untouched.
- `ui/about_dialog.py` — a custom `AboutDialog(QDialog)` (wordmark + scrollable rich-text +
  Close), dark-themed.
- One `about` SVG icon + toolbar button (left of the status chips); both the toolbar button and
  the existing Help-menu "About" open the new dialog.

**Out of scope** — Help content/button (deferred); real tester names (added later, with
consent); any processing/behaviour change.

## Architecture

```
seestar_processor/
  assets/contributors.json     # NEW data
  assets/icons/about.svg       # NEW icon
  ui/about.py                  # load_contributors() + fun data-driven about_html()
  ui/about_dialog.py           # NEW AboutDialog (styled QDialog)
  ui/icons.py                  # add "about" to ICON_NAMES
  ui/main_window.py            # About toolbar button (left of chips); _show_about -> AboutDialog
  ui/theme.py                  # QSS for #aboutWordmark / #aboutBody (optional, token-based)
```

## Data — `assets/contributors.json`

```json
{
  "creator": { "name": "Andreas Stehn",
               "role": "Creator, chief orchestrator & ideas department (not a developer, and proud of it)" },
  "ai": "Code wrangled in collaboration with Claude (Anthropic)",
  "built_with": [
    { "name": "PySide6 / Qt", "what": "the whole interface" },
    { "name": "NumPy", "what": "the numeric backbone" },
    { "name": "astropy", "what": "reading & writing FITS" },
    { "name": "SciPy", "what": "filters & maths" },
    { "name": "scikit-image", "what": "image operations" },
    { "name": "astroalign", "what": "lining up the stars" },
    { "name": "SEP", "what": "finding & grading stars" },
    { "name": "colour-demosaicing", "what": "turning Bayer data into colour" },
    { "name": "tifffile", "what": "16-bit TIFFs" },
    { "name": "Pillow", "what": "image loading & saving" }
  ],
  "works_with": [
    { "name": "GraXpert", "what": "background extraction (free)" },
    { "name": "RC-Astro", "what": "BlurX / NoiseX / StarX (optional)" }
  ],
  "photon_donors": []
}
```

## `ui/about.py`

- `load_contributors(path: str | None = None) -> dict` — read the JSON from
  `assets/contributors.json` (default path resolved relative to the package, like the icons
  loader); on any read/parse error return a minimal safe dict so About never crashes.
- `about_html(data: dict | None = None) -> str` — pure function; if `data` is None it calls
  `load_contributors()`. Returns fun, sectioned HTML:
  - Header: `APP_NAME`, `APP_TAGLINE`, `Version {__version__}`.
  - **Dreamed up & directed by** — creator name + role.
  - **Code** — the AI line.
  - **The crew** (built_with) — each `name — what`, framed playfully ("the open-source legends
    doing the real heavy lifting").
  - **Plays nicely with** (works_with).
  - **Photon Donors** — the testers; if the list is empty, a friendly "Be the first to lend
    your light — share your subs!" line; otherwise the names.
  - Footer: a fun sign-off + "Made under the stars. Not affiliated with ZWO."
- `help_html()` unchanged.

## `ui/about_dialog.py`

`AboutDialog(QDialog)` — `setWindowTitle(f"About {APP_NAME}")`; a big **Nocturne** wordmark
label (objectName `aboutWordmark`), a scrollable `QLabel` (rich text = `about_html()`,
objectName `aboutBody`, `openExternalLinks` off), and a Close button. Dark-themed via existing
tokens; min size ~520×560. A module-level constructor takes no args (calls `about_html()`), but
accept an optional `html` param for tests.

## Toolbar wiring (`main_window.py`)

In `_build_toolbar`, after `tb.addWidget(spacer)` and **before** `self._tools_label`, insert:
`self._about_btn_act = tb.addAction(load_icon("about"), "About", self._show_about)` — so About
sits on the right edge, just left of the status chips. `_show_about` opens `AboutDialog(self)`
(replacing the `QMessageBox.about`); the Help-menu "About" also opens it. Add `"about"` to
`icons.ICON_NAMES` and create `assets/icons/about.svg` (a small info/star glyph).

## Error handling

- Missing/corrupt `contributors.json` → `load_contributors` returns a safe minimal dict; About
  still renders (creator/AI/footer from constants). Never crashes the toolbar or dialog.
- Unknown icon name is already guarded by the icons loader.

## Testing

Headless, fast:
- `about.load_contributors`: parses the shipped JSON; returns a dict with `built_with`
  non-empty; a bogus path returns the safe minimal dict (no raise).
- `about.about_html`: contains the creator name, the "not a developer" role, the Claude line,
  every built_with library name, both works_with tools, and — with empty photon_donors — the
  "Be the first" line; with a sample donor, that donor's name appears.
- `about_dialog`: constructs with injected HTML and shows the wordmark + body without error.
- `icons`: `about` is in `ICON_NAMES` and `assets/icons/about.svg` exists / is valid XML
  (covered by the existing icon tests once the name is added).
- `main_window`: the toolbar has an "About" action with a non-null icon; clicking `_show_about`
  opens an `AboutDialog` (or the action exists and is wired).

## Verification (by eye, after merge)

Launch → click **About** (right side, left of the tool chips): a dark, fun credits dialog with
the Nocturne wordmark, the crew of libraries, the "not a developer" creator line, the Claude
credit, and an empty-but-inviting Photon Donors section. Screenshot for the README.
