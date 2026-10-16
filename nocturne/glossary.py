"""The glossary: plain-words meanings of the terms a Seestar owner meets.

ONE list, two outputs — the in-app Help topic (help_body) and a website page
(website_page) — so the app and the site can never explain a word two ways.
Andreas, 2026-10-14: "the whole point of Nocturne is to be able to guide and
perhaps explain things to people like myself who does not really know".

Definitions are plain text (escaped on the way out), one to three sentences,
British spelling, no "AI". Any sentence about what NOCTURNE does is tied to
the code by a test in tests/ui/test_help_accuracy.py; general astronomy is not.
No Qt here: the website generator must run without it.
"""
from __future__ import annotations

import datetime as _dt
import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    term: str
    definition: str
    see: str | None = None          # a help topic id, for "More in"
    aliases: tuple[str, ...] = ()   # other names it is looked up and linked by

    @property
    def anchor(self) -> str:
        return "term-" + _slug(self.term)


def _ascii(s: str) -> str:
    # Greek read as Latin, so Hα files under H (before Histogram), not after Z.
    return s.replace("α", "alpha")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(s).casefold()).strip("-")


def sort_key(name: str) -> str:
    return _ascii(name).casefold()


_T = Term
TERMS: tuple[Term, ...] = (
    _T("Alt-az and equatorial mounts",
       "An alt-az mount moves up and down and side to side, like a camera tripod head, "
       "and a Seestar is one. As it follows a target the field slowly turns from frame "
       "to frame, which Stack corrects, and which leaves the ragged edges on a master. "
       "An equatorial mount (or a Seestar on a wedge) tilts its axis to match the "
       "Earth's, so the field does not turn.",
       "stacking", ("alt-az", "equatorial mount", "field rotation")),
    _T("Arcminute and arcsecond",
       "Small units of angle on the sky. A degree is split into 60 arcminutes (′), and "
       "each arcminute into 60 arcseconds (″). The full Moon is about 30′ across.",
       "plate-solve", ("arcminute", "arcsecond", "arcmin", "arcsec")),
    _T("Background extraction",
       "Removing the smooth glow (a gradient) that light pollution, moonlight or haze "
       "spreads across a picture, so the sky is even from corner to corner. Nocturne's "
       "Background step does it with GraXpert, and can show you exactly what it took away.",
       "background", ("gradient", "gradient removal", "light pollution")),
    _T("Bayer pattern",
       "The grid of red, green and blue filters over a colour camera's pixels, with two "
       "green for every red and every blue, so each pixel sees only one colour. "
       "Debayering fills in the two missing colours at each pixel from its neighbours, "
       "and Nocturne's Stack debayers every sub as it reads it.",
       "dualband", ("debayering", "debayer", "demosaicing")),
    _T("Black point",
       "The level at and below which everything shows as pure black. Raising it darkens "
       "the sky background; raise it too far and faint detail is crushed to black for "
       "good. You set it in Levels.",
       "levels"),
    _T("Bortle scale",
       "A nine-step scale for how dark a night sky is, from 1 at the darkest sites on "
       "Earth to 9 in a city centre. Most suburban gardens sit around 5 to 7. A darker "
       "sky means less gradient to remove and fainter detail within reach.",
       None, ("Bortle",)),
    _T("Broadband, narrowband and dual-band",
       "A broadband picture takes in all visible light, as through the Seestar's clear "
       "IRCUT filter. A narrowband filter passes only the thin slice of colour that one "
       "gas glows in. Dual-band passes two such slices at once: the Seestar's LP filter "
       "is dual-band, passing Hα and OIII.",
       "dualband", ("broadband", "narrowband", "dual-band", "dualband", "LP filter")),
    _T("Calibration frames",
       "Extra frames that record the camera's own faults so they can be taken out of the "
       "subs: darks (sensor glow and hot pixels), flats (dust shadows and dim corners) "
       "and bias (the sensor's read-out offset). Nocturne's Stack does not apply them: "
       "it combines the subs exactly as the Seestar saved them. If you shoot calibration "
       "frames, stack in a program that uses them, such as Siril, and open the master here.",
       "stacking", ("darks", "flats", "bias", "dark frames", "flat frames")),
    _T("Clipping",
       "Detail lost by pushing values past either end of the range: crushed means pushed "
       "to pure black, blown means pushed to pure white. No later step can bring it back. "
       "Nocturne counts both, per colour, under the histogram from Stretch onwards.",
       "readout", ("crushed", "blown", "clipped")),
    _T("Colour space",
       "The agreed meaning of the colour numbers in a file. sRGB is what screens and "
       "browsers assume, and the right choice almost always. Nocturne's Export also "
       "offers Display P3, Adobe RGB and ProPhoto RGB for 16-bit TIFF, for a program "
       "that works in that space; a wider space does not add colour.",
       "export", ("sRGB", "P3", "Display P3", "Adobe RGB", "ProPhoto RGB")),
    _T("Declination",
       "The sky's north–south coordinate, like latitude on Earth: 0° on the celestial "
       "equator, +90° at the north celestial pole and −90° at the south. Plate Solve's "
       "grid labels it in degrees, such as −14°.",
       "plate-solve", ("Dec",)),
    _T("Deconvolution",
       "Undoing some of the blur the optics and the air add, to tighten stars and "
       "sharpen fine detail. It belongs on linear data, and too much puts dark rings "
       "round bright stars. Nocturne uses BlurXTerminator if you have RC-Astro, "
       "otherwise a free built-in fallback.",
       "deconvolution"),
    _T("Degree",
       "Angles on the sky are measured like any other angle: 360 degrees (°) all the way "
       "round, and 90° from the horizon to straight overhead. The full Moon is about half "
       "a degree across, and a Seestar S30 Pro frame is about 4° wide.",
       "plate-solve", ("degrees",)),
    _T("Drizzle",
       "A way of stacking onto a finer grid than the camera's pixels, using the small "
       "drift between frames to recover detail the pixels were too coarse to hold. "
       "Nocturne's Stack offers it at ×2 only: the master has four times the pixels, and "
       "stacking takes much longer.",
       "stacking", ("drizzling",)),
    _T("Field of view",
       "How much sky one frame takes in, as a width and a height in degrees. It is set by "
       "the focal length and the size of the sensor: a Seestar S30 Pro covers about "
       "4° × 2.2°, an S50 about 1.3° × 0.7°.",
       "plate-solve", ("FOV",)),
    _T("FITS",
       "The standard file format of astronomy, and the one the Seestar saves. Alongside "
       "the pixels it carries a header of capture details (target, exposure, filter, "
       "camera), which Nocturne reads. A FITS export keeps the data as full-precision "
       "numbers, for another astronomy program.",
       "getting-started", ("FIT", "FTS")),
    _T("FWHM",
       "Full width at half maximum: how wide a star is, measured where it is half as "
       "bright as its centre. Smaller means sharper. Stack uses it to grade frames.",
       "stacking", ("full width at half maximum",)),
    _T("Histogram",
       "A graph of how many pixels sit at each brightness, dark on the left and bright on "
       "the right. Nocturne shows it at the top right. On an astro picture most pixels "
       "are sky background, so most of the graph is one tall peak towards the left.",
       "levels"),
    _T("HOO",
       "A two-gas palette: Hα in red, OIII in both green and blue, so hydrogen glows red "
       "and oxygen teal. It suits dual-band data, and is one of the palettes in "
       "Nocturne's Narrowband tool.",
       "narrowband"),
    _T("Hα",
       "Deep red light from hydrogen, at 656 nm, and the brightest glow of most emission "
       "nebulae. Through the Seestar's LP filter it lands on the red pixels, which is why "
       "dual-band frames come out red.",
       "dualband", ("Ha", "H-alpha", "hydrogen-alpha")),
    _T("Integration time",
       "The total exposure in a master: the number of subs kept times the length of each. "
       "190 subs of 10 seconds make about 32 minutes. More integration time gives a "
       "cleaner picture.",
       "stacking", ("total exposure",)),
    _T("Linear and stretched",
       "Linear data still holds values in proportion to the light that arrived, so "
       "straight out of stacking it looks almost black. Stretched data has had its faint "
       "values brightened so the eye can see them. Background extraction and "
       "deconvolution belong on linear data, tone and colour finishing on stretched.",
       "linear-vs-stretched", ("linear", "stretched", "linear data", "non-linear")),
    _T("Magnitude",
       "How bright a star looks, on a scale that runs backwards: a smaller number is "
       "brighter, and each step of 1 is about 2.5 times fainter. On a dark night the eye "
       "reaches about magnitude 6. Plate Solve lists the named stars in a picture with "
       "their magnitudes.",
       "plate-solve", ("mag",)),
    _T("Master",
       "The single image stacked from all the subs you kept, and the file you open in "
       "Nocturne to process. The Seestar app can save one after a session, or Nocturne's "
       "Stack builds one from the subs.",
       "stacking", ("stacked master", "master frame")),
    _T("Midtones",
       "The tones between the black point and the white point. The Midtones slider in "
       "Levels brightens or darkens the middle of the range without moving either end.",
       "levels", ("gamma",)),
    _T("Noise",
       "The random grain in a picture, from the light itself and from the sensor. It is "
       "always there: stretching only makes it visible, and stacking more frames makes it "
       "smaller next to the signal.",
       "noise_sharpen", ("grain",)),
    _T("OIII",
       "Teal light from doubly ionised oxygen, at 501 nm. It is usually much fainter than "
       "Hα, and through the Seestar's LP filter it lands on the green and blue pixels.",
       "dualband", ("O III", "oxygen")),
    _T("OSC and mono",
       "A one-shot colour (OSC) camera records colour in a single exposure through a grid "
       "of coloured filters over its pixels, and every Seestar is one. A mono camera has "
       "no such grid and builds colour from separate exposures through separate filters.",
       None, ("OSC", "mono", "one-shot colour", "monochrome")),
    _T("Pixel scale",
       "How much sky one pixel covers, in arcseconds. It follows from the pixel size and "
       "the focal length: a Seestar S30 Pro pixel covers about 3.7″, an S50 pixel about 2.4″.",
       "stacking", ("image scale",)),
    _T("Plate solving",
       "Working out exactly where in the sky a picture points, by matching its pattern of "
       "stars against a star catalogue. Nocturne does it with the free program ASTAP, and "
       "the result powers the labels, the RA/Dec grid and photometric colour calibration.",
       "plate-solve", ("plate solve", "plate-solving", "plate-solve")),
    _T("Preset",
       "Your own edit saved by name, as a starting point for the next picture of the same "
       "kind of object. Unlike a recipe it runs on the picture you have open, where you see "
       "every step and can change it.",
       "presets", ("presets",)),
    _T("Recipe",
       "The list of steps you applied, saved as a small .json file. Batch replays a recipe "
       "over a whole folder of masters without opening them.",
       "recipes", ("recipes",)),
    _T("Right ascension",
       "The sky's east–west coordinate, like longitude on Earth. It is counted in hours "
       "and minutes rather than degrees: the sky turns once in 24 hours, so one hour is "
       "15°. Plate Solve's grid labels it as, for example, 18h20m.",
       "plate-solve", ("RA",)),
    _T("SHO",
       "The Hubble palette: SII in red, Hα in green and OIII in blue. Real SHO needs a "
       "sulfur filter, so Nocturne does not offer it. SHO-style (gold and blue) in the "
       "Narrowband tool borrows only the look, made from Hα and OIII.",
       "dualband", ("Hubble palette",)),
    _T("Sigma clipping",
       "A way of combining frames that, pixel by pixel, throws out values that disagree "
       "with the rest before averaging. It removes satellite trails, aeroplanes and "
       "cosmic-ray hits, and is Stack's usual choice.",
       "stacking", ("sigma-clipped",)),
    _T("Signal-to-noise ratio",
       "How strong the real light from your target is compared with the grain on top of "
       "it. Stacking raises it: four times as many frames roughly doubles it.",
       "stacking", ("SNR", "S/N")),
    _T("SII",
       "Deep red light from sulfur, at 672 nm, and the third gas of the Hubble palette. A "
       "Seestar has no filter for it, so it cannot be captured, and Nocturne never invents it.",
       "dualband", ("S II", "sulfur")),
    _T("SPCC",
       "Spectrophotometric colour calibration: setting the colour balance from the stars "
       "themselves. Nocturne plate-solves the picture, looks up each star's measured colour "
       "in the Gaia catalogue, and balances red, green and blue so the stars match. On "
       "dual-band data it steps aside, because star colours there no longer follow the "
       "catalogue.",
       "color", ("photometric colour calibration", "photometric")),
    _T("Stacking",
       "Aligning many subs and combining them into one master, so the random noise "
       "averages away while the real signal builds up. Nocturne's Stack grades the "
       "frames, sets the poor ones aside, aligns the rest and combines them.",
       "stacking", ("stack",)),
    _T("Star separation",
       "Splitting a picture into a starless image (the nebula with the stars taken out) "
       "and a stars-only image, so each can be worked on separately and then put back "
       "together. Nocturne uses StarXTerminator if you have RC-Astro, otherwise StarNet2, "
       "otherwise its own built-in separator.",
       "tools", ("starless", "star split", "star removal", "stars-only")),
    _T("Stretch",
       "Brightening the faint parts of a linear image far more than the bright parts, so "
       "nebulosity and dust show without blowing out the stars. Nocturne's preview is "
       "stretched for display all along; the Stretch step writes a real stretch into the "
       "image.",
       "stretch", ("stretching",)),
    _T("Sub",
       "One single short exposure from the telescope, also called a sub-frame or a light "
       "frame. A night produces hundreds of them, and stacking combines them into a master.",
       "stacking", ("subs", "sub-frame", "subframe", "sub-exposure", "light frame", "lights")),
    _T("TIFF",
       "A common picture file that, at 16 bits, holds 65,536 levels per colour instead of "
       "the 256 of a PNG or JPEG. The extra levels keep smooth sky gradients free of "
       "banding when you edit further. Nocturne exports 16-bit TIFF and opens it too.",
       "export", ("16-bit TIFF", "TIF")),
    _T("White point",
       "The level at and above which everything shows as pure white. Pulling it down "
       "brightens the highlights, but whatever lies above it is blown to white and loses "
       "its colour. You set it in Levels.",
       "levels"),
)


def sorted_terms() -> list[Term]:
    return sorted(TERMS, key=lambda t: sort_key(t.term))


def lookup(name: str) -> Term | None:
    """The entry a name belongs to — its term or any alias, ignoring case."""
    key = name.casefold()
    for t in TERMS:
        if key == t.term.casefold() or key in (a.casefold() for a in t.aliases):
            return t
    return None


def _letters(terms) -> list[tuple[str, list[Term]]]:
    groups: dict[str, list[Term]] = {}
    for t in terms:
        groups.setdefault(sort_key(t.term)[0].upper(), []).append(t)
    return list(groups.items())


def _e(s: str) -> str:
    return html.escape(s, quote=False)


# --- In-app help --------------------------------------------------------------

HELP_INTRO = (
    "Astrophotography has a lot of its own words. Here each one is explained in plain "
    "words, in a line or two. Some words in the other help topics link here, and "
    "each entry links on to the topic that says more.")


def help_body(topic_titles: dict[str, str]) -> str:
    """The Help topic's HTML. `topic_titles` maps topic id -> title, for "More in"."""
    groups = _letters(sorted_terms())
    index = " &nbsp;".join(f'<a href="#letter-{k.lower()}">{k}</a>' for k, _ in groups)
    out = [f"<p>{_e(HELP_INTRO)}</p>", f"<p><b>{index}</b></p>"]
    for letter, terms in groups:
        out.append(f'<h4><a name="letter-{letter.lower()}"></a>{letter}</h4>')
        for t in terms:
            more = ""
            if t.see is not None:
                more = (f' <i>More in <a href="help:{t.see}">'
                        f"{_e(topic_titles[t.see])}</a>.</i>")
            out.append(f'<p><a name="{t.anchor}"></a><b>{_e(t.term)}</b><br>'
                       f"{_e(t.definition)}{more}</p>")
    return "".join(out)


# --- Website ------------------------------------------------------------------

# Help topics with a page of their own on nocturneastro.com. A term whose topic
# has none simply carries no link there; guessing a page would be worse.
WEBSITE_PAGES: dict[str, tuple[str, str]] = {
    "stacking": ("stacking.html", "Stacking"),
    "plate-solve": ("plate-solve.html", "Plate Solve"),
    "narrowband": ("narrowband.html", "Narrowband"),
    "dualband": ("narrowband.html", "Narrowband"),
    "presets": ("presets.html", "Presets"),
    "recipes": ("batch.html", "Recipes and Batch"),
}

WEBSITE_STANDFIRST = (
    "Astrophotography has a lot of its own words. This page explains the ones you meet "
    "with a Seestar and in Nocturne, each in a line or two. The same list is the "
    "Glossary in Nocturne's own Help.")


def website_page(updated: str | None = None) -> str:
    """A site/_src page (front matter + <main>) in the site's own conventions.

    Not written anywhere: the site is gitignored and deployed separately, so the
    caller decides where this goes (site/_src/glossary.html). No inline style or
    script — the site's CSP blocks both.
    """
    updated = updated or _dt.date.today().isoformat()
    groups = _letters(sorted_terms())
    chips = "".join(f'<a href="#letter-{k.lower()}">{k}</a>' for k, _ in groups)
    body = []
    for letter, terms in groups:
        body.append(f'        <h2 id="letter-{letter.lower()}">{letter}</h2>\n')
        for t in terms:
            page = WEBSITE_PAGES.get(t.see or "")
            more = (f' More on the <a href="{page[0]}">{_e(page[1])}</a> page.'
                    if page is not None else "")
            body.append(f'        <h3 id="{t.anchor}">{_e(t.term)}</h3>\n'
                        f"        <p>{_e(t.definition)}{more}</p>\n")
    return (
        "---\n"
        f"updated: {updated}\n"
        "title: Nocturne glossary — astrophotography terms in plain words\n"
        "description: Plain-words meanings of the astrophotography terms Seestar owners "
        "meet, from arcseconds and plate solving to stretching, clipping and dual-band "
        "filters.\n"
        "scripts: main.js\n"
        "---\n"
        '<main id="top">\n'
        '    <section class="page-head">\n'
        '      <div class="wrap prose">\n'
        '        <p class="eyebrow">Learn</p>\n'
        "        <h1>Glossary</h1>\n"
        f"        <p>{_e(WEBSITE_STANDFIRST)}</p>\n"
        f'        <nav class="toc" aria-label="Jump to a letter">{chips}</nav>\n'
        "      </div>\n"
        "    </section>\n"
        '    <section class="section-body">\n'
        '      <div class="wrap prose">\n'
        + "".join(body) +
        "      </div>\n"
        "    </section>\n"
        "</main>\n")
