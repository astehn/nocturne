"""Frame timeline and compositing for the Share tool's before/after wipe video.

Pure NumPy + Pillow: no Qt and no encoder here, so the look and the timing can be tested
without either. Every pixel constant below was tuned on a 1920-high frame (the approved spike)
and is scaled by ``height / 1920`` so other shapes keep the same proportions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULT_WORDMARK = "NOCTURNE"
WORDMARK_URL = "nocturneastro.com"
BEFORE_LABEL = "Straight from the telescope"
FPS = 30

_FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Jost[wght].ttf"
_REF_HEIGHT = 1920.0     # the height every pixel constant below was tuned at
_PUSH_IN = 1.08          # final zoom; sources are resampled to this much oversize
_LABEL_IN = 0.3          # seconds for the label to fade in
_LABEL_OUT = 0.4         # seconds for it to fade out once the wipe starts
_CARD_IN = 0.6           # seconds for the end card to fade in
_WORDMARK_SPACING = 0.35  # letter-spacing, in ems


@dataclass(frozen=True)
class Timeline:
    hook: float = 1.2
    before: float = 1.3
    wipe: float = 4.5
    end: float = 3.5
    fps: int = FPS

    @property
    def total(self) -> float:
        return self.hook + self.before + self.wipe + self.end

    @property
    def frame_count(self) -> int:
        return round(self.total * self.fps)


TIMELINE = Timeline()


@dataclass(frozen=True)
class FrameSpec:
    phase: str          # "hook" | "before" | "wipe" | "end"
    wipe: float         # 0..1, eased
    label_alpha: float
    end_alpha: float
    zoom: float


def _smoothstep(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


def frame_spec(t: float, tl: Timeline = TIMELINE) -> FrameSpec:
    """What is on screen at time ``t`` seconds."""
    t_before = tl.hook
    t_wipe = tl.hook + tl.before
    t_end = t_wipe + tl.wipe
    zoom = 1.0 + (_PUSH_IN - 1.0) * min(1.0, max(0.0, t / tl.total))
    if t < t_before:
        return FrameSpec("hook", 1.0, 0.0, 0.0, zoom)
    if t < t_wipe:
        return FrameSpec("before", 0.0, min(1.0, (t - t_before) / _LABEL_IN), 0.0, zoom)
    if t < t_end:
        fade = 1.0 - min(1.0, (t - t_wipe) / _LABEL_OUT)
        return FrameSpec("wipe", _smoothstep((t - t_wipe) / tl.wipe), fade, 0.0, zoom)
    return FrameSpec("end", 1.0, 0.0, min(1.0, (t - t_end) / _CARD_IN), zoom)


@dataclass(frozen=True)
class EndCard:
    title: str
    credit: str
    wordmark: str
    url: str


def end_card(title: str, credit: str, wordmark: str) -> EndCard:
    """The URL line only follows the default wordmark; custom text replaces both lines."""
    wordmark = wordmark.strip()
    url = WORDMARK_URL if wordmark.upper() == DEFAULT_WORDMARK else ""
    return EndCard(title.strip(), credit.strip(), wordmark, url)


def video_size(crop_w: int, crop_h: int, short_side: int = 1080) -> tuple[int, int]:
    """(w, h) with the short side exactly ``short_side`` and the long side an even number.

    Even because yuv420p cannot encode odd dimensions.
    """
    scale = short_side / min(crop_w, crop_h)

    def dim(n: int) -> int:
        if n == min(crop_w, crop_h):
            return short_side
        return max(2, 2 * round(n * scale / 2))

    return dim(crop_w), dim(crop_h)


@lru_cache(maxsize=None)
def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_FONT_PATH), max(6, size))
    font.set_variation_by_axes([weight])
    return font


def _spaced_widths(text: str, font: ImageFont.FreeTypeFont, spacing_em: float) -> list[float]:
    return ([font.getlength(c) for c in text] if spacing_em
            else [font.getlength(text)])


def _fit(text: str, size: int, weight: int, max_w: float,
         spacing_em: float = 0.0) -> ImageFont.FreeTypeFont:
    """The font at `size`, or the largest smaller one whose drawn width fits
    `max_w`. A custom wordmark or a long credit ran off a 1080-wide frame."""
    while True:
        font = _font(size, weight)
        widths = _spaced_widths(text, font, spacing_em)
        width = sum(widths) + font.size * spacing_em * (len(widths) - 1)
        if width <= max_w or size <= 6:
            return font
        size = max(6, min(size - 1, int(size * max_w / width)))


def _centered(draw: ImageDraw.ImageDraw, width: int, y: float, text: str,
              font: ImageFont.FreeTypeFont, fill: tuple[int, int, int, int]) -> None:
    draw.text(((width - draw.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _label_overlay(size: tuple[int, int], alpha: float) -> Image.Image:
    w, h = size
    s = h / _REF_HEIGHT
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = _font(round(40 * s), 400)
    tw = d.textlength(BEFORE_LABEL, font=font)
    x, y = (w - tw) / 2, 150 * s
    d.rounded_rectangle((x - 28 * s, y - 14 * s, x + tw + 28 * s, y + 58 * s), 34 * s,
                        fill=(0, 0, 0, int(140 * alpha)))
    d.text((x, y), BEFORE_LABEL, font=font, fill=(255, 255, 255, int(235 * alpha)))
    return ov


def _card_overlay(size: tuple[int, int], card: EndCard, alpha: float) -> Image.Image:
    w, h = size
    s = h / _REF_HEIGHT
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    grad_h = max(1, round(700 * s))
    shade = Image.new("RGBA", (w, grad_h), (0, 0, 0, 255))
    shade.putalpha(Image.linear_gradient("L").resize((w, grad_h))
                   .point(lambda v: int(v * 0.78 * alpha)))
    ov.alpha_composite(shade, (0, h - grad_h))
    d = ImageDraw.Draw(ov)
    a = int(255 * alpha)

    max_w = w - 80 * s

    if card.title:
        font = _fit(card.title, round(76 * s), 500, max_w)
        _centered(d, w, h - 470 * s, card.title, font, (255, 255, 255, a))
    if card.credit:
        _centered(d, w, h - 360 * s, card.credit, _fit(card.credit, round(36 * s), 350, max_w),
                  (220, 220, 220, a))
    if card.wordmark:
        font = _fit(card.wordmark, round(64 * s), 300, max_w, _WORDMARK_SPACING)
        gap = font.size * _WORDMARK_SPACING   # letter-spacing drawn per character, not as spaces
        widths = _spaced_widths(card.wordmark, font, _WORDMARK_SPACING)
        x = (w - (sum(widths) + gap * (len(widths) - 1))) / 2
        for c, cw in zip(card.wordmark, widths):
            d.text((x, h - 220 * s), c, font=font, fill=(255, 255, 255, a))
            x += cw + gap
    if card.url:
        _centered(d, w, h - 130 * s, card.url, _font(round(36 * s), 350), (200, 200, 200, int(a * 0.8)))
    return ov


def _wipe_line(frame: Image.Image, x: int) -> Image.Image:
    """Soft glow plus a thin bright core at column ``x``; only a narrow strip is touched."""
    w, h = frame.size
    s = h / _REF_HEIGHT
    half = max(1, round(10 * s))
    core = max(1, round(1 * s))
    blur = 8 * s
    pad = half + math.ceil(3 * blur) + 1
    strip = Image.new("RGBA", (2 * pad + 1, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    d.rectangle((pad - half, 0, pad + half, h), fill=(255, 255, 255, 60))
    strip = strip.filter(ImageFilter.GaussianBlur(blur))
    ImageDraw.Draw(strip).rectangle((pad - core, 0, pad + core, h), fill=(255, 255, 255, 230))
    left = x - pad
    lo, hi = max(0, left), min(w, left + strip.width)
    region = frame.crop((lo, 0, hi, h)).convert("RGBA")
    region.alpha_composite(strip.crop((lo - left, 0, hi - left, h)))
    out = frame.copy()
    out.paste(region.convert("RGB"), (lo, 0))
    return out


def render_frames(before: np.ndarray, after: np.ndarray, card: EndCard,
                  size: tuple[int, int], tl: Timeline = TIMELINE) -> Iterator[np.ndarray]:
    """Yield ``tl.frame_count`` uint8 RGB frames of shape (size[1], size[0], 3).

    ``before`` and ``after`` are identical-shape uint8 images already cropped to the framing.
    Both are resampled once to 1.08x the output, and each frame is a centred window of that,
    so the two always share the same geometry and the wipe cannot misalign.
    """
    if before.shape != after.shape:
        raise ValueError(f"before {before.shape} and after {after.shape} differ in shape")
    w, h = size
    over = (math.ceil(w * _PUSH_IN), math.ceil(h * _PUSH_IN))
    big_b = Image.fromarray(before).resize(over, Image.LANCZOS)
    big_a = Image.fromarray(after).resize(over, Image.LANCZOS)

    def view(img: Image.Image, zoom: float) -> Image.Image:
        ww, hh = over[0] / zoom, over[1] / zoom
        left, top = (over[0] - ww) / 2, (over[1] - hh) / 2
        return img.resize(size, Image.BILINEAR, box=(left, top, left + ww, top + hh))

    overlay_cache: dict[tuple, Image.Image] = {}

    def overlay(key: tuple, make) -> Image.Image:
        # alpha holds at 1.0 for most of a phase, so the last overlay is usually reusable
        if key not in overlay_cache:
            overlay_cache.clear()
            overlay_cache[key] = make()
        return overlay_cache[key]

    for i in range(tl.frame_count):
        spec = frame_spec(i / tl.fps, tl)
        if spec.phase == "hook":
            frame = view(big_a, spec.zoom)
        elif spec.phase == "before":
            frame = view(big_b, spec.zoom)
        elif spec.phase == "wipe":
            frame = view(big_b, spec.zoom)
            x = round(spec.wipe * w)
            if x > 0:
                frame.paste(view(big_a, spec.zoom).crop((0, 0, x, h)), (0, 0))
            if 0 < x < w:
                frame = _wipe_line(frame, x)
        else:
            frame = view(big_a, spec.zoom)
        if spec.label_alpha > 0:
            ov = overlay(("label", spec.label_alpha), lambda: _label_overlay(size, spec.label_alpha))
            frame = Image.alpha_composite(frame.convert("RGBA"), ov)
        if spec.end_alpha > 0:
            ov = overlay(("card", spec.end_alpha), lambda: _card_overlay(size, card, spec.end_alpha))
            frame = Image.alpha_composite(frame.convert("RGBA"), ov)
        yield np.array(frame.convert("RGB"))
