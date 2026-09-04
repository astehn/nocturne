# Per-channel HSL — one question to settle before building

**Written 2026-09-04, after Andreas asked for "a way for us to actually
manipulate Hue, Saturation and Luminance for each RGB channel".**

He was explicit that he wants this regardless of my argument against per-channel
*curves* earlier the same day. That argument was about repairing clipped data
and does not apply here — this is a finishing control, and it stands on its own
merits. **It is decided. Only the shape is open.**

---

## The wrinkle

**Hue is not defined for an RGB channel.** A channel is one number per pixel. It
can be scaled (that is saturation, or luminance) but it cannot be rotated — hue
is an angle around all three. So a literal "HSL per RGB channel" can only
deliver two of the three sliders he asked for.

Every HSL panel he will have used elsewhere — Lightroom, Photoshop, Capture One
— is organised by colour RANGE, not by channel: rows for red, orange, yellow,
green, aqua, blue, purple, magenta, each with its own H, S and L. That form does
give all three sliders, because a range has a hue to rotate.

So the two readings of the request are genuinely different features.

## Option A — by colour range (recommended)

Rows are colour ranges; each has Hue, Saturation, Luminance.

Astro-relevant ranges rather than Lightroom's eight, because six of those never
appear in this data:

| range | what it is in practice |
|---|---|
| Red | Ha, emission nebulosity |
| Gold / orange | the warm star population, galaxy cores |
| Green | almost always unwanted — see `remove_green_step` |
| Teal / cyan | OIII in a bicolour palette |
| Blue | reflection nebulosity, hot stars |
| Magenta | the classic OSC halo cast |

Each pixel gets a weight per range from its hue angle, with overlapping
falloffs so a shift is smooth and no boundary shows. Same idea as
`color_balance.tone_weight`, which already does this for shadows / midtones /
highlights — so the machinery has a precedent in the codebase to follow.

**Why this one:** it delivers all three sliders, it matches the tool he already
knows, and it is the only version that can do the thing he is most likely to
want — lift Ha reds without touching gold stars.

**Cost:** a new step, a hue-weight function, six rows of three sliders. The UI is
the larger half.

## Option B — by RGB channel (literal)

Three rows, R / G / B, each with Saturation and Luminance. No hue.

- *Luminance* scales the channel.
- *Saturation* pushes pixels dominated by that channel away from grey.

**Why you might still want it:** it is simpler, and it is closer to what he
literally said. It is also the form that would let him counteract the
channel-clipping asymmetry directly, since that asymmetry is per channel.

**Cost:** roughly half of Option A, and it cannot offer Hue.

---

## What to ask him

> Per RGB channel (three rows, no Hue — hue isn't defined for a single channel),
> or per colour range like Lightroom (six rows, all three sliders)?

One question, and the answer decides the whole build.

## Where it belongs, once that is settled

Nocturne's idiom is visible-but-ignorable, not an "Advanced mode" gate. A new
step in the pipeline list, after Saturation, fits that — the existing Saturation
step stays the simple path and this is the one you reach for when you want more.

Do NOT fold it into Colour Balance: that tool is per TONE (shadows / midtones /
highlights) and this is per HUE. Two different axes in one dialog would make
both harder to understand.

## One constraint that must not be broken

`autostretch.neutral_stretch` deliberately applies a LINKED gain, because an
unlinked per-channel gain amplified green about 1.9x on Bayer data — a 3.6%
green deficit became a 4.7% green excess on screen. This tool runs long after
the stretch and works on hue, so it does not conflict. But if anyone is tempted
to implement Option B's "luminance" as a per-channel gain applied earlier in the
pipeline, that is the same mistake wearing a different hat.
