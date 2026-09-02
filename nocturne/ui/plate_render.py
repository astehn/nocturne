"""Painting the Share title plate.

Replaces `share_render._burn_caption`, which drew ONE line with a bare QFont()
inside a full-width 59%-black bar. Three things are different: type is chosen
and bundled, the text is a composition rather than a `·`-joined strip, and the
default background is a gradient that fades out with no visible edge instead of
a rectangle that reads as UI chrome.

Text WRAPS. The old renderer elided, and the real caption for a 2037-frame
IC 1396A export lost its date and the photographer's handle to a '…' that
nothing warned about.

Every size here is a fraction of the composited height, and `margin` a fraction
of the SHORT edge, so a portrait and a landscape crop get the same visual inset.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient,
                           QPainter, QPen)

from .fonts import load_bundled_fonts

ANCHORS: list[tuple[str, str]] = [
    ("Top left", "top-left"), ("Top centre", "top-centre"), ("Top right", "top-right"),
    ("Middle left", "middle-left"), ("Centre", "middle-centre"), ("Middle right", "middle-right"),
    ("Bottom left", "bottom-left"), ("Bottom centre", "bottom-centre"), ("Bottom right", "bottom-right"),
]

TREATMENTS: list[tuple[str, str]] = [
    ("Gradient", "scrim"), ("Shadow only", "shadow"),
    ("Solid band", "band"), ("None", "none"), ("Matte", "matte"),
]

# Fractions of the composited height unless noted.
_GAP_GROUP = 0.016      # between the three slots
_PAD = 0.028            # breathing room the band and the matte add around the block
_RULE_THICK = 0.0014    # hairline between designation and common name
_RULE_MIN_W = 0.10      # fraction of the WIDTH, so a short designation still rules

# The scrim reaches 2.2x the block height so it always covers the block and a
# little more, and eases in steeply rather than ramping linearly — a linear ramp
# has a visible start line, which is the one thing a scrim exists to avoid.
#
# The strength is bounded by measurement, not taste. On the 0x101010 test frame
# the glyphs put back 0.95 mean units while a 0.72-alpha linear scrim over the
# same 800x1000 took away 1.13 — the scrim outweighed its own text. The budget
# is sum(alpha x area) < 59,000 px, and the ease spends it where it buys the
# most contrast: at the edge, under the credit line. See the report on this
# branch — this is a light scrim, and it wants judging on a real capture.
_SCRIM_SPAN = 2.2
_SCRIM_MIN = 0.22       # with all three slots empty there is still a gradient
_SCRIM_ALPHA = 0.62
_SCRIM_STOPS = ((0.0, 0.0), (0.5, 0.015), (0.7, 0.12), (0.85, 0.38),
                (0.95, 0.74), (1.0, 1.0))

_BAND_ALPHA = 0.59      # DEFAULT_BAND_OPACITY — what today's caption band uses

# A blurred black copy under the glyphs, composited four times. A blur conserves
# its own mass, and the crisp glyphs drawn on top reclaim whatever sits directly
# beneath them, so a single pass barely nets anything: measured on the 0xB0B0B0
# test frame, one 210-alpha pass at radius 0.16em moved the mean by -0.13 where
# four at 0.28em move it by -0.22. Compositing repeatedly is what lifts the thin
# outer halo — the part that is actually doing the separating — off the floor.
_SHADOW_BLUR = 0.28     # fraction of the largest type size
_SHADOW_PASSES = 4
_SHADOW_ALPHA = 235

_MATTE_BG = QColor(11, 11, 13)   # a dark mount; the plate colours are off-white

_LAST: dict = {}


def last_layout() -> dict:
    """Geometry from the most recent draw_plate — for tests and for the dialog's
    'this will not fit' warning. Not part of the rendering contract."""
    return dict(_LAST)


# --------------------------------------------------------------------------- blur

def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """One box pass of half-width r, edge-padded, via a running sum."""
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def blur(img: QImage, radius: int) -> QImage:
    """Approximate gaussian blur. Qt has no image blur at all, so: three
    separable box passes over a numpy view of the ARGB buffer.

    The numpy view dies with the QImage it borrows, hence the .copy().
    """
    r = int(max(0, radius))
    if r == 0:
        return QImage(img)
    src = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = src.width(), src.height()
    buf = np.frombuffer(src.constBits(), np.uint8).reshape(h, src.bytesPerLine())
    a = buf[:, :w * 4].reshape(h, w, 4).astype(np.float32)
    for _ in range(3):
        a = _box(a, r, 1)
        a = _box(a, r, 0)
    out8 = np.ascontiguousarray(np.clip(a + 0.5, 0, 255).astype(np.uint8))
    return QImage(out8.data, w, h, 4 * w, QImage.Format.Format_ARGB32).copy()


# ------------------------------------------------------------------------- layout

def _font(family: str, px: int, weight, tracking) -> QFont:
    f = QFont(family)
    f.setPixelSize(max(1, int(px)))
    # Qt 6 wants the enum, and there is no QFont.Weight.Regular — it is Normal.
    f.setWeight(QFont.Weight(int(weight)))
    if tracking:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0 + float(tracking))
    return f


def _wrap(text: str, fm: QFontMetricsF, width: float) -> tuple[list[str], bool]:
    """Break on spaces. A word wider than the line stays on its own line rather
    than being elided or chopped — losing characters in silence is the bug this
    module exists to fix. Each word is placed exactly once, so this cannot spin.
    """
    words = (text or "").split()
    if not words:
        return [], False
    lines, cur = [], words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if fm.horizontalAdvance(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    over = len(lines) > 1 or fm.horizontalAdvance(lines[0]) > width
    return lines, over


def _measure(text, style, w: int, h: int) -> dict:
    """Stack the slots that have content, and give every drawable its own row.

    An empty slot contributes nothing at all — not the line, not the gap after
    it — so the composition closes up rather than leaving a hole where the
    catalogue had nothing to say.
    """
    short = min(w, h)
    mx = max(0, round(short * style.margin))
    avail = max(1.0, float(w - 2 * mx))

    fonts, metrics = {}, {}
    for key, frac, weight, track in (
        ("title", style.size_title, style.weight_title, style.tracking_title),
        ("sub", style.size_sub, style.weight_sub, style.tracking_sub),
        # No weight_credit in the style: the credit follows the common name, so
        # a preset stays one decision rather than four.
        ("credit", style.size_credit, style.weight_sub, style.tracking_sub),
    ):
        fonts[key] = _font(style.family, max(6, round(h * float(frac))), weight, track)
        metrics[key] = QFontMetricsF(fonts[key])

    lines, over = {}, False
    for key, value in (("title", text.designation), ("sub", text.common),
                       ("credit", text.credit)):
        lines[key], wrapped = _wrap(value, metrics[key], avail)
        over = over or wrapped

    gap = h * _GAP_GROUP
    thick = max(1.0, h * _RULE_THICK)
    items: list[dict] = []
    y = 0.0
    previous = None
    for key in ("title", "sub", "credit"):
        if not lines[key]:
            continue
        if previous is not None:
            y += gap
            if previous == "title" and key == "sub" and style.rule:
                width = min(avail, max(w * _RULE_MIN_W,
                                       max(metrics["title"].horizontalAdvance(ln)
                                           for ln in lines["title"])))
                items.append({"kind": "rule", "y": y, "w": width, "h": thick})
                y += thick + gap
        fm = metrics[key]
        for line in lines[key]:
            items.append({"kind": "text", "y": y, "text": line, "font": fonts[key],
                          "ascent": fm.ascent(), "h": fm.height(),
                          "w": fm.horizontalAdvance(line)})
            y += fm.height()
        previous = key

    block_h = y
    block_w = max((it["w"] for it in items), default=0.0)
    return {"items": items, "block_w": block_w, "block_h": block_h,
            "margin": mx, "avail": avail, "overflow": over,
            "sub_lines": lines["sub"], "px_max": max(f.pixelSize() for f in fonts.values())}


def _place(anchor: str, block_w: float, block_h: float, mx: int,
           w: int, top: float, height: float) -> tuple[float, float]:
    """Nine anchors, resolved independently in each axis so the grid cannot
    collapse to three."""
    vertical, _, horizontal = str(anchor or "bottom-centre").partition("-")
    if horizontal == "left":
        left = float(mx)
    elif horizontal == "right":
        left = w - mx - block_w
    else:
        left = (w - block_w) / 2.0
    if vertical == "top":
        y = top + mx
    elif vertical == "middle":
        y = top + (height - block_h) / 2.0
    else:
        y = top + height - mx - block_h
    return left, y


# ------------------------------------------------------------------------ painting

def _draw_items(p: QPainter, lay: dict, left: float, top: float,
                anchor: str, colour: QColor) -> None:
    """Every row shares the block's box, so ragged lines align with each other
    rather than each finding its own edge."""
    _, _, horizontal = str(anchor or "bottom-centre").partition("-")
    for it in lay["items"]:
        if horizontal == "left":
            x = left
        elif horizontal == "right":
            x = left + lay["block_w"] - it["w"]
        else:
            x = left + (lay["block_w"] - it["w"]) / 2.0
        if it["kind"] == "rule":
            p.fillRect(QRectF(x, top + it["y"], it["w"], it["h"]), colour)
        else:
            p.setPen(QPen(colour))
            p.setFont(it["font"])
            p.drawText(QPointF(x, top + it["y"] + it["ascent"]), it["text"])


def _scrim(p: QPainter, w: int, h: int, block_h: float, anchor: str) -> None:
    span = max(_SCRIM_MIN, _SCRIM_SPAN * block_h / max(1, h))
    span = min(1.0, span)
    from_top = str(anchor or "").startswith("top")
    y0 = 0.0 if from_top else h * (1.0 - span)
    y1 = h * span if from_top else float(h)
    grad = QLinearGradient(0.0, y1 if from_top else y0, 0.0, y0 if from_top else y1)
    for stop, weight in _SCRIM_STOPS:
        grad.setColorAt(stop, QColor(0, 0, 0, round(255 * _SCRIM_ALPHA * weight)))
    p.fillRect(0, round(min(y0, y1)), w, round(abs(y1 - y0)), grad)


def _shadow(p: QPainter, w: int, h: int, lay: dict, left: float, top: float,
            anchor: str) -> None:
    layer = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(0)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.RenderHint.Antialiasing)
    lp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    _draw_items(lp, lay, left, top, anchor, QColor(0, 0, 0, _SHADOW_ALPHA))
    lp.end()
    soft = blur(layer, max(1, round(lay["px_max"] * _SHADOW_BLUR)))
    for _ in range(_SHADOW_PASSES):
        p.drawImage(0, 0, soft)


def draw_plate(image: QImage, text, style) -> QImage:
    """Paint the plate onto a COPY of `image` and return it.

    `style` is duck-typed rather than imported: the renderer and core/presets.py
    were built in either order, and core must not learn about Qt to be painted.
    """
    load_bundled_fonts()      # a family merely REQUESTED substitutes in silence
    src = image.convertToFormat(QImage.Format.Format_RGB888).copy()
    w, h = src.width(), src.height()
    lay = _measure(text, style, w, h)
    treatment = str(getattr(style, "treatment", "scrim") or "scrim")
    colour = QColor(str(getattr(style, "colour", "#F0E9E2")))
    mx, block_w, block_h = lay["margin"], lay["block_w"], lay["block_h"]
    pad = h * _PAD

    if treatment == "matte":
        # Extends the canvas instead of covering the picture — the one treatment
        # that can sit under burned-in annotations without cutting a label in half.
        extra = max(1, round(block_h + 2 * pad))
        out = QImage(w, h + extra, QImage.Format.Format_RGB888)
        out.fill(_MATTE_BG)
        p = QPainter(out)
        p.drawImage(0, 0, src)
        left, top = _place(style.anchor, block_w, block_h, mx, w, float(h), float(extra))
    else:
        out = src
        p = QPainter(out)
        left, top = _place(style.anchor, block_w, block_h, mx, w, 0.0, float(h))

    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    band_top = top - pad
    if treatment == "scrim":
        _scrim(p, w, h, block_h, style.anchor)
    elif treatment == "band":
        vertical = str(style.anchor or "bottom-centre").partition("-")[0]
        if vertical == "top":
            y0, y1 = 0.0, top + block_h + pad
        elif vertical == "bottom":
            y0, y1 = band_top, float(h)
        else:
            y0, y1 = band_top, top + block_h + pad
        p.fillRect(0, round(y0), w, max(1, round(y1 - y0)),
                   QColor(0, 0, 0, round(255 * _BAND_ALPHA)))
    elif treatment == "shadow":
        _shadow(p, out.width(), out.height(), lay, left, top, style.anchor)

    _draw_items(p, lay, left, top, style.anchor, colour)

    if getattr(style, "keyline", False):
        # A border, not a background: independent of the treatment, because the
        # Keyline preset wants it together with the shadow.
        pen = QPen(colour)
        pen.setWidth(max(1, round(h * 0.0015)))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(mx, mx, out.width() - 2 * mx - 1, out.height() - 2 * mx - 1)
    p.end()

    fits = block_h <= (h - 2 * mx) and block_w <= lay["avail"]
    _LAST.clear()
    _LAST.update({"sub_lines": list(lay["sub_lines"]), "block_height": block_h,
                  "block_width": block_w, "block_left": left, "block_top": top,
                  "band_top": round(band_top), "overflow": bool(lay["overflow"] or not fits),
                  "canvas": (out.width(), out.height())})
    return out
