from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpTopic:
    """One help topic: a short summary plus a comprehensive HTML body."""
    id: str
    title: str
    summary: str
    body: str


@dataclass(frozen=True)
class HelpSection:
    """A table-of-contents grouping of topic ids."""
    title: str
    topic_ids: tuple[str, ...]


# Pipeline stage id -> help topic id. Stages not listed have no topic.
_STAGE_TO_TOPIC = {
    "load": "getting-started",
    "crop": "crop",
    "background": "background",
    "color": "color",
    "deconvolution": "deconvolution",
    "stretch": "stretch",
    "recover_core": "recover_core",
    "levels": "levels",
    "curves": "curves",
    "saturation": "saturation",
    "green_fringe": "green_fringe",
    "noise_sharpen": "noise_sharpen",
    "local_contrast": "local_contrast",
    "star_reduction": "star_reduction",
    "enhancements": "enhancements",
    "export": "export",
}


def stage_topic_id(stage_id: str) -> str | None:
    """The help topic id for a pipeline stage id, or None if it has no topic."""
    return _STAGE_TO_TOPIC.get(stage_id)


def topic(topic_id: str) -> "HelpTopic | None":
    """Look up a topic by id; None if unknown."""
    return TOPICS.get(topic_id)


def _t(id: str, title: str, summary: str, body: str) -> HelpTopic:
    return HelpTopic(id, title, summary, body)


# --- The content ------------------------------------------------------------
# Beginner-friendly and concept-teaching. Every step topic follows the
# "What it does / How to use it / Tips" shape. Kept accurate to how the app
# actually behaves.

_TOPIC_LIST = (
    # ---- Getting started ----
    _t("getting-started", "Getting started",
       "Turn a stacked Seestar image into a finished picture, one guided step at a time.",
       "<h4>What it does</h4>"
       "<p>Nocturne takes the stacked <b>FITS</b> file your Seestar S30 Pro produces and walks "
       "you through finishing it — crop, remove gradients, colour, stretch, and polish — as a "
       "guided, one-step-at-a-time flow. Nothing is destructive: you can undo, redo, or jump "
       "back to any earlier step at any time, and nothing is written to disk until you export.</p>"
       "<h4>How to use it</h4>"
       "<ol>"
       "<li>Open <b>Settings</b> and point Nocturne at your <b>GraXpert</b> program (required) "
       "and, if you have them, <b>RC-Astro</b> and <b>ASTAP</b> (both optional — ASTAP powers "
       "<b>Plate Solve</b>). Use <b>Test</b> to confirm each works.</li>"
       "<li>Click <b>Open FITS</b> and pick a stacked master (or use <b>Stack</b> to build one "
       "from a folder of subs).</li>"
       "<li>Work left-to-right through the steps in the sidebar — or click any step to jump to "
       "it. The panel on the right holds that step's controls; this box explains what it does.</li>"
       "<li>When you're happy, finish at <b>Export</b>.</li>"
       "</ol>"
       "<h4>Tips</h4>"
       "<p>The histogram (top-right) and the log (bottom) show what each step changed. "
       "Mouse wheel zooms, drag pans, and <b>Before/After</b> in the toolbar compares any step.</p>"),

    # ---- Concepts ----
    _t("linear-vs-stretched", "Linear vs. stretched",
       "Raw data is 'linear' and looks black; stretching reveals the faint detail.",
       "<h4>The idea</h4>"
       "<p>Straight out of stacking, astro data is <b>linear</b>: almost all the interesting "
       "signal sits in a tiny range of very dark values (around 0.003 out of 1.0). On its own it "
       "looks nearly black. To see it, the brightness has to be <b>stretched</b> — the faint "
       "values pulled up so nebulosity and dust become visible.</p>"
       "<h4>Preview vs. real stretch</h4>"
       "<p>Nocturne's preview <i>always</i> auto-stretches the image just so you can see it — "
       "much like PixInsight's Screen Transfer Function. That's display-only: the data underneath "
       "is still linear. The <b>Stretch</b> step is what commits a real stretch to the data so it "
       "matches the preview. Steps after Stretch (Levels, Saturation, and the rest) need real "
       "stretched data — so if you skip Stretch, Nocturne applies a sensible default for you when "
       "you move on.</p>"
       "<h4>Why it matters</h4>"
       "<p>Gradient removal and deconvolution work best on <b>linear</b> data (before Stretch); "
       "tone and colour polishing work on <b>stretched</b> data (after). The pipeline is ordered "
       "to put each step where it belongs.</p>"),

    _t("dualband", "Dualband, narrowband & Ha/OIII",
       "Your Seestar 'LP' filter is a dualband narrowband filter — that's why frames look red.",
       "<h4>The idea</h4>"
       "<p>The Seestar S30 Pro's <b>LP</b> filter is a <b>dualband</b> filter: it passes two "
       "narrow bands of light — <b>Ha</b> (hydrogen, deep red) and <b>OIII</b> (oxygen, teal). "
       "Most emission nebulae glow strongly in Ha, which is why your raw frames look red.</p>"
       "<h4>What you can and can't do</h4>"
       "<p>Classic <b>SHO</b> ('Hubble palette') needs three separate filters, which the Seestar "
       "can't capture — so SHO isn't possible from a single dualband master. Two-gas colour "
       "schemes (HOO, Foraxx-style) are the natural fit and look excellent.</p>"
       "<h4>Working with the channels</h4>"
       "<p>The <b>Ha/OIII</b> tool in the toolbar splits a dualband master into separate Ha and "
       "OIII masters, so you can combine them into a two-gas image in your tool of choice.</p>"),

    _t("step-order", "Why the step order matters",
       "Some steps belong on linear data, others after the stretch — the flow keeps them in order.",
       "<h4>The idea</h4>"
       "<p>Post-processing isn't arbitrary — each operation assumes the data is in a particular "
       "state. Getting the order right is most of what makes results predictable.</p>"
       "<h4>Before the stretch (linear)</h4>"
       "<p><b>Crop</b>, <b>Background</b> (gradient removal) and <b>Deconvolution</b> (sharpening) "
       "belong on linear data, before the image is stretched. Gradients and the telescope's blur "
       "are properties of the raw light, best corrected there.</p>"
       "<h4>After the stretch (display)</h4>"
       "<p><b>Levels</b>, <b>Saturation</b>, <b>Noise Reduction</b>, <b>Local Contrast</b>, "
       "<b>Star Reduction</b> and <b>Enhancements</b> are tone and colour polish — they work on "
       "the stretched image you can actually see. Nocturne enforces this ordering, and auto-"
       "stretches for you if you jump ahead, so a finishing step never lands on linear data.</p>"),

    _t("history", "Non-destructive history",
       "Every step is cached; undo, redo, and jump-back are instant and lossless.",
       "<h4>What it does</h4>"
       "<p>Nocturne remembers the result of every step. Nothing overwrites your original — the "
       "loaded image is always the untouched starting point, and each step stacks on top of it.</p>"
       "<h4>How to use it</h4>"
       "<ul>"
       "<li><b>Undo / Redo</b> (toolbar) step back and forward instantly.</li>"
       "<li><b>Before/After</b> compares the current step against the one before it.</li>"
       "<li>Click an earlier step in the sidebar to <b>jump back</b>; changing it re-runs only "
       "the steps from there onward.</li>"
       "<li><b>Reset</b> returns to the freshly-loaded image.</li>"
       "</ul>"
       "<h4>Tips</h4>"
       "<p>Because nothing is destructive, experiment freely — you can always step back. Data is "
       "only written to disk when you <b>Export</b>.</p>"),

    _t("readout", "Hover readout & clipping warning",
       "A pixel readout under your cursor, plus a warning when tones are clipping.",
       "<h4>What it does</h4>"
       "<p>Hover anywhere over the image and a small pill in the bottom-left corner reports the "
       "pixel underneath: its position, its <b>R G B</b> values (a single <b>V</b> for a mono "
       "image), and — for colour images — its <b>L</b> (luminance, the brightness the eye actually "
       "perceives). It hides itself during <b>Crop</b>, where you're framing rather than judging "
       "tone, and reappears on every step from there on.</p>"
       "<h4>Why the numbers look tiny before Stretch</h4>"
       "<p>Before the <b>Stretch</b> step your data is still <b>linear</b> — almost all the signal "
       "sits around 0.003 out of 1.0 (see the Linear vs. stretched topic). Nocturne's preview always "
       "auto-stretches the image just so you can see it, but the pill reports the real number "
       "underneath, not the brightened pixel on screen — so pre-Stretch it shows four decimal places "
       "and tags the reading <b>linear</b>, a reminder that the value and the brightness you're "
       "looking at are two different things there. From Stretch onward the data itself matches what "
       "you see, so the tag disappears and two decimals are enough.</p>"
       "<h4>The clipping summary and overlay</h4>"
       "<p>From <b>Stretch</b> onward, the panel under the histogram also reports how much of the "
       "image is <b>clipped</b> — pushed all the way to pure black or pure white in the 8-bit image "
       "an export would produce — as a percentage of highlights and shadows, naming whichever "
       "channel is worst. Past a threshold the line turns amber as a warning. Tick <b>Show "
       "clipping</b> to paint the clipped pixels directly on the canvas — shadows in blue, "
       "highlights in red — live, even while you're dragging a Levels or Curves slider.</p>"
       "<h4>Tips</h4>"
       "<p>A scatter of red dots on stars is almost always their <b>saturated cores</b> — blown at "
       "capture, not something an edit did or can fix — so don't chase it away. A solid "
       "<b>region</b> turning red or blue, on the other hand, means a real edit (a Levels white "
       "point pulled too far in, say) is crushing detail, and is worth backing off. The overlay and "
       "summary work on every step from Stretch on, so you can leave it ticked and watch it react "
       "as you work.</p>"),

    # ---- The steps ----
    _t("crop", "Crop, rotate & flip",
       "Trim the ragged stacking edges and frame your target.",
       "<h4>What it does</h4>"
       "<p>Removes the uneven edges left by stacking (where subs didn't fully overlap) and lets "
       "you frame, rotate, and flip the image.</p>"
       "<h4>How to use it</h4>"
       "<p>Drag the box to choose the keep-area, pick an aspect ratio if you want a standard "
       "shape, and use rotate / flip to orient the target. Apply to commit.</p>"
       "<h4>Tips</h4>"
       "<p>Crop early — later steps then work on your final framing, and gradient removal has a "
       "cleaner frame to model.</p>"),

    _t("background", "Background extraction",
       "Remove light-pollution gradients so the sky is even.",
       "<h4>What it does</h4>"
       "<p>Uses <b>GraXpert</b> to model and subtract the smooth glow of light pollution and "
       "sky gradients, leaving an even background so the real signal stands out.</p>"
       "<h4>How to use it</h4>"
       "<p>Choose <b>light</b> for most images, <b>strong</b> when the gradient is heavy. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Don't be alarmed if the sky looks a little <b>redder</b> afterwards — that's expected. "
       "Light pollution is often bluish, so removing it leaves the naturally red nebulosity more "
       "prominent. The next step, <b>Color</b>, neutralises any residual cast. Needs GraXpert "
       "(set its path in Settings).</p>"),

    _t("color", "Color calibration",
       "Neutralise the sky background automatically.",
       "<h4>What it does</h4>"
       "<p>Samples your empty sky and neutralises any leftover colour cast so the background is a "
       "clean grey — <i>without</i> touching your nebula's real colour. It measures the sky "
       "itself (not the whole frame), so red or teal nebulosity is preserved rather than washed "
       "out. Optional green removal (SCNR) is there if a green tinge remains.</p>"
       "<h4>How to use it</h4>"
       "<p>Pick a <b>Method</b> and apply. <b>Sky balance</b> (the default) neutralises the sky "
       "cast automatically. <b>Photometric (SPCC)</b> instead calibrates colour against real "
       "star measurements — it identifies stars in the field and balances the channels to their "
       "catalogue colours, for a more scientifically-accurate white balance (best on a plate-"
       "solvable field). You'll usually <i>not</i> need <b>Remove Green</b>; use it only if stars "
       "or background still take on a green tinge. Remove Green has a <b>strength</b> dial with a "
       "live preview — start gentle (the default) and drag up only as far as the green needs; "
       "full strength can flatten real nebula colour, so a light touch usually wins.</p>"
       "<h4>Tips</h4>"
       "<p>This is the step that cleans up the colour left over after Background extraction. It's "
       "mainly for broadband/OSC data. Photometric (SPCC) needs enough stars to match, so it "
       "suits star-rich fields.</p>"),

    _t("deconvolution", "Deconvolution",
       "Sharpen stars and recover fine detail on the linear image, before stretch.",
       "<h4>What it does</h4>"
       "<p>Corrects the small blur every telescope adds, tightening stars and recovering fine "
       "detail. It runs on the <b>linear</b> image (before Stretch), which is where deconvolution "
       "works best. Uses <b>BlurXTerminator</b> if you have RC-Astro, or a free sharpening "
       "fallback otherwise.</p>"
       "<h4>How to use it</h4>"
       "<p>Pick <b>light</b>, <b>medium</b>, or <b>strong</b>. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>The Seestar is undersampled (big pixels for its focal length), so keep this "
       "conservative — light or medium usually looks best. Strongest with RC-Astro installed.</p>"),

    _t("stretch", "Stretch",
       "Reveal faint detail by committing a real non-linear stretch.",
       "<h4>What it does</h4>"
       "<p>Applies the real, permanent stretch that turns the dark linear data into a visible "
       "image — pulling faint nebulosity and dust up out of the shadows.</p>"
       "<h4>How to use it</h4>"
       "<p>Use the aggressiveness slider: the middle roughly matches the preview you already see; "
       "higher reveals more faint signal (and more noise). Apply.</p>"
       "<h4>Tips</h4>"
       "<p>If you move past this step without stretching, Nocturne commits a sensible default "
       "stretch automatically so the later steps work.</p>"),

    _t("levels", "Levels",
       "Fine-tune black point, midtones, and white point against the histogram.",
       "<h4>What it does</h4>"
       "<p>Precise control over the tonal range: set where black begins (black point), adjust the "
       "midtones (gamma), and set the white point — read against the histogram top-right.</p>"
       "<h4>How to use it</h4>"
       "<p>Nudge the <b>black point</b> up slightly to deepen the background; use <b>gamma</b> to "
       "brighten or darken midtones; pull the <b>white point</b> in to lift highlights. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Levels works on the <b>stretched</b> image — on still-linear data even a tiny black "
       "point would clip everything to black, so it must come after Stretch. Nocturne handles "
       "that ordering for you. Small black-point nudges go a long way.</p>"),

    _t("curves", "Curves",
       "Shape a tone curve to add midtone contrast.",
       "<h4>What it does</h4>"
       "<p>Bends the tones with a smooth curve. Where Levels sets the black point, "
       "midtone brightness and white point, Curves lets you add <b>contrast</b> in "
       "the middle — steepening the slope so the nebula gains punch — while leaving "
       "the darkest and brightest tones anchored.</p>"
       "<h4>How to use it</h4>"
       "<p>Click the curve to add a point, drag to move it, double-click to remove it. "
       "The faint histogram behind the grid shows where the sky and nebula sit — drop a "
       "point on the sky peak and leave it to pin the background, then lift the midtones. "
       "Or press <b>Add contrast</b> for a gentle S. Watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Small moves go a long way. A steep curve can crush the faint outer nebulosity "
       "into the background — keep an eye on the dim detail as you pull.</p>"),

    _t("saturation", "Saturation",
       "Mute or boost colour intensity.",
       "<h4>What it does</h4>"
       "<p>Adjusts overall colour intensity — from muted to vivid.</p>"
       "<h4>How to use it</h4>"
       "<p>Drag left to mute, right to boost; the centre is no change. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Gentle boosts look natural and bring out nebula colour; heavy boosts also amplify "
       "colour noise in the background, so go easy.</p>"),

    _t("green_fringe", "Remove Green Fringe",
       "Remove the green colour fringe around stars.",
       "<h4>What it does</h4>"
       "<p>Stars are never truly green, so a green fringe or halo around them is an "
       "artifact (chromatic aberration or debayering). It suppresses the green excess "
       "only in the region around stars, so the nebula and background colour are left "
       "untouched. With <b>StarXTerminator</b> (RC-Astro) the stars are cleanly split "
       "out first for the most precise result; without it, a built-in star detector "
       "finds the stars and de-greens around them in place.</p>"
       "<h4>How to use it</h4>"
       "<p>Raise <b>Strength</b> until the green fringe on the stars fades (0 = off). "
       "The star detection runs once when you enter the step, then the slider previews "
       "instantly. Works without RC-Astro; setting RC-Astro (StarXTerminator) in "
       "Settings gives a cleaner separation.</p>"
       "<h4>Tips</h4>"
       "<p>A little usually does it. Because only the stars are affected, you can be "
       "fairly aggressive without shifting the overall colour. Removing the green often "
       "leaves the star a touch blue — a perfectly natural star colour.</p>"),

    _t("noise_sharpen", "Noise Reduction",
       "Smooth grain without smearing detail.",
       "<h4>What it does</h4>"
       "<p>Reduces the grainy noise the stretch amplifies, using <b>NoiseXTerminator</b> "
       "(RC-Astro) or a free fallback.</p>"
       "<h4>How to use it</h4>"
       "<p>Choose <b>light</b>, <b>medium</b>, or <b>strong</b>. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Denoise after stretching (which is where the grain shows). Don't overdo it — too much "
       "smears fine structure and stars. Light is often enough on a well-stacked master.</p>"),

    _t("recover_core", "Recover Core",
       "Pull blown-out bright cores back so they show detail.",
       "<h4>What it does</h4>"
       "<p>Short exposures blow out the bright centre of targets like M42, M8 or a "
       "galaxy nucleus — after stretching it becomes a featureless white blob. "
       "Recover Core pulls those highlights back down and re-expands the structure "
       "hiding inside them, so the core shows swirls and detail instead of pure white.</p>"
       "<h4>How to use it</h4>"
       "<p>Drag <b>Strength</b> up until the core shows detail without looking flat or "
       "grey. 0 = off. Watch the live preview. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Only the brightest regions are affected — the sky and faint nebulosity are "
       "left alone. Recover Core brings back detail that is still hiding in a bright, "
       "compressed core; but if a core is completely clipped to pure white in the data "
       "there is nothing left to recover, and it simply stays white.</p>"),

    _t("local_contrast", "Local Contrast",
       "Add mid-scale depth so nebulosity pops.",
       "<h4>What it does</h4>"
       "<p>Boosts mid-scale structure — the difference between neighbouring regions — so "
       "nebulosity and dust gain depth and dimensionality.</p>"
       "<h4>How to use it</h4>"
       "<p>Pick <b>light</b>, <b>medium</b>, or <b>strong</b>. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Subtle usually wins — strong local contrast can look crunchy and exaggerate noise.</p>"),

    _t("star_reduction", "Star Reduction",
       "Shrink stars so nebulosity takes centre stage.",
       "<h4>What it does</h4>"
       "<p>Reduces the size and dominance of stars, so a busy star field stops competing "
       "with the nebula. With <b>StarXTerminator</b> (RC-Astro) the split is cleanest; "
       "without it, a built-in star detector is used instead.</p>"
       "<h4>How to use it</h4>"
       "<p>Choose <b>light</b>, <b>medium</b>, or <b>strong</b>. Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Works without RC-Astro; RC-Astro gives a cleaner separation. A little goes a "
       "long way — over-reduction leaves an unnatural, starless-looking frame. It pairs "
       "well just before the Enhancements step.</p>"),

    _t("star_spikes", "Star Spikes",
       "Add diffraction spikes to the brightest stars.",
       "<h4>What it does</h4>"
       "<p>Refractor scopes like the Seestar produce no diffraction spikes — the "
       "four-point flares many people associate with an astrophoto. This tool draws "
       "tasteful, colour-matched spikes on the brightest stars. It is a purely artistic "
       "choice, so it lives in the toolbar rather than the processing steps.</p>"
       "<h4>How to use it</h4>"
       "<p>Finish your normal processing first, then click <b>Star Spikes…</b> in the "
       "toolbar. <b>Length</b> sets how long the spikes are (0 = off), <b>Intensity</b> "
       "how bright or transparent they are (100% = full strength), <b>Number of stars</b> "
       "how many of the brightest stars get spikes, and <b>Rotation</b> tilts the cross. "
       "Watch the live preview, then Apply.</p>"
       "<h4>Tips</h4>"
       "<p>Less is more — a few long spikes on the brightest stars looks intentional; "
       "spikes on everything looks fake. Keep the count low.</p>"),

    _t("narrowband", "Narrowband",
       "Natural Hubble-palette colour from dual-band (Ha + OIII) data.",
       "<p>The Seestar dual-band filter captures two real signals: <b>Ha</b> "
       "(hydrogen, red) and <b>OIII</b> (oxygen). Because Ha is usually much "
       "stronger than OIII, a plain colour combine looks orange. Narrowband first "
       "lifts the weak OIII up to Ha's level, so oxygen shows as real teal/blue.</p>"
       "<h4>How to use it</h4>"
       "<p>Finish your normal processing first (Narrowband works on the stretched "
       "image), then click <b>Narrowband…</b> in the toolbar. Pick a <b>Palette</b>, "
       "and use <b>OIII boost</b> to bring out the oxygen — it is the key control for "
       "Seestar data. <b>Protect background</b> keeps the dark sky its natural colour; "
       "<b>Preserve lightness</b> keeps your tonal structure while only the colour "
       "changes. Watch the live preview, then Apply.</p>"
       "<h4>Palettes</h4>"
       "<p><b>HOO</b> — natural (red-gold nebula, teal oxygen). "
       "<b>Pseudo-SHO</b> — a gold/teal &quot;Hubble&quot; look. "
       "<b>Pseudo-bicolor</b> — magenta nebula, green oxygen. There is no real sulfur "
       "(SII) in dual-band data, so the pseudo palettes are stylistic arrangements of "
       "the two real signals.</p>"
       "<h4>Stars</h4>"
       "<p>With StarXTerminator (RC-Astro) installed, stars are removed first so they "
       "keep their natural colour, then added back on top. Without it, the whole image "
       "is recoloured and star colour may look off.</p>"
       "<h4>Credit</h4>"
       "<p>Normalization concept and palette formulas by Bill Blanshan &amp; Mike "
       "Cranfield (PixInsight NarrowbandNormalization).</p>"),

    _t("enhancements", "Enhancements",
       "Targeted, tap-to-stack finishing moves for colour, stars, dust, and glow.",
       "<h4>What it does</h4>"
       "<p>A bank of ten gentle finishing taps, grouped by what they touch:</p>"
       "<ul>"
       "<li><b>Colour boosts</b> — <b>Boost Red</b> (Ha), <b>Boost Cyan</b> (OIII), "
       "<b>Boost Blue</b>, <b>Boost Gold</b>: hue-selective saturation lifts.</li>"
       "<li><b>Vibrance</b> — a smart, oversaturation-resistant pop that lifts the muted colours "
       "more than the already-vivid ones.</li>"
       "<li><b>Star Colour</b> — brings out the natural colour of stars (blue-white through gold) "
       "using a star/starless split, so only the stars gain colour, not the nebula.</li>"
       "<li><b>Darken Sky</b> / <b>Lighten Sky</b> — shadow-masked background adjustments.</li>"
       "<li><b>Dark Structure</b> — adds definition to dust lanes and dark nebulae.</li>"
       "<li><b>Soft Glow</b> — a dreamy Orton-style bloom over the bright signal.</li>"
       "</ul>"
       "<h4>How to use it</h4>"
       "<p>Tap a button to apply one gentle nudge; tap again to stack more. Each tap is its own "
       "undoable step, so you can dial the effect in and back it off precisely.</p>"
       "<h4>Tips</h4>"
       "<p>The colour boosts are hue-selective — Boost Red only deepens red areas and leaves teal "
       "alone, and Boost Gold warms golden-brown dust lanes. The sky moves are shadow-masked, so "
       "they only touch the dark background and leave nebula and stars untouched. Star Colour "
       "takes a moment on its first tap while it separates the stars. Dark Structure and Soft Glow "
       "are subtle by design — stack a few taps to taste.</p>"),

    _t("export", "Export",
       "Save your finished image.",
       "<h4>What it does</h4>"
       "<p>Writes the finished image to disk.</p>"
       "<h4>How to use it</h4>"
       "<p>Choose a format: <b>16-bit TIFF</b>, <b>PNG</b>, or <b>FITS</b>. Or export a "
       "<b>starless + stars</b> pair (two TIFFs) for compositing elsewhere — that needs "
       "RC-Astro. The stars image is <i>unscreened</i>, so recombine the two with a "
       "<b>Screen</b> blend to reconstruct the image exactly.</p>"
       "<h4>Tips</h4>"
       "<p>TIFF and FITS preserve the most information for further editing; PNG is best for "
       "quick sharing. You can also export earlier in the flow (even a linear file) if you want "
       "a clean base to finish in another tool.</p>"),

    # ---- Tools ----
    _t("tools", "External tools: GraXpert, RC-Astro & ASTAP",
       "GraXpert is free and required; RC-Astro and ASTAP are optional and add extra power.",
       "<h4>GraXpert (free, required)</h4>"
       "<p>Powers <b>Background extraction</b> (and, optionally, Noise Reduction). It's free — "
       "download it, then set its path in <b>Settings</b> and press <b>Test</b>.</p>"
       "<h4>RC-Astro (paid, optional)</h4>"
       "<p>Adds <b>BlurXTerminator</b> (deconvolution), <b>NoiseXTerminator</b> (noise), and "
       "<b>StarXTerminator</b> (the star/starless split behind Star Reduction, Star Colour, the "
       "nebula saturation boost, Remove Green Fringe, and the starless+stars export). "
       "Set its path in Settings and Test it.</p>"
       "<h4>ASTAP (free, optional)</h4>"
       "<p>A free plate-solver that powers <b>Plate Solve</b> — identifying the field and "
       "annotating it with catalogue objects, named stars, a compass, and a scale bar. It also "
       "helps the Photometric (SPCC) colour method. Download ASTAP and its star database, then "
       "set its path in Settings and Test it.</p>"
       "<h4>Do I need the optional tools?</h4>"
       "<p>No — every RC-Astro step has a built-in free fallback, so the whole app works without "
       "it; RC-Astro simply makes those steps noticeably better. ASTAP is only needed for plate "
       "solving/annotation. Nocturne isn't affiliated with any of these tools.</p>"),

    _t("auto-enhance", "Auto Enhance",
       "One tap from a raw master to a finished picture.",
       "<h4>What it does</h4>"
       "<p>Runs a complete, sensible processing plan for you — background, colour, stretch, and "
       "finishing polish — from your cropped frame, in a single click. A great starting point, or "
       "a quick finished result when you don't want to work through every step.</p>"
       "<h4>How to use it</h4>"
       "<p><b>Crop your image first</b> — Auto Enhance only becomes available once you've cropped, "
       "and it works from that cropped frame, so your composition is respected. Then click "
       "<b>Auto Enhance</b>; it replaces any processing you've done, so it asks before discarding "
       "it (your crop is kept).</p>"
       "<h4>Tips</h4>"
       "<p>You can keep editing from the result, or <b>Undo</b> straight back to where you were. "
       "It always aims for natural, photometric-style colour — for narrowband looks, use the "
       "Narrowband tool instead.</p>"),

    _t("plate-solve", "Plate Solve & Annotate",
       "Identify the field and label what's in it.",
       "<h4>What it does</h4>"
       "<p>Works out exactly where your image is pointing by matching it against the sky, then "
       "overlays what's there — catalogue objects (nebulae, galaxies, clusters), named bright "
       "stars, a north compass, and a scale bar.</p>"
       "<h4>How to use it</h4>"
       "<p>Set up <b>ASTAP</b> in Settings first (it does the solving). Then toggle <b>Plate "
       "Solve</b> in the toolbar to show or hide the overlay — the first solve takes a moment, "
       "after which it's remembered. At <b>Export</b> you can burn the labels into a PNG.</p>"
       "<h4>Tips</h4>"
       "<p>The solution is cached per framing, so cropping, rotating, or flipping re-solves. "
       "Great for confirming what you captured and for making annotated shares.</p>"),

    _t("share", "Share",
       "Reframe and caption a copy for social, without touching your master.",
       "<h4>What it does</h4>"
       "<p>Makes a social-ready version of your image — cropped to a common aspect ratio, with an "
       "optional caption band carrying your handle — while leaving your edited master untouched.</p>"
       "<h4>How to use it</h4>"
       "<p>Click <b>Share</b>, pick an aspect ratio, toggle the caption if you want one, then "
       "<b>Export</b> a JPEG or <b>Copy to clipboard</b>. Set your <b>@handle</b> in Settings.</p>"
       "<h4>Tips</h4>"
       "<p>It's non-destructive: only the shared copy is reframed, so you can go straight back to "
       "finishing your full image afterwards.</p>"),

    _t("upscale", "Upscale Crop",
       "Enlarge a cropped region 2× for a closer view.",
       "<h4>What it does</h4>"
       "<p>Takes a cropped region and scales it up 2×, for a larger, tighter view of your "
       "subject.</p>"
       "<h4>How to use it</h4>"
       "<p>Click <b>Upscale Crop</b>, adjust the crop box, then <b>Upscale</b>. <b>Compare</b> "
       "shows before/after at the same size. <b>Export</b> the result, or <b>Open as copy</b> to "
       "keep editing it as a new project.</p>"
       "<h4>Tips</h4>"
       "<p>Upscaling can't invent detail that isn't there — it's best for reframing tight on a "
       "subject. A small text file recording the crop and scale is saved next to each export.</p>"),

    # ---- Projects & records ----
    _t("saved-projects", "Saved Projects",
       "Save and reopen your whole editing session.",
       "<h4>What it does</h4>"
       "<p>Saves everything about your session — the image, your complete edit history, and any "
       "plate solve — into a single <b>.nocturne</b> file, so you can close Nocturne and later "
       "pick up exactly where you left off, with undo/redo intact.</p>"
       "<h4>How to use it</h4>"
       "<p><b>Save Project</b> (or <b>Save Project As…</b>) writes the file; <b>Open Project</b> "
       "reloads one; <b>Recent Projects</b> lists the last few. <b>Close Project</b> returns to "
       "the welcome screen.</p>"
       "<h4>Tips</h4>"
       "<p>Unlike Export — which writes a flat, finished picture — a project keeps every step "
       "editable. Saving runs in the background, so the app stays responsive.</p>"),

    _t("provenance", "Provenance report",
       "Export a readable record of everything you did.",
       "<h4>What it does</h4>"
       "<p>Writes a plain, readable <b>Markdown</b> record of your whole edit — every step and its "
       "settings, plus the capture details and the app version — so you, or anyone, can see "
       "exactly how the image was made.</p>"
       "<h4>How to use it</h4>"
       "<p>Open the <b>Project</b> menu ▸ <b>Provenance report…</b>, then <b>Save…</b> the report "
       "or <b>Copy to clipboard</b>.</p>"
       "<h4>Tips</h4>"
       "<p>Handy for reproducibility, sharing your process with others, or just remembering what "
       "worked on a particular target.</p>"),

    # ---- Stacking & Ha/OIII ----
    _t("stacking", "Stacking",
       "Build a master image from a folder of subs.",
       "<h4>What it does</h4>"
       "<p>Turns a folder of individual sub-exposures into a single clean <b>master</b>: it "
       "grades and rejects poor frames, registers (aligns) the rest — handling the field rotation "
       "an alt-az mount like the Seestar introduces — and integrates them.</p>"
       "<h4>How to use it</h4>"
       "<p>Click <b>Stack</b> in the toolbar, choose the folder of subs, let it grade, then stack. "
       "The resulting master loads straight into the flow.</p>"
       "<h4>Tips</h4>"
       "<p>More subs mean a cleaner master with less noise. If you already have a stacked master "
       "(e.g. from the Seestar app), you can skip this and just Open FITS.</p>"),

    _t("haoiii", "Ha / OIII extraction",
       "Split a dualband master into separate Ha and OIII channels.",
       "<h4>What it does</h4>"
       "<p>Separates a dualband master into individual <b>Ha</b> and <b>OIII</b> masters, for "
       "people who want to build a palette by hand in another tool.</p>"
       "<h4>How to use it</h4>"
       "<p>Click <b>Ha/OIII</b> in the toolbar.</p>"
       "<h4>Tips</h4>"
       "<p>This is optional, for people who prefer to combine the Ha and OIII channels by hand "
       "in another tool.</p>"),

    # ---- Recipes & Batch ----
    _t("recipes", "Recipes & Batch",
       "Save a sequence of steps and apply it to other images or a whole folder.",
       "<h4>What it does</h4>"
       "<p>A <b>recipe</b> records the steps you applied so you can replay them on another image "
       "— or on a whole folder at once with <b>Batch</b>.</p>"
       "<h4>How to use it</h4>"
       "<p>Process an image, then <b>Save Recipe</b>. Later, use <b>Batch</b> to point a saved "
       "recipe at a folder and process everything in one go.</p>"
       "<h4>Tips</h4>"
       "<p>Great for a night of the same target shot in sessions. The Enhancements taps "
       "are captured in recipes and replayed in Batch too.</p>"),

    # ---- Troubleshooting ----
    _t("troubleshooting", "Troubleshooting & FAQ",
       "Quick answers to the things people hit most.",
       "<h4>The image went black on Levels</h4>"
       "<p>Levels needs a <b>stretched</b> image; on linear data it clips to black. Stretch first "
       "— newer builds auto-stretch for you when you enter a finishing step.</p>"
       "<h4>The sky went red after Background</h4>"
       "<p>Expected. Background removed the bluish light pollution, leaving the naturally red "
       "nebulosity more prominent; the <b>Color</b> step neutralises the residual cast.</p>"
       "<h4>My dualband image just looks red</h4>"
       "<p>That's raw narrowband data from the dualband filter — see the Dualband topic. You can "
       "split it into Ha and OIII channels with the <b>Ha/OIII</b> tool in the toolbar.</p>"
       "<h4>A tool isn't detected</h4>"
       "<p>Open <b>Settings</b>, set the path to the program, and press <b>Test</b>. GraXpert is "
       "required; RC-Astro is optional (steps fall back to free methods without it).</p>"
       "<h4>The log shows a change amount</h4>"
       "<p>The Δ% in the log estimates how much each step changed the visible image — a quick "
       "sanity check that a step did what you expected.</p>"),
)

TOPICS: dict[str, HelpTopic] = {t.id: t for t in _TOPIC_LIST}


SECTIONS: tuple[HelpSection, ...] = (
    HelpSection("Getting Started", ("getting-started",)),
    HelpSection("Concepts", ("linear-vs-stretched", "dualband", "step-order", "history", "readout")),
    HelpSection("The Steps", ("crop", "background", "color", "deconvolution", "stretch",
                              "recover_core", "levels", "curves", "saturation",
                              "green_fringe", "noise_sharpen", "local_contrast",
                              "star_reduction", "enhancements", "export")),
    HelpSection("Tools", ("tools", "auto-enhance", "plate-solve", "star_spikes", "narrowband")),
    HelpSection("Sharing & Projects", ("share", "upscale", "saved-projects", "provenance")),
    HelpSection("Stacking & Ha/OIII", ("stacking", "haoiii")),
    HelpSection("Recipes & Batch", ("recipes",)),
    HelpSection("Troubleshooting", ("troubleshooting",)),
)
