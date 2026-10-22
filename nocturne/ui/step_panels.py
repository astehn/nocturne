from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QStyle,
    QLineEdit, QPushButton, QRadioButton, QSlider, QToolButton, QVBoxLayout,
    QWidget,
)

from .option_buttons import OptionButtons
from .shape_picker import SegmentRow, ShapePicker, section_label
from ..core.autostretch import _TARGET_BG
from ..steps.stretch_step import _DEFAULT as _STEP_DEFAULT
from ..steps.stretch_step import new_stretch_option
from ..core.color import ColorSettings
from ..core.stretch import _TARGET_MAX as _STRETCH_MAX, _TARGET_MIN as _STRETCH_MIN
from ..core.crop import GUIDE_KINDS, GUIDES
from ..core import nr_models
from .apply_button import ApplyButton
from .curve_editor import CurveEditor
from .reset_slider import ResetSlider
from .theme import CHANNEL_TINT, WARNING

# Black-point slider resolution. Ten times the other two levels sliders —
# see the levels panel for why. Defined in core because Auto's search resolves
# finer than one of its steps.
from ..core.levels import BLACK_STEPS  # noqa: E402,F401 - re-exported
from ..core.levels import new_levels_option  # noqa: E402

# One colour's black-point offset: +-0.100 in the Black point's 0.001 steps.
OFFSET_STEPS = 100


def _offset_text(d: float) -> str:
    """"0.000" at rest, signed with a true minus otherwise ("\u22120.015")."""
    if round(d * BLACK_STEPS) == 0:
        return "0.000"
    return f"{d:+.3f}".replace("-", "\u2212")

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "deconvolution": ["light", "medium", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
}
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"]

# Which of those write 16 bits per channel and may therefore carry a wide gamut.
# Named explicitly rather than sniffed from the label: this gate was
# `fmt.startswith("TIFF")`, which silently excluded the starless+stars pair
# because its label starts with "Starless" — two genuinely 16-bit TIFFs locked
# to sRGB while the export path was converting and tagging correctly all along.
SIXTEEN_BIT_FORMATS = frozenset({"TIFF (16-bit)", "Starless + Stars (two TIFFs)"})
# The Stretch slider's default: the background brightness a new image starts at.
#
# 30 is MEASURED PREFERENCE, not a derivation. Andreas picked from six-panel
# ladders of four of his own masters (2026-09-14), after the same comparison
# established that Nocturne's sky lands about twice as bright as AstroWizard's
# and that this — not denoising — was why its images looked cleaner to him:
#
#     M 16  0.10    M 33  0.10    IC 1396A  0.10    M 45  0.20-0.30
#
# M 45 decides it. At 0.10 "too much of the nebulosity is not visible", and that
# loss is unrecoverable: too bright and you see noise and drag it down, too dark
# and you never learn what you missed. So the default takes the most
# conservative of his four answers and fails in the recoverable direction.
# It also matches AUTO_STRETCH_AMOUNT, which was already 0.30 — before this the
# manual default was MORE aggressive than the automatic one.
#
# It replaced a "Target" dropdown (Auto/Nebula/Galaxy/Cluster) deleted
# 2026-09-13: four entries, three distinct values, two identical, "Auto" set the
# slider to the value it already had, and the binding was one-way so the box
# went on reading "Nebula" over a value that was not Nebula's.
#
# DERIVED, again and for good. It was briefly derived (2026-09-13/14), then
# pinned to 30 when the default moved — and that left the canvas DARKENING by
# 18% when you walked into Stretch, because the linear display autostretch still
# targeted 0.25. Andreas noticed it independently on 2026-09-15.
#
# Fixed at the source instead: autostretch.DEFAULT_TARGET_BG is now the single
# fact and both the preview and the slider default derive from it, so a third
# hand-written copy here would drift the same way a third time.
STRETCH_DEFAULT = round(_STEP_DEFAULT * 100)
# Inline "needs <tool>" note text per process stage that can be gated.
_GATE_NOTE = {
    "background": "Needs GraXpert — set its path in Settings.",
}


# What each step does for the picture, in at most two lines at the panel width
# (spec 2026-09-25-consistent-panels §6, Andreas' wording). What used to follow
# in the old, longer descriptions moved to the panel's notes (anything the user
# decides on) or to the step's "How this works" topic.
STEP_DESCRIPTIONS: dict[str, str] = {
    "load": "Your stack as loaded: its facts, and how the unstretched data is shown.",
    "crop": "Click the image to place the crop box, adjust it, then apply.",
    "background": "Remove uneven sky-glow — a gradient brighter toward one edge or corner.",
    "color": "Neutralise the sky background without touching your nebula's real colour.",
    "deconvolution": "Sharpen stars and fine detail by undoing some of the blur.",
    "stretch": "Brighten the faint detail so your target appears.",
    "remove_green": "Remove a green cast from the sky. Usually unnecessary — leave at 0 "
                    "if there is none.",
    "recover_core": "Pull blown-out bright cores back so they show detail. 0 = off.",
    "levels": "Fine-tune the black point, midtones and white point.",
    "curves": "Drag the curve to shape contrast. Double-click a point to remove it.",
    "saturation": "Mute or boost colour. Centre = no change; Nebula boost lifts only "
                  "the nebulosity.",
    "green_fringe": "Drain the green-to-cyan tint from stars; every other colour is "
                    "left alone.",
    "noise_sharpen": "Reduce noise in the stretched image while keeping fine detail.",
    "local_contrast": "Add depth to mid-sized structure. 0 = off.",
    "star_reduction": "Shrink and dim the stars so the nebula stands out. 0 = untouched.",
    "enhancements": "Final targeted tweaks — tap to add, Undo to peel back.",
    "export": "Save the finished picture.",
}


REVEAL_LABEL = "Show in Finder" if sys.platform == "darwin" else "Open folder"


def export_description(saved: str | None) -> str:
    """Export's description, plus where the last export went.

    The 2026-10-04 app audit (F-05): after a successful export the only trace
    was an Activity line, so a first-time user had to leave the app to find the
    file. In the pinned description box for the same reason as Stretch's colour
    balance line: Export still scrolls at 1280x800 (by 149-173 px since the
    2026-10-14 redesign), and a "done" line below the fold is the problem it
    exists to solve.

    `saved` is the already-elided, already-escaped name to show.
    """
    base = STEP_DESCRIPTIONS["export"]
    if not saved:
        return base
    # The app's ACCENT, no underline: "How this works"'s style. A raw link
    # draws in the palette's dark default blue, underlined, and is hard to
    # read on the panel (seen in the first render).
    from .theme import ACCENT
    link = f'<a href="reveal" style="color:{ACCENT}; text-decoration:none">{REVEAL_LABEL}</a>'
    return f'{base}<br>Saved <b>{saved}</b> · {link}'


def stretch_description(linked: bool) -> str:
    """Stretch's description, with which colour balance Apply commits.

    The linkage is half of what Apply commits, and until 2026-10-04 nothing on
    the panel showed it: Import sets a default, Visual stretch can pick the
    other one, and the only trace of the switch was a log line. A first-time
    user (the 2026-10-04 app audit) had to reconstruct it from the history.

    In the description box's spare second line, not a label of its own: the
    box is pinned above the scroll, and Stretch at 1280x800 had 16 px to spare
    in it — a one-line label there still scrolled the step (measured 5 px).
    """
    # The short half of the owner's wording (2026-10-11): this line has a
    # pixel budget, and the full sentence lives in the Import tooltips.
    name, what = (("Linked", "keeps star and nebula colours") if linked
                  else ("Unlinked", "evens the channels out"))
    return (f"{STEP_DESCRIPTIONS['stretch']}<br>"
            f"Colour balance: <b>{name}</b>, {what}.")


def _desc_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("stepDesc")
    label.setWordWrap(True)
    return label


class _DescBox(QLabel):
    """The description, ALWAYS two lines tall (Andreas, 2026-09-25), so the
    controls under it start at the same height on every step whatever the text.

    The height is recomputed whenever the style or font arrives, not fixed once
    at construction: the app stylesheet gives stepDesc its own 12 px font and
    6 px bottom padding, and a height taken from the construction-time font is
    wrong in the real window (the ApplyButton measured 45 px built, 47 px styled).
    """

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("stepDesc")
        self.setWordWrap(True)
        self.setIndent(0)   # the title's reason: the ink lines up with the controls
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._fit()

    def _fit(self) -> None:
        # Two lines at the CURRENT font, plus the box model: the stylesheet's
        # padding-bottom lands in contentsMargins() once polished. Checked
        # against a plain stepDesc label showing "x\nx" under the app
        # stylesheet: 2 x 15 + 6 = 36 px, the same as that label's sizeHint
        # (30 px unstyled). Not sizeHint() of this label itself: a
        # fixed-height label's hints are clamped to its own minimum, so a
        # re-fit could only ever grow (measured 42 px after a restyle).
        m = self.contentsMargins()
        two = (self.fontMetrics().lineSpacing() * 2 + m.top() + m.bottom()
               + 2 * self.margin())
        if self.minimumHeight() != two or self.maximumHeight() != two:
            self.setFixedHeight(two)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit()

    def event(self, event) -> bool:  # noqa: A003 (Qt override)
        result = super().event(event)
        if event.type() == QEvent.Type.Polish:
            self._fit()
        return result


def _wall_summary(fields: dict, handle: str) -> str:
    """One line naming what the wall will show beside the picture.

    Built from the SAME dict that gets posted, so the panel cannot describe one
    submission and send another — which is the fault this whole move exists to
    correct, one step to the left.

    Parts are collected and joined, so a file with almost no header renders a
    short line rather than a row of separators.
    """
    bits = []
    if (fields.get("target") or "").strip():
        bits.append(str(fields["target"]).strip())
    if fields.get("frames") and fields.get("sub_s"):
        sub = str(fields["sub_s"]).rstrip("0").rstrip(".")
        bits.append(f"{fields['frames']} \u00d7 {sub}s")
    if fields.get("instrument"):
        bits.append(str(fields["instrument"]))
    if fields.get("captured_on"):
        bits.append(str(fields["captured_on"]))
    if (handle or "").strip():
        bits.append(handle.strip())
    return "The gallery will show: " + " \u00b7 ".join(bits) if bits else ""


# Export's format tiles, in EXPORT_FORMATS order: (label, sub-label, icon).
_FORMAT_TILES = [
    ("TIFF", "16-bit", "format-tiff"),
    ("PNG", "8-bit", "format-png"),
    ("FITS", "data", "format-fits"),
    ("Layers", "starless + stars", "stack"),
]
_LAYERS_FORMAT = "Starless + Stars (two TIFFs)"
# Short labels for the colour-space buttons; the VALUES stay core.colour.SPACES.
_SPACE_LABELS = {"Display P3": "P3", "ProPhoto RGB": "ProPhoto"}
# C2 (Andreas, 2026-10-14, after testing B1): the extras sit under one heading
# that says what they are NOT, so nobody shares or saves a preset, thinks the
# picture is saved, and quits. Share waits for an export of this version.
_OPTIONAL_HEADING = "OPTIONAL — DOESN'T SAVE YOUR PICTURE"
_GALLERY_HINT_WAIT = "Available after you export."
_GALLERY_HINT = "Your exported picture in the public gallery."
_GALLERY_TIP_WAIT = ("Export the picture first: the gallery shows the picture you "
                     "exported, and this version has not been exported yet.")
_GALLERY_TIP = "Publish your exported picture in the Nocturne gallery at nocturneastro.com"
_GALLERY_URL = "https://nocturneastro.com/gallery.html"
_PRESET_HINT = "Saves the steps for similar pictures — not this picture."


def _rule() -> QFrame:
    """The Colour step's divider, so "optional" reads the same way twice."""
    rule = QFrame()
    rule.setFrameShape(QFrame.Shape.HLine)
    rule.setObjectName("panelRule")
    return rule


def _open_url(href: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(href))


class _GalleryDialog(QDialog):
    """The gallery block that sat at the foot of the Export panel, moved into a
    small window of its own (spec 2026-10-14). A container only: the panel
    fills it and owns every rule about consent, the handle and a spent send."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Share to the gallery")
        self.setModal(True)
        self.setMinimumWidth(420)
        # No title label: the window's own title bar says it (a window-modal
        # QDialog is a titled window on macOS too, not a sheet).
        lay = QVBoxLayout(self)
        self.body = QVBoxLayout()
        # "How this works ↗"'s style: ACCENT, no underline; ↗ = opens elsewhere.
        from .theme import ACCENT
        self.gallery_link = QLabel(
            f'<a href="{_GALLERY_URL}" style="color:{ACCENT}; text-decoration:none">'
            "See the gallery ↗</a>")
        self.gallery_link.setObjectName("helpHeader")
        self.gallery_link.setOpenExternalLinks(False)
        self.gallery_link.setToolTip(_GALLERY_URL)
        self.gallery_link.linkActivated.connect(_open_url)
        lay.addLayout(self.body)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch(1)
        # Live through a busy sweep: closing the window must always work.
        from .busy_gate import keep_live
        self.cancel_btn = keep_live(QPushButton("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        self.send_btn = QPushButton("Send to the gallery")
        self.send_btn.setAutoDefault(False)
        self.cancel_btn.setAutoDefault(False)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.send_btn)
        lay.addLayout(row)


# Noise Reduction's first engine entry: the settings' default engine. With no
# external tool installed it is the built-in denoise, and says so.
DEFAULT_ENGINE = "Default"
DEFAULT_BUILTIN = "Default (built-in)"


def _add_preset_controls(w, controls, on_presets, on_clear_preset) -> None:
    """Crop's "Presets…" and the chosen preset's chip, under Guides. Crop only:
    the panel builder is shared by every step, so this is opt-in by
    construction.

    A real button, as Stretch's "Visual stretch…" is (Andreas, 2026-10-13,
    his description in the spec). At 1280×800 it and the chip sit below the
    card's ~208 px fold; what the chip says is always on the Apply button."""
    btn = QPushButton("Presets…")
    btn.setToolTip("Choose a saved preset to apply after the crop")
    if on_presets is not None:
        btn.clicked.connect(lambda: on_presets())
    controls.addWidget(btn)

    chip = QWidget()
    row = QHBoxLayout(chip)
    row.setContentsMargins(0, 2, 0, 0)
    thumb = QLabel()
    thumb.setFixedSize(48, 32)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    name = QLabel("")
    name.setObjectName("stepDesc")
    clear = QToolButton()
    clear.setText("\u2715")
    clear.setToolTip("Don't apply a preset")
    clear.setAutoRaise(True)
    if on_clear_preset is not None:
        clear.clicked.connect(lambda: on_clear_preset())
    row.addWidget(thumb)
    row.addWidget(name, 1)
    row.addWidget(clear)
    chip.setVisible(False)
    controls.addWidget(chip)
    w.presets_btn = btn
    w.preset_chip = chip
    w.preset_chip_thumb = thumb
    w.preset_chip_name = name
    w.preset_chip_clear = clear


def build_panel(
    stage,
    *,
    on_open=None,
    on_apply=None,
    on_crop_apply=None,
    on_crop_change=None,
    on_presets=None,
    on_clear_preset=None,
    on_guides_change=None,
    on_rotate=None,
    on_flip_h=None,
    on_flip_v=None,
    on_export=None,
    wall_fields=None, wall_handle="", on_wall_submit=None, wall_state=None,
    gallery_ready: bool = False,
    on_remove_green=None,
    on_removegreen_change=None, on_tint_change=None, on_apply_tint=None,
    on_enhance=None,
    on_save_preset=None,
    on_stretch_change=None,
    on_visual_stretch=None,
    on_view_linked=None,
    view_linked=True,
    stretch_linked=True,
    on_opened_as_linear=None,
    opened_as_linear=None,
    on_levels_change=None,
    on_levels_auto=None,
    on_levels_colour_change=None,
    on_sat_change=None,
    on_sat_apply=None,
    on_fringe_apply=None,
    on_fringe_change=None,
    on_lc_change=None,
    on_show_model=None,
    on_option_change=None,
    on_curve_change=None,
    on_curve_preset=None, on_curve_expand=None,
    on_recover_change=None,
    on_sr_change=None,
    on_sr_apply=None,
    on_reset_step=None,
    apply_enabled: bool = True,
    split_enabled: bool = False,
    mono: bool = False,
    option_default: str | None = None,
    denoise_engine_choices: list | None = None,
    denoise_default_engine: str = "rcastro",
    denoise_engine_current: str | None = None,
    denoise_nr_engines: dict | None = None,
    denoise_disabled_choices: list | None = None,
) -> QWidget:
    w = QWidget()
    w.setObjectName("stepCard")
    w.panel_kind = stage.kind
    lay = QVBoxLayout(w)
    # The header — title row and the FIXED two-line description — is its own
    # widget, handed to SidePanel's header slot above the scroll (spec §3): a
    # tall step scrolls its controls, never its name or what it does. Built
    # here, not laid out in the card; inset like the card's own contents so
    # the title lines up with the controls under it.
    header = QWidget()
    header.setObjectName("stepHeader")
    header_lay = QVBoxLayout(header)
    # ONE inset for the header and the card's controls, set explicitly on
    # both. Copying the card layout's margins here read them before the
    # widget was polished (11 px) while the card later resolved its own
    # (9 px), so the title sat 2 px right of the controls under it.
    inset = w.style().pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin)
    lay.setContentsMargins(inset, 0, inset, inset)
    header_lay.setContentsMargins(inset, inset, inset, 0)
    header_lay.setSpacing(lay.spacing())
    w.header = header
    title_row = QHBoxLayout()
    title = QLabel(stage.label)
    title.setObjectName("stageTitle")
    # indent 0: with a stylesheet padding Qt gives a label a frame and then
    # indents its text by half an "x" (6 px at 20 px bold), so the title's ink
    # sat right of the controls' even at the same x.
    title.setIndent(0)
    title_row.addWidget(title)
    title_row.addStretch(1)
    # "How this works" sits on the title line so it never floats with the
    # panel's length (spec §4.2). MainWindow sets its text and wires it.
    w.help_link = QLabel("")
    w.help_link.setObjectName("helpHeader")
    w.help_link.setOpenExternalLinks(False)
    title_row.addWidget(w.help_link)
    header_lay.addLayout(title_row)
    # One template on every step (spec 2026-09-25-consistent-panels §3): the
    # header above, then in the card the controls (so they always start at the
    # same height), then notes. The main action and Reset step are built
    # below but NOT laid out here — MainWindow pins them in the side panel's
    # action slot, outside the scroll, in the same place on every step.
    w.desc_box = _DescBox(STEP_DESCRIPTIONS.get(stage.id, ""))
    header_lay.addWidget(w.desc_box)
    body = QWidget()
    body.setObjectName("panelBody")
    w.controls = QVBoxLayout(body)
    w.controls.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(body)
    notes_host = QWidget()
    notes_host.setObjectName("panelBody")
    w.notes = QVBoxLayout(notes_host)
    w.notes.setContentsMargins(0, 4, 0, 0)
    lay.addWidget(notes_host)
    w.primary_action = None
    w.apply_btn = None
    # What this panel's Apply hands its callback, read live — the SAME callable
    # the Apply connects to, so MainWindow's "do the controls still equal the
    # commit?" (_controls_match_commit) reads exactly what a press would send
    # and cannot drift from it. None where a panel commits nothing of its own.
    w.commit_option = None
    controls, notes = w.controls, w.notes

    if stage.kind == "import":
        # No "Open FITS…" button: the toolbar has one and the cold-start screen
        # has its own pair, so this copy was unreachable in every state where it
        # would have been the entry point.
        meta = _desc_label("Open a stacked Seestar FITS to begin.")
        meta.setObjectName("importMeta")   # brighter/larger than stepDesc — the FITS info must be readable
        meta.setTextFormat(Qt.TextFormat.RichText)
        controls.addWidget(meta)
        w.meta_label = meta

        # How the LINEAR data is drawn. A view, not a commitment: no pixel is
        # touched and no history entry is made. It exists because the linked
        # view leaves a uniform cast on data whose channels have very different
        # spreads (R/G MAD 2.67 on IC 1396A), and a uniform cast reads as
        # monochrome however saturated it actually is.
        heading = QLabel("How to show the unstretched data")
        heading.setObjectName("panelSectionLabel")
        controls.addWidget(heading)
        row = QHBoxLayout()
        linked_btn = QRadioButton("Linked")
        linked_btn.setToolTip("One curve for all colours: keeps the colours of stars and nebula")
        unlinked_btn = QRadioButton("Unlinked")
        unlinked_btn.setToolTip("Each colour stretched on its own: evens the channels out")
        group = QButtonGroup(w)
        group.addButton(linked_btn); group.addButton(unlinked_btn)
        (linked_btn if view_linked else unlinked_btn).setChecked(True)
        row.addWidget(linked_btn); row.addWidget(unlinked_btn); row.addStretch(1)
        controls.addLayout(row)
        if on_view_linked is not None:
            linked_btn.toggled.connect(lambda on: on_view_linked(bool(on)))
        w.view_linked = linked_btn
        w.view_unlinked = unlinked_btn
        w._view_group = group          # or the QButtonGroup is garbage collected

        # Only for a file that could plausibly be either. A FITS is linear by
        # the definition of the format we accept, and offering the choice there
        # would invite someone to get it wrong.
        if opened_as_linear is not None:
            head = QLabel("How this file was read")
            head.setObjectName("panelSectionLabel")
            controls.addWidget(head)
            row2 = QHBoxLayout()
            lin_btn = QRadioButton("Unstretched data")
            stretched_btn = QRadioButton("Already stretched")
            grp2 = QButtonGroup(w)
            grp2.addButton(lin_btn); grp2.addButton(stretched_btn)
            (lin_btn if opened_as_linear else stretched_btn).setChecked(True)
            row2.addWidget(lin_btn); row2.addWidget(stretched_btn); row2.addStretch(1)
            controls.addLayout(row2)
            if on_opened_as_linear is not None:
                lin_btn.toggled.connect(lambda on: on_opened_as_linear(bool(on)))
            w.opened_as_linear = lin_btn
            w._opened_group = grp2      # or the QButtonGroup is garbage collected
            # Stays with its control: it is the caption of this choice.
            controls.addWidget(_desc_label(
                "Nocturne measured the pixels to decide this. It is nearly always "
                "right, but a starless file or a very bright subject can fool it — "
                "if the picture looks wrong from here, switch it."))

        note = _desc_label(
            "Linked uses one curve for all colours and keeps the colours of stars "
            "and nebula; Unlinked stretches each colour on its own and evens the "
            "channels out, which usually shows more variety in star and dust "
            "colour. This only "
            "changes what you see — you choose again, and commit, at Stretch.")
        note.setTextFormat(Qt.TextFormat.RichText)
        notes.addWidget(note)

    elif stage.kind == "crop":
        # Shape buttons, not a dropdown: each draws the frame it makes, and
        # Orientation turns it (shape_picker.py; Andreas's variant B, 2026-10-10).
        shapes = ShapePicker(offer_free=True)
        if on_crop_change is not None:
            shapes.shapeChanged.connect(lambda name: on_crop_change(name))
        turns = SegmentRow(["\u21bb 90\u00b0", "\u21cb Flip H", "\u21f5 Flip V"],
                           checkable=False)
        rotate_btn, flip_h, flip_v = turns.buttons()
        rotate_btn.setToolTip("Rotate a quarter turn clockwise")
        flip_h.setToolTip("Mirror left to right")
        flip_v.setToolTip("Mirror top to bottom")
        if on_rotate is not None:
            rotate_btn.clicked.connect(lambda: on_rotate())
        if on_flip_h is not None:
            flip_h.clicked.connect(lambda: on_flip_h())
        if on_flip_v is not None:
            flip_v.clicked.connect(lambda: on_flip_v())
        apply_btn = ApplyButton("Apply Crop")
        apply_btn.setEnabled(False)  # off until the crop box is shown (cropBoxShown)
        if on_crop_apply is not None:
            apply_btn.clicked.connect(lambda: on_crop_apply())
        guides = SegmentRow(GUIDES)
        if on_guides_change is not None:
            guides.currentTextChanged.connect(
                lambda t: on_guides_change(GUIDE_KINDS[t]))
        # Compact on purpose: the whole card must fit the ~208 px a MacBook
        # leaves it (test_every_crop_control_is_in_view_without_scrolling).
        # "Apply instantly" lives in the heading, not a line of its own.
        controls.setSpacing(4)
        controls.addWidget(shapes)
        controls.addWidget(section_label("Rotate / flip \u00b7 apply instantly"))
        controls.addWidget(turns)
        controls.addWidget(section_label("Guides"))
        controls.addWidget(guides)
        # The crop's size readout: a status line, so it goes with the notes.
        size = _desc_label("—")
        notes.addWidget(size)
        w.shape_picker = shapes
        w.guides_box = guides
        w.rotate_btn = rotate_btn
        w.flip_h_btn = flip_h
        w.flip_v_btn = flip_v
        w.apply_btn = w.primary_action = apply_btn
        w.crop_size_label = size
        _add_preset_controls(w, controls, on_presets, on_clear_preset)

    elif stage.kind == "process":
        # Joined buttons, not a dropdown: every level visible, one click
        # (option_buttons.py). Same option strings as before.
        box = OptionButtons()
        box.addItems(_PROCESS_OPTIONS[stage.id])
        if option_default:
            box.setCurrentText(option_default)
        apply_btn = ApplyButton(f"Apply {stage.label}")
        note = _desc_label(_GATE_NOTE.get(stage.id, ""))
        note.setVisible(False)

        def _update_enabled(*_):
            if stage.id == "background":
                off = box.currentText() == "off"
                apply_btn.setEnabled(apply_enabled or off)
                note.setVisible(not apply_enabled and not off)
            elif stage.id in _GATE_NOTE:  # gated process stage (e.g. star_reduction)
                apply_btn.setEnabled(apply_enabled)
                note.setVisible(not apply_enabled)
            else:
                apply_btn.setEnabled(apply_enabled)

        box.currentTextChanged.connect(_update_enabled)
        if on_option_change is not None:
            # The pending label reads the level buttons, so it has to hear
            # them. Without this it only caught up on the next _refresh,
            # which for a compute stage means it lagged until the user did
            # something else entirely.
            box.currentTextChanged.connect(lambda _t: on_option_change())

        # Seeing the model is how you tell a real gradient from the fit eating
        # the faint outer parts of your object: the first is a smooth ramp, the
        # second carries the shape of the thing you photographed. In the
        # corrected image that failure only looks "a bit flat".
        show_model = None
        if stage.id == "background":
            show_model = QCheckBox("Show what was removed")
            show_model.setEnabled(False)          # nothing to show until it runs
            show_model.setToolTip(
                "Available once background extraction has run")
            if on_show_model is not None:
                show_model.toggled.connect(on_show_model)

        engine_box = None
        if stage.id == "noise_sharpen" and denoise_engine_choices:
            engine_box = QComboBox()
            # ["Default","NoiseXTerminator","GraXpert"], then any Nocturne NR models
            engine_box.addItems(denoise_engine_choices)
            for i in range(engine_box.count()):
                text = engine_box.itemText(i)
                nr_engine = (denoise_nr_engines or {}).get(text)
                if nr_engine is not None:
                    # The label may be elided; the tooltip carries the whole name.
                    engine_box.setItemData(
                        i, nr_models.engine_label(nr_engine[len(nr_models.PREFIX):]),
                        Qt.ItemDataRole.ToolTipRole)
                if text in (denoise_disabled_choices or ()):
                    item = engine_box.model().item(i)
                    if item is not None:
                        item.setEnabled(False)
            if denoise_engine_current in denoise_engine_choices:
                # A revisited step shows the engine it committed with, as the
                # strength box shows its level (MainWindow._denoise_engine_label).
                engine_box.setCurrentText(denoise_engine_current)
            if on_option_change is not None:
                # The engine is half of what Apply commits: Apply's state has
                # to hear it move, or an applied step stayed "✓ applied" and
                # off over a different engine (final review C1).
                engine_box.currentTextChanged.connect(lambda _t: on_option_change())
            controls.addWidget(QLabel("Engine"))
            controls.addWidget(engine_box)
            w.engine_box = engine_box
            # "Where you found it", like option_baseline: an engine switched
            # after an apply lit Apply, yet Next moved on and dropped it.
            w.engine_baseline = engine_box.currentText()

        def _noise_apply_option():
            level = box.currentText()
            if stage.id != "noise_sharpen":
                return level                              # background / deconvolution: bare level
            if engine_box is not None:
                sel = engine_box.currentText()
                nr = (denoise_nr_engines or {}).get(sel)
                # A model commits its stable id ("nr:v20.0"), never its label:
                # a renamed model must not break a saved project or recipe.
                engine = (nr if nr is not None
                          else denoise_default_engine if sel in (DEFAULT_ENGINE, DEFAULT_BUILTIN)
                          else "graxpert" if sel == "GraXpert" else "rcastro")
            else:
                engine = denoise_default_engine
            return {"engine": engine, "level": level}

        w.commit_option = _noise_apply_option
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(_noise_apply_option()))
        controls.addWidget(QLabel("Strength"))
        controls.addWidget(box)
        if show_model is not None:
            # A control, directly under the level buttons it checks the result of
            # (it sat below Apply while Apply was in the panel).
            controls.addWidget(show_model)
            w.show_model_check = show_model
            # How much was removed, while the view is on — on the step, not in
            # the log: the view changes nothing (Andreas, 2026-10-01).
            model_note = _desc_label("")
            model_note.setVisible(False)
            controls.addWidget(model_note)
            w.show_model_note = model_note
        if stage.id == "background":
            # Decision-relevant, so a note rather than "How this works": which
            # strength to pick, and how to read the check above.
            notes.addWidget(_desc_label(
                "Strong suits most images; use Light when your object fills the frame. "
                "After applying, "
                "tick Show what was removed: mid-grey is where nothing was taken, and "
                "a smooth ramp is sky-glow. If it carries the shape of your object, "
                "the fit took signal with it — undo and try Light."))
        notes.addWidget(note)
        _update_enabled()
        w.option_box = box
        # What the level buttons read on arrival. "Pending" means "moved since the
        # last commit or since I got here", and only the panel can answer that:
        # the committed history stores whatever the step recorded — a dict for
        # Noise Reduction, nothing at all for Background "off" — and a rebuilt
        # panel starts at the step default rather than at the committed value.
        w.option_baseline = box.currentText()
        w.apply_btn = w.primary_action = apply_btn
        w.disabled_note = note

    elif stage.kind == "enhance":
        _specs = [
            ("boost_red_btn", "Boost Red (Ha)", "Boost Red"),
            ("boost_cyan_btn", "Boost Cyan (OIII)", "Boost Cyan"),
            ("boost_blue_btn", "Boost Blue", "Boost Blue"),
            ("boost_gold_btn", "Boost Gold", "Boost Gold"),
            ("vibrance_btn", "Vibrance", "Vibrance"),
            ("darken_sky_btn", "Darken Sky", "Darken Sky"),
            ("lighten_sky_btn", "Lighten Sky", "Lighten Sky"),
            ("star_colour_btn", "Star Colour", "Star Colour"),
            ("dark_structure_btn", "Dark Structure", "Dark Structure"),
            ("soft_glow_btn", "Soft Glow", "Soft Glow"),
            ("sharpen_btn", "Sharpen Nebulosity", "Sharpen Nebulosity"),
        ]
        # No Save as Preset… here since 2026-10-14: on this step it read as an
        # Enhancements-only preset. It is on Export, and in the Project menu.
        for attr, label, op in _specs:
            btn = QPushButton(label)
            if on_enhance is not None:
                btn.clicked.connect(lambda _=False, o=op: on_enhance(o))
            controls.addWidget(btn)
            setattr(w, attr, btn)

    elif stage.kind == "auto":
        # Buttons, not a dropdown (his ask, 2026-10-14): the same idiom as Export's
        # format and colour space. SegmentRow reads and writes the same strings
        # the dropdown did, so everything downstream is unchanged.
        controls.addWidget(section_label("Method"))
        method_box = SegmentRow(["Sky balance", "Photometric (SPCC)"])
        controls.addWidget(method_box)
        w.method_box = method_box
        # What the dropdown read on arrival — same idea as option_baseline for
        # a compute stage's dropdown (see _has_pending): the method choice has
        # no preview slot of its own, so this is the only way to tell "moved
        # since the last commit" from "just arrived here".
        w.method_baseline = method_box.currentText()
        if on_option_change is not None:
            # The pending label (and the hero green) read this dropdown, so
            # they have to hear it move — same wiring the process-stage
            # dropdown below gets, for the same reason.
            method_box.currentTextChanged.connect(lambda _t: on_option_change())

        def _color_option():
            photometric = method_box.currentText().startswith("Photometric")
            return ColorSettings(method="photometric" if photometric else "sky")

        # The ONE visible action on Colour (spec §2.4). Built unconnected:
        # MainWindow connects it to _apply_colour_step, which commits method
        # and tint in _apply_sequence's order. The method's own commit is the
        # hidden apply_method_btn below.
        apply_btn = ApplyButton("Apply Color")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = _color_option
        # Colour cast, two bipolar sliders centred on 0 (double-click resets).
        #
        # Why these exist: Seestar data arrives with a magenta cast that is the
        # SENSOR's, not ours — measured on a raw sub at +0.041 on a (R+B)/2 - G
        # axis and passed through to the master essentially unchanged (+0.037).
        # Nocturne shipped De-green Sky for a cast its own stacks never have, and
        # nothing for the one they always do.
        #
        # Multiplicative gains on linear data, applied here rather than after the
        # stretch, for a measured reason: an ADDITIVE move at this point is erased
        # by neutral_stretch's background re-levelling (shift 0.00000), while a
        # gain survives. (Still so in stretch version 2, which levels on the sky
        # median: a uniform +0.002 green moved the result by at most 3e-5,
        # rounding, 2026-10-11.) It also leaves the background alone (also 0.00000), which
        # is what we want -- the magenta is in the nebulosity, and the background
        # is already faintly GREEN from chroma noise.
        # De-green Sky moved out to its own stage, which freed the room this
        # uses. Andreas, 2026-09-13: the two groups "feel a bit crammed together
        # now". A rule and a heading, not just padding — the point is that what
        # follows is OPTIONAL, and the step's own copy already said so in prose
        # nobody reads. This is the Colour half of the decided 2026-09-12
        # "separate and label the optional tools"; with De-green Sky gone, only
        # Tint remains, so it is one divider and one label rather than a layout.
        controls.addSpacing(14)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setObjectName("panelRule")
        controls.addWidget(rule)
        controls.addSpacing(10)
        optional = QLabel("Optional")
        optional.setObjectName("panelSectionLabel")
        controls.addWidget(optional)
        controls.addWidget(_desc_label(
            "Nudge the overall colour if it looks too magenta or too green. "
            "Double-click a slider to re-centre it."))
        tint_slider = ResetSlider(0, minimum=-100, maximum=100)
        tint_val = QLabel("0.00")
        tint_row = QHBoxLayout()
        tint_row.addWidget(QLabel("Green ←→ Magenta"))
        tint_row.addWidget(tint_val)
        def _emit_tint(*_):
            tint_val.setText(f"{tint_slider.value() / 100:+.2f}")
            temp_val.setText(f"{temp_slider.value() / 100:+.2f}")
            if on_tint_change is not None:
                on_tint_change(tint_slider.value() / 100.0, temp_slider.value() / 100.0)

        tint_slider.valueChanged.connect(_emit_tint)
        controls.addLayout(tint_row)
        controls.addWidget(tint_slider)

        temp_slider = ResetSlider(0, minimum=-100, maximum=100)
        temp_val = QLabel("0.00")
        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("Cool ←→ Warm"))
        temp_row.addWidget(temp_val)
        temp_slider.valueChanged.connect(_emit_tint)
        controls.addLayout(temp_row)
        controls.addWidget(temp_slider)
        w.tint_slider = tint_slider
        w.temp_slider = temp_slider
        # What the controls describe UNTOUCHED. main_window compares the live
        # value against this, so putting a slider back where you found it stops
        # the step reading as pending. Must stay in step with _emit_tint above —
        # test_neutral_option_matches_the_emit fires both and compares.
        w.neutral_option = (tint_slider.value() / 100.0, temp_slider.value() / 100.0)

        # Kept, wired, and never shown or laid out: _apply_sequence still
        # presses it to commit the tint, but the step shows ONE Apply. Parented
        # to the card so it dies with it.
        apply_tint_btn = QPushButton("Apply Tint", w)
        apply_tint_btn.setEnabled(apply_enabled)
        if on_apply_tint is not None:
            apply_tint_btn.clicked.connect(
                lambda: on_apply_tint(tint_slider.value() / 100.0,
                                      temp_slider.value() / 100.0))
        apply_tint_btn.setVisible(False)
        w.apply_tint_btn = apply_tint_btn
        # The method's own commit, hidden like apply_tint_btn. MainWindow
        # rewires the visible Apply to press these two in _apply_sequence's
        # order; had the sequence pressed the visible Apply for the method, it
        # would re-enter itself.
        apply_method_btn = QPushButton("Apply Color", w)
        apply_method_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_method_btn.clicked.connect(lambda: on_apply(_color_option()))
        apply_method_btn.setVisible(False)
        w.apply_method_btn = apply_method_btn
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "stretch":
        slider = ResetSlider(STRETCH_DEFAULT)
        stretch_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_stretch(*_):
            stretch_val.setText(f"{slider.value() / 100:.2f}")
            if on_stretch_change is not None:
                on_stretch_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_stretch)
        apply_btn = ApplyButton("Apply Stretch")
        apply_btn.setEnabled(apply_enabled)
        # A DICT, not a bare float: the stretch now carries its MECHANISM
        # as well as its amount, and both have to reach the commit.
        # new_stretch_option records the stretch VERSION too, so the step
        # replays as it was made (autostretch.STRETCH_VERSION).
        w.commit_option = lambda: new_stretch_option(slider.value() / 100.0,
                                                     bool(w.stretch_linked))
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(w.commit_option()))
        # Optional, and BELOW the slider: the slider keeps working untouched
        # for anyone who already knows the number they want. The picker is for
        # the case a number cannot answer — four of Andreas's own targets wanted
        # three different values, so no default can serve them all.
        #
        # ABOVE Apply, though — it was below it until 2026-09-17, which made
        # Stretch the only step in the app with a control under its commit
        # button. Reading top to bottom, that said "press this AFTER applying",
        # and the picker does the opposite: _apply_picked_stretch only moves the
        # slider, leaving the step for Apply to commit. Enforced for every panel
        # by test_nothing_sits_below_the_commit_button.
        visual_btn = QPushButton("Visual stretch…")
        visual_btn.setEnabled(apply_enabled)
        if on_visual_stretch is not None:
            visual_btn.clicked.connect(lambda: on_visual_stretch())
        agg_row = QHBoxLayout()
        agg_row.addWidget(QLabel("Aggressiveness (gentle → punchy)"))
        agg_row.addWidget(stretch_val)
        controls.addLayout(agg_row)
        controls.addWidget(slider)
        controls.addWidget(visual_btn)
        # Shown by MainWindow._sync_step_controls, which alone knows whether
        # Colour was photometric. The picker's own caveat is gone by the time
        # Apply is pressed, and he never saw it (Andreas, 2026-09-29). Laid out
        # at the card's BOTTOM edge, directly above Apply (his call 2026-09-30:
        # under Visual stretch it was out of the eye's path to the button).
        # Kept current by MainWindow._sync_step_controls, which runs after
        # every write to w.stretch_linked (build, picker, Import change).
        w.desc_box.setText(stretch_description(bool(stretch_linked)))
        w.linkage_note = w.desc_box
        spcc_note = _desc_label(
            "Unlinked will discard your photometric colour calibration (SPCC). "
            "To keep it, choose Linked in Visual stretch.")
        spcc_note.setStyleSheet(f"color: {WARNING};")
        spcc_note.setVisible(False)
        w.spcc_note = spcc_note
        w.fill_height = True     # SidePanel.set_panel: the card's height is ours
        w.visual_btn = visual_btn
        w.stretch_linked = bool(stretch_linked)
        w.linked_baseline = w.stretch_linked     # see engine_baseline
        w.stretch_slider = slider
        w.stretch_val = stretch_val
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "remove_green":
        # De-green Sky (SCNR) with a strength dial + live preview — a knob, not a
        # hammer. 1.00 == the classic full clamp.
        #
        # Default OFF, not 0.40. SCNR clamps green only where it exceeds the
        # red/blue average, and on data with no green cast that happens only in
        # the noise — so it shaves the upper half of green's fluctuations, skews
        # the distribution the stretch neutralises on, and makes the sky GREENER.
        # Measured on a real M 31 mosaic: the stretched sky went 0.983 -> 1.003 at
        # strength 0.40 and -> 1.027 at 1.00, where 1.000 is neutral. A default
        # that harms the common case is the wrong default.
        #
        # This step now sits AFTER Stretch (it used to be a button on Color,
        # five steps before the stretch that actually creates the cast), so
        # "reach for this only if a cast survives the stretch" is finally
        # advice the user can act on.
        rg_slider = ResetSlider(0)           # off until the user asks for it
        rg_val = QLabel("0.00")
        rg_row = QHBoxLayout()
        rg_row.addWidget(QLabel("Green removal"))
        rg_row.addWidget(rg_val)
        w.neutral_option = rg_slider.value() / 100.0
        if on_removegreen_change is not None:
            rg_slider.valueChanged.connect(
                lambda v: (rg_val.setText(f"{v / 100:.2f}"), on_removegreen_change(v / 100.0)))
        controls.addLayout(rg_row)
        controls.addWidget(rg_slider)
        # The measured harm above, said where the user decides — a note, not
        # "How this works".
        notes.addWidget(_desc_label(
            "On data with no cast this makes the sky greener, not less green."))
        apply_btn = ApplyButton("Apply De-green Sky")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = lambda: rg_slider.value() / 100.0
        if on_remove_green is not None:
            apply_btn.clicked.connect(lambda: on_remove_green(w.commit_option()))
        w.rg_slider = rg_slider
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "levels":
        auto_btn = QPushButton("Auto black point")
        # Checkable purely as an INDICATOR: it stays down while the values on the
        # sliders are still the ones Auto derived, and pops up the moment one is
        # nudged. That is the only sign of whether the recipe will store "derive
        # this per image" or three frozen numbers.
        auto_btn.setCheckable(True)
        auto_btn.setObjectName("levelsAuto")
        auto_btn.setToolTip(
            "Derive the black point from this image. Stays selected while the "
            "values are still the derived ones — a recipe then re-derives them "
            "for each image instead of reusing this one's.")
        if on_levels_auto is not None:
            auto_btn.clicked.connect(lambda: on_levels_auto())
        controls.addWidget(auto_btn)
        # Said only when Auto came in below its old rule (spec A): MainWindow
        # fills and shows it while Auto is selected AND stopped. Under the
        # button, because that is the choice it explains.
        auto_note = _desc_label("")
        auto_note.setVisible(False)
        controls.addWidget(auto_note)

        # 1000 steps, not 100. The black point is the ONLY value Auto Levels
        # sets now, so it carries the whole step; and its useful range is about
        # 0-0.15, so 0.01 steps gave roughly fifteen usable positions and
        # rounded most of the adaptation away before the user ever saw it.
        black = ResetSlider(0, maximum=BLACK_STEPS)
        gamma = ResetSlider(100, minimum=10, maximum=300)  # 1.00
        white = ResetSlider(100)
        black_val = QLabel("0.000")
        gamma_val = QLabel("1.00")
        white_val = QLabel("1.00")

        # One colour's black point, as an offset from the shared one (spec B).
        # Same 0.001 step as Black point; +-0.100 covers the measured need (a
        # crushed R or B on his projects sits 0.01-0.03 under the shared black).
        offset_sliders = [ResetSlider(0, minimum=-OFFSET_STEPS, maximum=OFFSET_STEPS)
                          for _ in range(3)]
        offset_vals = [QLabel(_offset_text(0.0)) for _ in range(3)]

        def _offsets():
            return tuple(s.value() / BLACK_STEPS for s in offset_sliders)

        # What Apply commits from the controls alone. Auto is MainWindow's: it
        # knows whether the black on the slider is still the derived one.
        # A black finer than the slider's 0.001 grid — Auto's continuous one,
        # or a committed value the panel was rebuilt from — as (slider position
        # it shows at, exact value). While the slider stays there, the exact
        # value is what is committed, so touching another control keeps the
        # picture rather than snapping the black to the grid.
        # Midtones and White point the same way: a hand-edited recipe or
        # preset can hold 1.234, and a colour nudge must not snap it to 1.23.
        w.exact_black = w.exact_gamma = w.exact_white = None

        def _held(slider, held, scale):
            if held is not None and held[0] == slider.value():
                return held[1]
            return slider.value() / scale

        w.commit_option = lambda: new_levels_option(
            _held(black, w.exact_black, BLACK_STEPS), _held(gamma, w.exact_gamma, 100.0),
            _held(white, w.exact_white, 100.0), _offsets())
        w.levels_offsets = _offsets

        def _labels():
            black_val.setText(f"{black.value() / BLACK_STEPS:.3f}")
            gamma_val.setText(f"{gamma.value() / 100:.2f}")
            white_val.setText(f"{white.value() / 100:.2f}")
            for s, v in zip(offset_sliders, offset_vals):
                v.setText(_offset_text(s.value() / BLACK_STEPS))

        def _emit(*_):
            _labels()
            if on_levels_change is not None:
                on_levels_change(w.commit_option())

        def _set_values(black_exact, gamma_v, white_v, offsets):
            """Show values WITHOUT emitting: a panel rebuilt from its commit
            is not an edit. The black shows rounded DOWN; all three are kept
            exact while their sliders stay where they were put."""
            import math
            pos = math.floor(round(float(black_exact) * BLACK_STEPS, 6))
            g_pos, w_pos = round(float(gamma_v) * 100), round(float(white_v) * 100)
            values = [(black, pos), (gamma, g_pos), (white, w_pos)]
            values += [(s, round(float(d) * BLACK_STEPS))
                       for s, d in zip(offset_sliders, offsets)]
            for s, v in values:
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
            w.exact_black = (pos, float(black_exact))
            w.exact_gamma = (g_pos, float(gamma_v))
            w.exact_white = (w_pos, float(white_v))
            _labels()
        w.set_levels_values = _set_values

        def _emit_colour(*_):
            _labels()
            # Its own hook: a colour move keeps Auto selected (spec B), where
            # any of the three above makes the value a choice.
            if on_levels_colour_change is not None:
                on_levels_colour_change(w.commit_option())

        w.neutral_option = w.commit_option()
        black.valueChanged.connect(_emit)
        gamma.valueChanged.connect(_emit)
        white.valueChanged.connect(_emit)
        for s in offset_sliders:
            s.valueChanged.connect(_emit_colour)

        apply_btn = ApplyButton("Apply Levels")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(w.commit_option()))

        black_row = QHBoxLayout()
        black_row.addWidget(QLabel("Black point"))
        black_row.addWidget(black_val)
        controls.addLayout(black_row)
        controls.addWidget(black)

        gamma_row = QHBoxLayout()
        gamma_row.addWidget(QLabel("Midtones"))
        gamma_row.addWidget(gamma_val)
        controls.addLayout(gamma_row)
        controls.addWidget(gamma)

        white_row = QHBoxLayout()
        white_row.addWidget(QLabel("White point"))
        white_row.addWidget(white_val)
        controls.addLayout(white_row)
        controls.addWidget(white)

        # Always visible on a colour picture (spec B: a crushed colour must be
        # fixable where the amber is seen), one box so a mono picture hides it
        # whole. The rule + section label are the Colour step's "optional".
        colour_box = QWidget()
        colour_box.setObjectName("panelBody")      # the card's ground, not a box
        colour_lay = QVBoxLayout(colour_box)
        colour_lay.setContentsMargins(0, 0, 0, 0)
        colour_lay.addSpacing(14)
        colour_lay.addWidget(_rule())
        colour_lay.addSpacing(10)
        section = QLabel("OPTIONAL — ONE COLOUR'S DARKEST LEVEL")
        section.setObjectName("panelSectionLabel")
        colour_lay.addWidget(section)
        colour_lay.addWidget(_desc_label(
            "For a colour that is crushed (amber above) or too dark. "
            "Most pictures leave these at 0."))
        for name, letter, s, v in zip(("Red", "Green", "Blue"), "RGB",
                                      offset_sliders, offset_vals):
            row = QHBoxLayout()
            label = QLabel(name)
            # The read-out's own channel colours, so "amber B above" and the
            # slider that fixes it are visibly the same colour.
            label.setStyleSheet(f"color: {CHANNEL_TINT[letter]};")
            row.addWidget(label)
            row.addWidget(v)
            colour_lay.addLayout(row)
            colour_lay.addWidget(s)
        ends = QHBoxLayout()
        for text, align in (("\u2190 lift", Qt.AlignmentFlag.AlignLeft),
                            ("darken \u2192", Qt.AlignmentFlag.AlignRight)):
            end = QLabel(text)
            end.setObjectName("sliderEnd")
            end.setAlignment(align)
            ends.addWidget(end)
        colour_lay.addLayout(ends)
        controls.addWidget(colour_box)

        w.auto_btn = auto_btn
        w.auto_note = auto_note
        w.black_slider = black
        w.gamma_slider = gamma
        w.white_slider = white
        w.black_val = black_val
        w.gamma_val = gamma_val
        w.white_val = white_val
        w.red_slider, w.green_slider, w.blue_slider = offset_sliders
        w.red_val, w.green_val, w.blue_val = offset_vals
        w.levels_colour_box = colour_box
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "curves":
        editor = CurveEditor()
        # 240 px minimum, and it takes any spare height (stretch 1 below) — it
        # draws SQUARE, so extra height also buys width up to the pane. It was
        # 320 (2026-08-20), which made Curves scroll even in a 1920x1080 window
        # (step room 350 px, measured 2026-09-26). Where even 240 does not fit,
        # MainWindow hides it and the step offers the large editor instead.
        editor.setMinimumHeight(240)
        # Curves' neutral is the identity curve the editor is built with.
        w.neutral_option = list(editor.points())
        if on_curve_change is not None:
            editor.curveChanged.connect(lambda pts: on_curve_change(pts))
        controls.addWidget(editor, 1)

        preset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        add_btn = QPushButton("Add contrast")
        if on_curve_preset is not None:
            reset_btn.clicked.connect(lambda: on_curve_preset("reset"))
            add_btn.clicked.connect(lambda: on_curve_preset("add_contrast"))
        preset_row.addWidget(reset_btn)
        preset_row.addWidget(add_btn)
        controls.addLayout(preset_row)

        # The pane cannot get wider, so precision work goes to a dialog — the
        # same answer Colour Balance and Narrowband already use. The inline
        # editor stays the default: a quick tweak should not need a window.
        expand_btn = QPushButton("Open large editor…")
        if on_curve_expand is not None:
            expand_btn.clicked.connect(lambda: on_curve_expand())
        controls.addWidget(expand_btn)
        w.expand_btn = expand_btn

        apply_btn = ApplyButton("Apply Curves")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = editor.points
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(w.commit_option()))

        w.curve_editor = editor
        w.reset_btn = reset_btn
        w.add_contrast_btn = add_btn
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "saturation":
        slider = ResetSlider(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
        sat_val = QLabel(f"{slider.value() / 100:.2f}")
        neb = ResetSlider(0)
        neb_val = QLabel(f"{neb.value() / 100:.2f}")
        neb_status = _desc_label("")   # main_window sets "Separating stars…" / gate text

        def _emit_sat(*_):
            sat_val.setText(f"{slider.value() / 100:.2f}")
            neb_val.setText(f"{neb.value() / 100:.2f}")
            if on_sat_change is not None:
                on_sat_change(slider.value() / 100.0, neb.value() / 100.0)

        w.neutral_option = (slider.value() / 100.0, neb.value() / 100.0)
        slider.valueChanged.connect(_emit_sat)
        neb.valueChanged.connect(_emit_sat)
        apply_btn = ApplyButton("Apply Saturation")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = lambda: (slider.value() / 100.0, neb.value() / 100.0)
        if on_sat_apply is not None:
            apply_btn.clicked.connect(lambda: on_sat_apply(*w.commit_option()))
        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Saturation (mute ← native → boost)"))
        sat_row.addWidget(sat_val)
        controls.addLayout(sat_row)
        controls.addWidget(slider)
        neb_row = QHBoxLayout()
        neb_row.addWidget(QLabel("Nebula boost (off → strong)"))
        neb_row.addWidget(neb_val)
        controls.addLayout(neb_row)
        controls.addWidget(neb)
        notes.addWidget(neb_status)
        w.sat_slider = slider
        w.sat_val = sat_val
        w.neb_slider = neb
        w.neb_val = neb_val
        w.neb_status = neb_status
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "green_fringe":
        # AN AMOUNT SLIDER, added 2026-09-19 — and it reverses a decision made
        # here on 2026-09-13, so the reason matters.
        #
        # This briefly had a CHECKBOX, and Andreas was right to reject it: *"Why
        # do the user have to click a checkbox and then press apply, since its
        # only a one step process... there is nothing to choose."* A control
        # with one meaningful position is a step performed for the app's
        # benefit. That argument was about WHETHER to de-green, and it still
        # stands — the hue is not a choice, because no star is green or cyan.
        #
        # HOW FAR is a choice, and three things made it one. He set Photoshop's
        # Hue/Saturation to -75 rather than -100 and preferred the result, so
        # full neutralisation is not always wanted. The band now reaches cyan,
        # taking the step from ~3% of pixels to ~20%, so its swing is far
        # larger. And it interacts with De-green Sky — maxing that first leaves
        # this one less to do — which makes the right amount depend on the image
        # and on what ran before it.
        #
        # The slider IS Photoshop's Saturation: both scale how far a selected
        # pixel travels toward neutral, so 75 here is exactly Saturation -75.
        #
        # With RC-Astro (StarX) the split gives a clean stars layer, so
        # de-greening it and screen-recombining really does touch only the
        # stars. Without it there is no clean stars layer to de-green in
        # isolation (see remove_green_fringe_masked's docstring), so the free
        # path de-greens the WHOLE image instead, blended by a dilated,
        # feathered star mask. Measured on a real NGC 7000 master at
        # FRINGE_MASK_SCALE 2.5: the mask touches 68.1% of the frame (13.2% at
        # >=50% weight, 2.5% at full strength) — enough that background green
        # noise visibly shifts too. The note below has to say so.
        status = _desc_label("")   # main_window sets the split/mask label or gate text
        notes.addWidget(status)
        notes.addWidget(_desc_label(
            "With a star separator configured only the stars layer is touched "
            "and nebula colour cannot move; without one, the free path works on "
            "the whole image inside a feathered mask centred on stars, so "
            "background colour can shift too."))
        slider = ResetSlider(100)
        fringe_val = QLabel(f"{slider.value()}")

        def _emit_fringe(*_):
            fringe_val.setText(f"{slider.value()}")
            if on_fringe_change is not None:
                on_fringe_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_fringe)
        apply_btn = ApplyButton("Apply De-green Stars")
        w.commit_option = lambda: slider.value() / 100.0
        if on_fringe_apply is not None:
            apply_btn.clicked.connect(lambda: on_fringe_apply(w.commit_option()))
        # Start disabled — main_window enables once the (slow) split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Amount (none → fully neutral)"))
        fringe_row.addWidget(fringe_val)
        controls.addLayout(fringe_row)
        controls.addWidget(slider)
        w.fringe_status = status
        w.fringe_slider = slider
        w.fringe_val = fringe_val
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "recover_core":
        slider = ResetSlider(0)
        recover_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_recover(*_):
            recover_val.setText(f"{slider.value() / 100:.2f}")
            if on_recover_change is not None:
                on_recover_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_recover)
        apply_btn = ApplyButton("Apply Recover Core")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = lambda: slider.value() / 100.0
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(w.commit_option()))
        rec_row = QHBoxLayout()
        rec_row.addWidget(QLabel("Strength (off → full)"))
        rec_row.addWidget(recover_val)
        controls.addLayout(rec_row)
        controls.addWidget(slider)
        w.recover_slider = slider
        w.recover_val = recover_val
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "local_contrast":
        slider = ResetSlider(0)
        lc_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_lc(*_):
            lc_val.setText(f"{slider.value() / 100:.2f}")
            if on_lc_change is not None:
                on_lc_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_lc)
        apply_btn = ApplyButton("Apply Local Contrast")
        apply_btn.setEnabled(apply_enabled)
        w.commit_option = lambda: slider.value() / 100.0
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(w.commit_option()))
        lc_row = QHBoxLayout()
        lc_row.addWidget(QLabel("Strength (off → full)"))
        lc_row.addWidget(lc_val)
        controls.addLayout(lc_row)
        controls.addWidget(slider)
        w.lc_slider = slider
        w.lc_val = lc_val
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "star_reduction":
        status = _desc_label("")   # main_window sets "Separating stars…" / gate text
        notes.addWidget(status)
        slider = ResetSlider(0)
        sr_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_sr(*_):
            sr_val.setText(f"{slider.value() / 100:.2f}")
            if on_sr_change is not None:
                on_sr_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_sr)
        apply_btn = ApplyButton("Apply Star Reduction")
        w.commit_option = lambda: slider.value() / 100.0
        if on_sr_apply is not None:
            apply_btn.clicked.connect(lambda: on_sr_apply(w.commit_option()))
        # Start disabled — main_window enables once the (slow) StarX split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        sr_row = QHBoxLayout()
        sr_row.addWidget(QLabel("Reduction (none → strong)"))
        sr_row.addWidget(sr_val)
        controls.addLayout(sr_row)
        controls.addWidget(slider)
        w.sr_status = status
        w.sr_slider = slider
        w.sr_val = sr_val
        w.apply_btn = w.primary_action = apply_btn

    elif stage.kind == "export":
        from ..core.colour import EIGHT_BIT_SPACES, SPACES
        from .format_tiles import TileRow
        from .icons import load_icon
        # Buttons, not dropdowns, as on every other step (Andreas, 2026-10-14,
        # mock-up "B1"). The tiles and segments read and write today's strings,
        # so on_export, recipes and Batch see exactly what they always did.
        # Layers a third wider: "starless + stars" measured 76 px at 10 px
        # (Cocoa; 79 offscreen) in an 81 px tile at 1280x800 — an even split
        # cut it. 3:3:3:4 gives it ~99 px and the others ~75.
        box = TileRow([(v, label, sub, icon) for v, (label, sub, icon) in zip(
            EXPORT_FORMATS, _FORMAT_TILES)], weights=[3, 3, 3, 4])

        # Colour space. Every export is TAGGED with whichever is chosen, so a
        # reader never has to guess — an untagged file is why a correct M 16
        # export rendered dark in Photoshop.
        space_box = SegmentRow([_SPACE_LABELS.get(s, s) for s in SPACES], values=list(SPACES))
        space_note = _desc_label(
            "Tagged, so other programs show it as you see it here. "
            + ("A mono picture exports in sRGB." if mono
               else "Wider spaces for 16-bit TIFF only."))

        def _restrict_space(fmt: str) -> None:
            """Wide gamut only for 16-bit TIFF.

            Adobe RGB spreads the same 256 levels over a larger volume, so an
            8-bit file in one bands visibly — and astro images are mostly smooth
            gradients, the worst case. Enforced by DISABLING the entries and
            pulling the selection back, not by hiding them: a user who picks
            Adobe RGB and then PNG must not quietly get a banded file.
            """
            # Nor for MONO: a grey file cannot carry an RGB working space,
            # and the conversion has no colour to move.
            wide_ok = fmt in SIXTEEN_BIT_FORMATS and not mono
            for i, b in enumerate(space_box.buttons()):
                b.setEnabled(wide_ok or space_box.itemText(i) in EIGHT_BIT_SPACES)
            if not wide_ok and space_box.currentText() not in EIGHT_BIT_SPACES:
                space_box.setCurrentText(EIGHT_BIT_SPACES[0])

        # Shown only when the picture is plate-solved: MainWindow decides.
        w.burn_annotations = QCheckBox("Burn annotations (PNG)")
        w.burn_annotations.setVisible(False)

        # Shown only when it says something: Layers chosen, no StarNet2/StarX.
        w.split_note = None
        if not split_enabled:
            w.split_note = _desc_label(
                "Starless + stars uses Nocturne's built-in star split.")
            w.split_note.setVisible(False)

        def _format_changed(fmt: str) -> None:
            _restrict_space(fmt)
            if w.split_note is not None:
                w.split_note.setVisible(fmt == _LAYERS_FORMAT)

        box.currentTextChanged.connect(_format_changed)
        _format_changed(box.currentText())

        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export is not None:
            export_btn.clicked.connect(
                lambda: on_export(box.currentText(), space_box.currentText()))
        controls.addWidget(section_label("Format"))
        controls.addWidget(box)
        controls.addSpacing(4)
        controls.addWidget(section_label("Colour space"))
        controls.addWidget(space_box)
        controls.addWidget(space_note)
        controls.addWidget(w.burn_annotations)
        if w.split_note is not None:
            controls.addWidget(w.split_note)
        w.format_box = box
        w.space_box = space_box
        w.space_note = space_note
        # The step's main action: pinned by MainWindow like every Apply.
        w.export_btn = w.primary_action = export_btn

        # --- and, optionally, the gallery ---------------------------------
        #
        # HERE rather than in the Share dialog (spec 2.4). Share reframes for a
        # destination and composes without the plate, so what it sent differed
        # from what it showed — in the one dialog built around those being the
        # same thing. At the end of the pipeline nothing is transformed on the
        # way out, and this is also the moment someone has just finished
        # something they are pleased with.
        #
        # Behind its own button since 2026-10-14: the block made the panel
        # "busy compared to other screens". The dialog is the panel's child,
        # so the busy gate sweeps it with the rest — and it dies with the
        # panel, which is rebuilt often (a plate solve landing, among a dozen
        # callers). So a send's state is NOT kept here: MainWindow holds it
        # per picture and hands it back as `wall_state` to every rebuild.
        #
        # The panel RECEIVES the facts and a callback. It never touches the
        # image: composing here would be the second compose path all over again,
        # one step to the left.
        w.wall_consent = None
        w.wall_btn = None
        w.wall_note = None
        w.wall_target = None
        w.gallery_btn = None
        w.gallery_hint = None
        w.gallery_dialog = None
        controls.addWidget(_rule(), 0)
        w.optional_heading = section_label(_OPTIONAL_HEADING)
        controls.addWidget(w.optional_heading)
        if wall_fields is not None:
            w.gallery_btn = QPushButton(load_icon("upload"), "Share to the gallery…")
            w.gallery_hint = _desc_label(_GALLERY_HINT_WAIT)
            controls.addWidget(w.gallery_btn)
            controls.addWidget(w.gallery_hint)

            dlg = _GalleryDialog(w)
            w.gallery_dialog = dlg
            body_lay = dlg.body
            body_lay.addWidget(_desc_label(
                "Publish this picture in the public gallery at "
                "nocturneastro.com. It is looked at before it appears, and can "
                "be taken down later by asking."))
            body_lay.addWidget(dlg.gallery_link)

            # WHAT IT WILL SAY ABOUT YOU, from the same dict that gets posted,
            # so the panel cannot claim one thing and send another.
            summary = _wall_summary(wall_fields, wall_handle)
            if summary:
                body_lay.addWidget(_desc_label(summary))

            # ONE field, and only when the file supplied no object. A TIFF has
            # no FITS headers and finishing one is a first-class use; without
            # this such a picture reaches the wall as a byline and nothing else.
            if not (wall_fields.get("target") or "").strip():
                body_lay.addWidget(QLabel("Object"))
                w.wall_target = QLineEdit()
                w.wall_target.setPlaceholderText("M 31 — this file does not name one")
                body_lay.addWidget(w.wall_target)

            w.wall_consent = QCheckBox("Publish this in the Nocturne gallery")
            w.wall_btn = dlg.send_btn
            w.wall_btn.setEnabled(False)
            w.wall_note = QLabel("")
            w.wall_note.setWordWrap(True)
            w.wall_note.setObjectName("stepDesc")
            body_lay.addWidget(w.wall_consent)
            body_lay.addWidget(w.wall_note)

            def _wall_state() -> None:
                # Derived from state, never set ad hoc: MainWindow re-runs this
                # from _sync_step_controls, so a send that lands while another
                # job holds the panel cannot switch Send or the box back on.
                if getattr(w, "_wall_sent", False):
                    w.wall_btn.setEnabled(False)     # spent; the same picture goes once
                    w.wall_consent.setEnabled(False)
                    return
                if getattr(w, "_wall_sending", False):
                    # Dead for the whole flight: two presses would queue the
                    # same picture twice.
                    w.wall_btn.setEnabled(False)
                    return
                if not (wall_handle or "").strip():
                    w.wall_btn.setEnabled(False)
                    w.wall_note.setText(
                        "Set a handle in Settings first — it is the only credit "
                        "shown beside your picture in the gallery.")
                    return
                w.wall_btn.setEnabled(w.wall_consent.isChecked())

            def _wall_toggled() -> None:
                _wall_state()
                if (wall_handle or "").strip():
                    w.wall_note.setText("")

            def _wall_click() -> None:
                w._wall_sending = True
                _wall_state()
                w.wall_note.setText("Sending…")
                w.gallery_hint.setText("Sending…")   # seen with the window closed
                w._wall_msg_shown = True
                target = w.wall_target.text().strip() if w.wall_target else ""
                if on_wall_submit is not None:
                    on_wall_submit(target)

            def _wall_finished(ok: bool, message: str) -> None:
                w._wall_sending = False
                w.wall_note.setText(message)
                # Also under the panel's button: the dialog may have been
                # closed while the send was in flight.
                w.gallery_hint.setText(message)
                w._wall_msg_shown = True
                if ok:
                    w._wall_sent = True
                # On failure Send comes back (a network blip must not cost
                # someone their submission) — through the derivation.
                _wall_state()

            w.wall_consent.toggled.connect(_wall_toggled)
            w.wall_btn.clicked.connect(_wall_click)
            w.gallery_btn.clicked.connect(dlg.open)
            def _gallery_sync(ready: bool) -> None:
                """Share waits for an export of THIS version (MainWindow
                knows). Enablement only: a busy sweep re-closes it, as for
                every control _sync_step_controls touches. A send's own
                message, once there is one, outranks the standing line."""
                w.gallery_btn.setEnabled(bool(ready))
                w.gallery_btn.setToolTip(_GALLERY_TIP if ready else _GALLERY_TIP_WAIT)
                if not getattr(w, "_wall_msg_shown", False):
                    w.gallery_hint.setText(_GALLERY_HINT if ready else _GALLERY_HINT_WAIT)

            w.wall_finished = _wall_finished
            w.wall_sync = _wall_state
            w.gallery_sync = _gallery_sync
            # A rebuilt panel starts from the picture's send, not from scratch.
            state = (wall_state or {}).get("state")
            if state in ("sending", "sent", "failed"):
                w._wall_sending = state == "sending"
                w._wall_sent = state == "sent"
                msg = (wall_state or {}).get("message", "")
                w.wall_note.setText(msg)
                w.gallery_hint.setText(msg)
                w._wall_msg_shown = True
            _gallery_sync(gallery_ready)
            _wall_state()

        # Save as Preset… — here, not on Enhancements, where it read as an
        # Enhancements-only preset (Andreas, 2026-10-14). The Project-menu item
        # reaches it from both steps; MainWindow gates the two together.
        w.save_preset_btn = QPushButton(load_icon("save-preset"), "Save as Preset…")
        w.save_preset_btn.setObjectName("savePreset")
        w.save_preset_btn.setEnabled(False)
        if on_save_preset is not None:
            w.save_preset_btn.clicked.connect(lambda: on_save_preset())
        controls.addWidget(w.save_preset_btn)
        w.save_preset_hint = _desc_label(_PRESET_HINT)
        controls.addWidget(w.save_preset_hint)

    else:  # placeholder / unknown
        controls.addWidget(QLabel("Coming soon."))

    # Every stage that can commit gets this, in the same place. Import has
    # nothing to reset (the toolbar Reset owns that) and Export commits nothing.
    # NOT `reset_btn`: the Curves panel already owns that name for its
    # curve-preset Reset (step_panels.py, clicked by tests/ui/test_step_panels.py),
    # and the shared tail runs last, so reusing the name would silently clobber
    # it and the curve reset would start resetting the whole step.
    #
    # Built here but NOT laid out: MainWindow pins it at the right of the main
    # action, on the one row of the side panel's action slot (SidePanel.
    # set_actions; Andreas, 2026-09-25 19:30, "one row", no divider) —
    # reversing the 2026-09-13 call to keep it beside the controls: Apply and
    # Reset in the same place on every step is "about muscle memory again".
    #
    # The "Press Space to toggle before and after" line that sat above it is
    # gone from every panel (spec §2.6: Space, F and Escape move to a Keyboard
    # shortcuts help topic), and so is the "Not applied yet" line: the pending
    # state is now carried by the ApplyButton itself.
    w.reset_step_btn = None
    if stage.id not in ("load", "export"):
        w.reset_step_btn = QPushButton("Reset step")
        w.reset_step_btn.setObjectName("resetStep")   # warm tint, see theme.py
        w.reset_step_btn.setEnabled(False)   # main_window enables when there is work
        if on_reset_step is not None:
            w.reset_step_btn.clicked.connect(lambda: on_reset_step())

    lay.addStretch(1)
    if getattr(w, "spcc_note", None) is not None:
        lay.addWidget(w.spcc_note)     # after the stretch: the card's bottom edge
    return w
