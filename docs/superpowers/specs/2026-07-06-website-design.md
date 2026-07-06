# Nocturne Website — Design

**Date:** 2026-07-06
**Project:** Nocturne marketing site — `nocturne.stehn.com`
**Status:** Approved — building under standing authorization.

## Motivation

Nocturne needs a home on the web — a simple but beautiful landing page that showcases what
it does and gets macOS users to download it. It will be hosted on the user's own VPS under
`nocturne.stehn.com`, served as static files by nginx.

## Decisions (from discussion)

- **Primary job:** showcase + download. The main call-to-action is *Download for macOS*; a
  smaller "contribute test data" section lives further down.
- **Tech:** a **self-contained static site** — `index.html` + one `styles.css` + images +
  a tiny bit of vanilla JS (smooth-scroll only). No framework, no build step, no external
  CDN/font calls (privacy + offline-safe). Drops straight into an nginx web root.
- **Visual:** matches the app — deep near-black navy background, nebula hero, teal accent
  (`#2dd4bf`), the aperture icon, subtle starfield. Fully responsive.
- **Download hosting:** the zipped `Nocturne.app` is hosted on the VPS; the button links to a
  single, clearly-marked URL constant that's easy to repoint (e.g. to GitHub Releases later).
- **License:** GPLv3 (shown in the footer).
- **Deferred (YAGNI):** analytics, a blog/docs section, multi-page, dark/light toggle,
  cookie banner (no tracking → none needed).

## Architecture / files

```
site/
  index.html          # the whole page (semantic sections)
  styles.css          # the visual system (custom properties + responsive)
  main.js             # ~15 lines: smooth-scroll for nav anchors, current-year in footer
  img/
    hero.png          # nebula hero (from docs/img)
    icon.png          # app icon (favicon + brand mark)
    screenshot-*.png  # UI screenshots (user-supplied; placeholder frame until then)
    favicon.png
  README.md           # deploy notes + sample nginx server block
```

Content is derived from the repo `README.md`, so the two stay consistent.

## Page structure (one scrolling page)

1. **Header/nav** — sticky, translucent: wordmark left; anchors right (Features · How it
   works · Download · GitHub). Collapses to a simple stack on mobile.
2. **Hero** — full-bleed dark nebula backdrop (image + gradient overlay for legibility),
   crisp HTML wordmark "Nocturne", the tagline, and two buttons: **Download for macOS**
   (primary, teal) with a "free · beta" sub-label, and **View on GitHub** (secondary).
3. **Features** — responsive card grid (icon + title + one line): Guided non-destructive
   flow · One-press Colourise · Built-in stacking · Ha/OIII extraction · Recipes & batch ·
   Targeted Enhancements. Icons are inline SVG (no icon-font dependency).
4. **Screenshots** — a framed showcase of the app in use (user screenshots from
   `site/img/`); until supplied, a tasteful placeholder panel with a note.
5. **How it works** — three short beats (Linear vs stretched · Dualband → colour ·
   Non-destructive), each a sentence, echoing the in-app Help voice.
6. **Requirements** — GraXpert (free, required) + RC-Astro (optional, free fallbacks); the
   honest "not affiliated with ZWO / GraXpert / RC-Astro" line.
7. **Download** — repeated primary button + install note (*unsigned beta → right-click →
   Open*) + system requirements (macOS; ~314 MB).
8. **Contribute data** — a compact Photon Donors call linking the data request
   (`docs/announcement.md` content), privacy line ("used only to improve Nocturne").
9. **Footer** — created by Andreas Stehn · built with the open-source stack · **GPLv3** ·
   © year · not affiliated.

## Visual system

- **Palette:** `--bg:#070c1a`, `--surface:#0e1730`, `--text:#e7ecf5`, `--muted:#9aa6bd`,
  `--accent:#2dd4bf` (teal), `--accent-2:#3f79d8` (blue). Matches the app theme + icon.
- **Type:** system font stack (`-apple-system, "Segoe UI", Roboto, sans-serif`); large
  tracking-tight display weight for the wordmark; comfortable body measure.
- **Texture:** a subtle CSS starfield (radial-gradient dots) behind sections; the nebula
  image only in the hero. Soft shadows, rounded cards, teal focus rings.
- **Motion:** minimal — smooth anchor scroll; gentle fade/rise on scroll is optional and
  CSS-only (`@media (prefers-reduced-motion)` respected).
- **Responsive:** single fluid column on mobile; the feature grid goes 3→2→1 columns.

## Download handling

`index.html` has one obvious constant (an HTML comment marks it) — the download `href`,
initially `https://nocturne.stehn.com/download/Nocturne.zip`. The button and the Download
section both use it. Repointing to GitHub Releases later is a one-line change.

## Deployment (documented in `site/README.md`)

Static files → nginx web root. Sample server block for `nocturne.stehn.com`
(root, `index.html`, gzip, long cache for `/img` and CSS/JS, TLS via the user's existing
certbot). No server-side code.

## SEO / sharing

`<title>`, meta description, canonical `https://nocturne.stehn.com/`, and Open Graph +
Twitter card tags (title, description, `og:image` = the hero) so shared links look good.
Favicon from the app icon.

## Error handling / robustness

- No external requests → nothing to fail at runtime; works offline and behind privacy tools.
- Missing screenshot images degrade to the placeholder panel (don't break layout).
- Buttons are plain `<a>` links — no JS required for the core page; `main.js` is progressive
  enhancement only.

## Testing / verification

- **Automated** (`tests/test_site_links.py`): parse `site/index.html`; assert every local
  asset it references (`src`/`href` starting with `img/`, `styles.css`, `main.js`) exists on
  disk — guards against broken links/typos. Assert the page contains the download URL, the
  GPLv3 mention, and the "not affiliated" line.
- **Manual (by eye):** open `site/index.html` in a browser; check the hero, feature grid,
  responsive behaviour (resize to phone width), and that no network requests go out
  (DevTools → Network is empty but for local files). The user reviews the rendered site and
  we tune the visuals.
- Full Python suite stays green.

## Verification (by eye)

Open `site/index.html`: a dark, nebula-lit landing page with a bold "Nocturne" hero and a
teal Download button; scannable feature cards; a screenshots strip; the honest requirements
+ not-affiliated note; a download section with the beta/unsigned caveat; a data-contribution
call; and a footer crediting the stack under GPLv3. Looks right on desktop and phone.
