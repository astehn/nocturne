from __future__ import annotations

from .. import APP_NAME, APP_TAGLINE, __version__


def about_html() -> str:
    return (
        f"<h2>{APP_NAME}</h2>"
        f"<p>{APP_TAGLINE}</p>"
        f"<p>Version {__version__}</p>"
        "<p>Guided post-processing for one-shot-color smart-telescope stacks "
        "(tuned for the ZWO Seestar S30 Pro / Sony IMX585).</p>"
        "<p>Uses <b>GraXpert</b> (free, required for background extraction) and "
        "<b>RC-Astro</b> BlurX/NoiseX/StarX (optional). Set their paths in Settings.</p>"
        "<p>Not affiliated with ZWO.</p>"
    )


def help_html() -> str:
    return (
        f"<h2>{APP_NAME} — Quick help</h2>"
        "<p><b>Set up:</b> open <i>Settings</i> and point to your GraXpert binary "
        "(required) and, optionally, RC-Astro. Use <i>Test</i> to confirm they work.</p>"
        "<p><b>Workflow:</b> Open a stacked FITS, then step through:</p>"
        "<ol>"
        "<li><b>Import</b> — see the image + metadata.</li>"
        "<li><b>Destination</b> — finish in-app, or export a 16-bit TIFF for Photoshop/PixInsight.</li>"
        "<li><b>Crop</b> — drag the box; aspect / rotate / flip.</li>"
        "<li><b>Background</b> — remove light-pollution gradients (GraXpert).</li>"
        "<li><b>Color</b> — auto neutralize / white balance, optional green removal.</li>"
        "<li><b>Stretch</b> — reveal faint detail (aggressiveness slider).</li>"
        "<li><b>Levels</b> — fine black/white/gamma against the histogram.</li>"
        "<li><b>Saturation</b>, <b>Noise &amp; Sharpen</b>, <b>Star Reduction</b>.</li>"
        "<li><b>Export</b> — TIFF / PNG / FITS.</li>"
        "</ol>"
        "<p><b>Tips:</b> the histogram (top-right) and the log (bottom, with a Δ% change "
        "metric) confirm what each step did. Wheel = zoom, drag = pan. Undo/Redo and "
        "Before/After are in the toolbar.</p>"
    )
