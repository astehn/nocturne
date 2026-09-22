from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget,
)

from ..core.autostretch import _TARGET_BG
from ..steps.stretch_step import _DEFAULT as _STEP_DEFAULT
from ..core.color import ColorSettings
from ..core.stretch import _TARGET_MAX as _STRETCH_MAX, _TARGET_MIN as _STRETCH_MIN
from ..core.crop import ASPECTS, GUIDE_KINDS, GUIDES
from .curve_editor import CurveEditor
from .reset_slider import ResetSlider

# Black-point slider resolution. Ten times the other two levels sliders —
# see the levels panel for why.
BLACK_STEPS = 1000

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "deconvolution": ["light", "medium", "strong"],
    "ai_denoise": ["light", "medium", "strong"],
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


def _desc_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("stepDesc")
    label.setWordWrap(True)
    return label


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
    return "The wall will show: " + " \u00b7 ".join(bits) if bits else ""


def build_panel(
    stage,
    *,
    on_open=None,
    on_apply=None,
    on_crop_apply=None,
    on_crop_change=None,
    on_guides_change=None,
    on_rotate=None,
    on_flip_h=None,
    on_flip_v=None,
    on_export=None,
    wall_fields=None, wall_handle="", on_wall_submit=None,
    on_remove_green=None,
    on_removegreen_change=None, on_tint_change=None, on_apply_tint=None,
    on_enhance=None,
    on_stretch_change=None,
    on_visual_stretch=None,
    on_view_linked=None,
    view_linked=True,
    stretch_linked=True,
    on_opened_as_linear=None,
    opened_as_linear=None,
    on_levels_change=None,
    on_levels_auto=None,
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
    option_default: str | None = None,
    denoise_engine_choices: list | None = None,
    denoise_default_engine: str = "rcastro",
) -> QWidget:
    w = QWidget()
    w.setObjectName("stepCard")
    w.panel_kind = stage.kind
    lay = QVBoxLayout(w)
    title = QLabel(stage.label)
    title.setObjectName("stageTitle")
    lay.addWidget(title)

    if stage.kind == "import":
        # No "Open FITS…" button: the toolbar has one and the cold-start screen
        # has its own pair, so this copy was unreachable in every state where it
        # would have been the entry point.
        meta = _desc_label("Open a stacked Seestar FITS to begin.")
        meta.setObjectName("importMeta")   # brighter/larger than stepDesc — the FITS info must be readable
        meta.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(meta)
        w.meta_label = meta

        # How the LINEAR data is drawn. A view, not a commitment: no pixel is
        # touched and no history entry is made. It exists because the linked
        # view leaves a uniform cast on data whose channels have very different
        # spreads (R/G MAD 2.67 on IC 1396A), and a uniform cast reads as
        # monochrome however saturated it actually is.
        heading = QLabel("How to show the unstretched data")
        heading.setObjectName("panelSectionLabel")
        lay.addWidget(heading)
        row = QHBoxLayout()
        linked_btn = QRadioButton("Linked")
        linked_btn.setToolTip("Keeps the sky's own colour")
        unlinked_btn = QRadioButton("Unlinked")
        unlinked_btn.setToolTip("Evens the channels out")
        group = QButtonGroup(w)
        group.addButton(linked_btn); group.addButton(unlinked_btn)
        (linked_btn if view_linked else unlinked_btn).setChecked(True)
        row.addWidget(linked_btn); row.addWidget(unlinked_btn); row.addStretch(1)
        lay.addLayout(row)
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
            lay.addWidget(head)
            row2 = QHBoxLayout()
            lin_btn = QRadioButton("Unstretched data")
            stretched_btn = QRadioButton("Already stretched")
            grp2 = QButtonGroup(w)
            grp2.addButton(lin_btn); grp2.addButton(stretched_btn)
            (lin_btn if opened_as_linear else stretched_btn).setChecked(True)
            row2.addWidget(lin_btn); row2.addWidget(stretched_btn); row2.addStretch(1)
            lay.addLayout(row2)
            if on_opened_as_linear is not None:
                lin_btn.toggled.connect(lambda on: on_opened_as_linear(bool(on)))
            w.opened_as_linear = lin_btn
            w._opened_group = grp2      # or the QButtonGroup is garbage collected
            lay.addWidget(_desc_label(
                "Nocturne measured the pixels to decide this. It is nearly always "
                "right, but a starless file or a very bright subject can fool it — "
                "if the picture looks wrong from here, switch it."))

        note = _desc_label(
            "Linked keeps the sky's own colour; Unlinked evens the channels out, "
            "which usually shows more variety in star and dust colour. This only "
            "changes what you see — you choose again, and commit, at Stretch.")
        note.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(note)

    elif stage.kind == "crop":
        lay.addWidget(_desc_label(
            "Click the image to place the crop box, adjust it, then Apply Crop."))
        aspect = QComboBox()
        aspect.addItems(ASPECTS)
        if on_crop_change is not None:
            aspect.currentTextChanged.connect(lambda t: on_crop_change(t))
        rotate_btn = QPushButton("Rotate 90° ↻")
        if on_rotate is not None:
            rotate_btn.clicked.connect(lambda: on_rotate())
        flip_h = QPushButton("Flip H")
        if on_flip_h is not None:
            flip_h.clicked.connect(lambda: on_flip_h())
        flip_v = QPushButton("Flip V")
        if on_flip_v is not None:
            flip_v.clicked.connect(lambda: on_flip_v())
        apply_btn = QPushButton("Apply Crop")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(False)  # off until the crop box is shown (cropBoxShown)
        if on_crop_apply is not None:
            apply_btn.clicked.connect(lambda: on_crop_apply())
        guides = QComboBox()
        guides.addItems(GUIDES)
        if on_guides_change is not None:
            guides.currentTextChanged.connect(
                lambda t: on_guides_change(GUIDE_KINDS[t]))
        lay.addWidget(QLabel("Aspect ratio"))
        lay.addWidget(aspect)
        lay.addWidget(QLabel("Guides"))
        lay.addWidget(guides)
        lay.addWidget(rotate_btn)
        flips = QHBoxLayout()
        flips.addWidget(flip_h)
        flips.addWidget(flip_v)
        lay.addLayout(flips)
        lay.addWidget(_desc_label("Rotate / Flip apply instantly"))
        lay.addWidget(apply_btn)
        size = _desc_label("—")
        lay.addWidget(size)
        w.aspect_box = aspect
        w.guides_box = guides
        w.rotate_btn = rotate_btn
        w.flip_h_btn = flip_h
        w.flip_v_btn = flip_v
        w.apply_btn = apply_btn
        w.crop_size_label = size

    elif stage.kind == "process":
        if stage.id == "background":
            lay.addWidget(_desc_label(
                "A gradient is uneven sky-glow — brighter toward one edge or corner. "
                "Light suits most images; use Strong when it's heavy. After applying, "
                "tick Show what was removed: mid-grey is where nothing was taken, and "
                "a smooth ramp is sky-glow. If it carries the shape of your object, "
                "the fit took signal with it — undo and try Light."))
        box = QComboBox()
        box.addItems(_PROCESS_OPTIONS[stage.id])
        if option_default:
            box.setCurrentText(option_default)
        apply_btn = QPushButton(f"Apply {stage.label}")
        apply_btn.setObjectName("primary")
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
            # The pending label reads the dropdown, so it has to hear the
            # dropdown. Without this it only caught up on the next _refresh,
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
        if stage.id in ("noise_sharpen", "ai_denoise") and denoise_engine_choices:
            engine_box = QComboBox()
            engine_box.addItems(denoise_engine_choices)   # ["Default","RC-Astro","GraXpert"]
            lay.addWidget(QLabel("Engine"))
            lay.addWidget(engine_box)
            w.engine_box = engine_box

        def _noise_apply_option():
            level = box.currentText()
            if stage.id not in ("noise_sharpen", "ai_denoise"):
                return level                              # background / deconvolution: bare level
            if engine_box is not None:
                sel = engine_box.currentText()
                if sel.startswith("Nocturne NR ("):   # ai_denoise, and nothing else
                    # "Nocturne NR (v6)" -> "nr:v6". The label carries the file
                    # name so two runs can sit side by side in the dropdown.
                    engine = "nr:" + sel[len("Nocturne NR ("):-1]
                else:
                    engine = (denoise_default_engine if sel == "Default"
                              else "graxpert" if sel == "GraXpert" else "rcastro")
            else:
                engine = denoise_default_engine
            return {"engine": engine, "level": level}

        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(_noise_apply_option()))
        lay.addWidget(QLabel("Strength"))
        lay.addWidget(box)
        lay.addWidget(apply_btn)
        lay.addWidget(note)
        _update_enabled()
        w.option_box = box
        # What the dropdown read on arrival. "Pending" means "moved since the
        # last commit or since I got here", and only the panel can answer that:
        # the committed history stores whatever the step recorded — a dict for
        # Noise Reduction, nothing at all for Background "off" — and a rebuilt
        # panel starts at the step default rather than at the committed value.
        w.option_baseline = box.currentText()
        w.apply_btn = apply_btn
        w.disabled_note = note
        if show_model is not None:
            lay.addWidget(show_model)
            w.show_model_check = show_model

    elif stage.kind == "enhance":
        lay.addWidget(_desc_label(
            "Final targeted tweaks — tap to stack, Undo to peel back."))
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
        for attr, label, op in _specs:
            btn = QPushButton(label)
            if on_enhance is not None:
                btn.clicked.connect(lambda _=False, o=op: on_enhance(o))
            lay.addWidget(btn)
            setattr(w, attr, btn)

    elif stage.kind == "auto":
        lay.addWidget(_desc_label(
            "Neutralises the sky background so it's colour-neutral, without "
            "touching your nebula's real colour."
        ))
        lay.addWidget(QLabel("Method"))
        method_box = QComboBox()
        method_box.addItems(["Sky balance", "Photometric (SPCC)"])
        lay.addWidget(method_box)
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

        apply_btn = QPushButton("Apply Color")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(_color_option()))
        lay.addWidget(apply_btn)
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
        # gain survives. It also leaves the background alone (also 0.00000), which
        # is what we want -- the magenta is in the nebulosity, and the background
        # is already faintly GREEN from chroma noise.
        # De-green Sky moved out to its own stage, which freed the room this
        # uses. Andreas, 2026-09-13: the two groups "feel a bit crammed together
        # now". A rule and a heading, not just padding — the point is that what
        # follows is OPTIONAL, and the step's own copy already said so in prose
        # nobody reads. This is the Colour half of the decided 2026-09-12
        # "separate and label the optional tools"; with De-green Sky gone, only
        # Tint remains, so it is one divider and one label rather than a layout.
        lay.addSpacing(14)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setObjectName("panelRule")
        lay.addWidget(rule)
        lay.addSpacing(10)
        optional = QLabel("Optional")
        optional.setObjectName("panelSectionLabel")
        lay.addWidget(optional)
        lay.addWidget(_desc_label(
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
        lay.addLayout(tint_row)
        lay.addWidget(tint_slider)

        temp_slider = ResetSlider(0, minimum=-100, maximum=100)
        temp_val = QLabel("0.00")
        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("Cool ←→ Warm"))
        temp_row.addWidget(temp_val)
        temp_slider.valueChanged.connect(_emit_tint)
        lay.addLayout(temp_row)
        lay.addWidget(temp_slider)
        w.tint_slider = tint_slider
        w.temp_slider = temp_slider
        # What the controls describe UNTOUCHED. main_window compares the live
        # value against this, so putting a slider back where you found it stops
        # the step reading as pending. Must stay in step with _emit_tint above —
        # test_neutral_option_matches_the_emit fires both and compares.
        w.neutral_option = (tint_slider.value() / 100.0, temp_slider.value() / 100.0)

        apply_tint_btn = QPushButton("Apply Tint")
        # Without this, theme.py's `QPushButton#primary[pending=...]` selector
        # never matches it at all — _sync_step_controls sets the Qt property
        # every time regardless, so the button silently never changes colour.
        apply_tint_btn.setObjectName("primary")
        apply_tint_btn.setEnabled(apply_enabled)
        if on_apply_tint is not None:
            apply_tint_btn.clicked.connect(
                lambda: on_apply_tint(tint_slider.value() / 100.0,
                                      temp_slider.value() / 100.0))
        lay.addWidget(apply_tint_btn)
        w.apply_tint_btn = apply_tint_btn
        w.apply_btn = apply_btn

    elif stage.kind == "stretch":
        lay.addWidget(_desc_label("Brighten the faint detail so the target appears."))
        slider = ResetSlider(STRETCH_DEFAULT)
        stretch_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_stretch(*_):
            stretch_val.setText(f"{slider.value() / 100:.2f}")
            if on_stretch_change is not None:
                on_stretch_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_stretch)
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            # A DICT, not a bare float: the stretch now carries its MECHANISM
            # as well as its amount, and both have to reach the commit. Anchored
            # on the Visual-stretch comment below, because this exact Apply line
            # appears in three panels and a bare replace patched all three.
            apply_btn.clicked.connect(
                lambda: on_apply({"amount": slider.value() / 100.0,
                                  "linked": bool(w.stretch_linked)}))
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
        lay.addLayout(agg_row)
        lay.addWidget(slider)
        lay.addWidget(visual_btn)
        lay.addWidget(apply_btn)
        w.visual_btn = visual_btn
        w.stretch_linked = bool(stretch_linked)
        w.stretch_slider = slider
        w.stretch_val = stretch_val
        w.apply_btn = apply_btn

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
        lay.addWidget(_desc_label(
            "Optional, and usually unnecessary. Look at the sky you just "
            "stretched: if it carries a green cast, drag for strength (right = "
            "stronger). If it does not, leave this at 0 — on data with no cast "
            "this makes the sky greener, not less green."))
        rg_slider = ResetSlider(0)           # off until the user asks for it
        rg_val = QLabel("0.00")
        rg_row = QHBoxLayout()
        rg_row.addWidget(QLabel("Green removal"))
        rg_row.addWidget(rg_val)
        w.neutral_option = rg_slider.value() / 100.0
        if on_removegreen_change is not None:
            rg_slider.valueChanged.connect(
                lambda v: (rg_val.setText(f"{v / 100:.2f}"), on_removegreen_change(v / 100.0)))
        lay.addLayout(rg_row)
        lay.addWidget(rg_slider)
        apply_btn = QPushButton("Apply De-green Sky")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_remove_green is not None:
            apply_btn.clicked.connect(lambda: on_remove_green(rg_slider.value() / 100.0))
        lay.addWidget(apply_btn)
        w.rg_slider = rg_slider
        w.apply_btn = apply_btn

    elif stage.kind == "levels":
        lay.addWidget(_desc_label("Fine-tune black point, midtones, and white point."))
        auto_btn = QPushButton("Auto")
        # Checkable purely as an INDICATOR: it stays down while the values on the
        # sliders are still the ones Auto derived, and pops up the moment one is
        # nudged. That is the only sign of whether the recipe will store "derive
        # this per image" or three frozen numbers.
        auto_btn.setCheckable(True)
        auto_btn.setToolTip(
            "Derive the black point from this image. Stays selected while the "
            "values are still the derived ones — a recipe then re-derives them "
            "for each image instead of reusing this one's.")
        if on_levels_auto is not None:
            auto_btn.clicked.connect(lambda: on_levels_auto())
        lay.addWidget(auto_btn)

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

        def _emit(*_):
            black_val.setText(f"{black.value() / BLACK_STEPS:.3f}")
            gamma_val.setText(f"{gamma.value() / 100:.2f}")
            white_val.setText(f"{white.value() / 100:.2f}")
            if on_levels_change is not None:
                on_levels_change(
                    black.value() / BLACK_STEPS, gamma.value() / 100.0,
                    white.value() / 100.0
                )

        w.neutral_option = (black.value() / BLACK_STEPS, gamma.value() / 100.0,
                            white.value() / 100.0)
        black.valueChanged.connect(_emit)
        gamma.valueChanged.connect(_emit)
        white.valueChanged.connect(_emit)

        apply_btn = QPushButton("Apply Levels")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(
                (black.value() / BLACK_STEPS, gamma.value() / 100.0,
                 white.value() / 100.0)
            ))

        black_row = QHBoxLayout()
        black_row.addWidget(QLabel("Black point"))
        black_row.addWidget(black_val)
        lay.addLayout(black_row)
        lay.addWidget(black)

        gamma_row = QHBoxLayout()
        gamma_row.addWidget(QLabel("Midtones"))
        gamma_row.addWidget(gamma_val)
        lay.addLayout(gamma_row)
        lay.addWidget(gamma)

        white_row = QHBoxLayout()
        white_row.addWidget(QLabel("White point"))
        white_row.addWidget(white_val)
        lay.addLayout(white_row)
        lay.addWidget(white)

        lay.addWidget(apply_btn)
        w.auto_btn = auto_btn
        w.black_slider = black
        w.gamma_slider = gamma
        w.white_slider = white
        w.black_val = black_val
        w.gamma_val = gamma_val
        w.white_val = white_val
        w.apply_btn = apply_btn

    elif stage.kind == "curves":
        lay.addWidget(_desc_label(
            "Drag the curve to add midtone contrast. Drop a point on the "
            "background peak to pin the sky. Double-click a point to remove it."))
        editor = CurveEditor()
        # Give it the pane's spare height. The right pane is 400 px wide and
        # fixed (so the image never moves between steps), and the editor was
        # sitting at its 240 px minimum inside a 424 px pane — 184 px unused,
        # in the one widget where area is precision. It draws SQUARE now, so
        # extra height also buys width up to the pane.
        editor.setMinimumHeight(320)
        # Curves' neutral is the identity curve the editor is built with.
        w.neutral_option = list(editor.points())
        if on_curve_change is not None:
            editor.curveChanged.connect(lambda pts: on_curve_change(pts))
        lay.addWidget(editor, 1)

        preset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        add_btn = QPushButton("Add contrast")
        if on_curve_preset is not None:
            reset_btn.clicked.connect(lambda: on_curve_preset("reset"))
            add_btn.clicked.connect(lambda: on_curve_preset("add_contrast"))
        preset_row.addWidget(reset_btn)
        preset_row.addWidget(add_btn)
        lay.addLayout(preset_row)

        # The pane cannot get wider, so precision work goes to a dialog — the
        # same answer Colour Balance and Narrowband already use. The inline
        # editor stays the default: a quick tweak should not need a window.
        expand_btn = QPushButton("Open large editor…")
        if on_curve_expand is not None:
            expand_btn.clicked.connect(lambda: on_curve_expand())
        lay.addWidget(expand_btn)
        w.expand_btn = expand_btn

        apply_btn = QPushButton("Apply Curves")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(editor.points()))
        lay.addWidget(apply_btn)

        w.curve_editor = editor
        w.reset_btn = reset_btn
        w.add_contrast_btn = add_btn
        w.apply_btn = apply_btn

    elif stage.kind == "saturation":
        lay.addWidget(_desc_label(
            "Drag Saturation left to mute colour, right to boost. Centre = no change. "
            "Nebula boost lifts only the nebulosity (stars & sky untouched); RC-Astro "
            "(StarX) gives a cleaner separation but is not required."))
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
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_sat_apply is not None:
            apply_btn.clicked.connect(
                lambda: on_sat_apply(slider.value() / 100.0, neb.value() / 100.0))
        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Saturation (mute ← native → boost)"))
        sat_row.addWidget(sat_val)
        lay.addLayout(sat_row)
        lay.addWidget(slider)
        neb_row = QHBoxLayout()
        neb_row.addWidget(QLabel("Nebula boost (off → strong)"))
        neb_row.addWidget(neb_val)
        lay.addLayout(neb_row)
        lay.addWidget(neb)
        lay.addWidget(neb_status)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
        w.sat_val = sat_val
        w.neb_slider = neb
        w.neb_val = neb_val
        w.neb_status = neb_status
        w.apply_btn = apply_btn

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
        # noise visibly shifts too. The description below has to say so.
        lay.addWidget(_desc_label(
            "Drain the green-to-cyan tint from stars — those pixels lose their "
            "colour and keep their lightness, and every other colour is left "
            "alone. No star is truly green or cyan, so the tint is always an "
            "artefact. Amount 100 removes it entirely; lower values leave some "
            "of it, like Photoshop's Hue/Saturation on Cyans. With a star "
            "separator configured only the stars layer is touched and nebula "
            "colour cannot move; without one, the free path works on the whole "
            "image inside a feathered mask centred on stars, so background "
            "colour can shift too."))
        status = _desc_label("")   # main_window sets the split/mask label or gate text
        lay.addWidget(status)
        slider = ResetSlider(100)
        fringe_val = QLabel(f"{slider.value()}")

        def _emit_fringe(*_):
            fringe_val.setText(f"{slider.value()}")
            if on_fringe_change is not None:
                on_fringe_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_fringe)
        apply_btn = QPushButton("Apply De-green Stars")
        apply_btn.setObjectName("primary")
        if on_fringe_apply is not None:
            apply_btn.clicked.connect(lambda: on_fringe_apply(slider.value() / 100.0))
        # Start disabled — main_window enables once the (slow) split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Amount (none → fully neutral)"))
        fringe_row.addWidget(fringe_val)
        lay.addLayout(fringe_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.fringe_status = status
        w.fringe_slider = slider
        w.fringe_val = fringe_val
        w.apply_btn = apply_btn

    elif stage.kind == "recover_core":
        lay.addWidget(_desc_label(
            "Pull blown-out bright cores back so they show detail instead of a "
            "white blob. 0 = off."))
        slider = ResetSlider(0)
        recover_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_recover(*_):
            recover_val.setText(f"{slider.value() / 100:.2f}")
            if on_recover_change is not None:
                on_recover_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_recover)
        apply_btn = QPushButton("Apply Recover Core")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        rec_row = QHBoxLayout()
        rec_row.addWidget(QLabel("Strength (off → full)"))
        rec_row.addWidget(recover_val)
        lay.addLayout(rec_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.recover_slider = slider
        w.recover_val = recover_val
        w.apply_btn = apply_btn

    elif stage.kind == "local_contrast":
        lay.addWidget(_desc_label(
            "Drag up to add mid-scale depth. 0 = off."))
        slider = ResetSlider(0)
        lc_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_lc(*_):
            lc_val.setText(f"{slider.value() / 100:.2f}")
            if on_lc_change is not None:
                on_lc_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_lc)
        apply_btn = QPushButton("Apply Local Contrast")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lc_row = QHBoxLayout()
        lc_row.addWidget(QLabel("Strength (off → full)"))
        lc_row.addWidget(lc_val)
        lay.addLayout(lc_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.lc_slider = slider
        w.lc_val = lc_val
        w.apply_btn = apply_btn

    elif stage.kind == "star_reduction":
        lay.addWidget(_desc_label(
            "Shrink and dim the stars so the nebula stands out. Drag right for "
            "more reduction. 0 = untouched."))
        status = _desc_label("")   # main_window sets "Separating stars…" / gate text
        lay.addWidget(status)
        slider = ResetSlider(0)
        sr_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_sr(*_):
            sr_val.setText(f"{slider.value() / 100:.2f}")
            if on_sr_change is not None:
                on_sr_change(slider.value() / 100.0)

        w.neutral_option = slider.value() / 100.0
        slider.valueChanged.connect(_emit_sr)
        apply_btn = QPushButton("Apply Star Reduction")
        apply_btn.setObjectName("primary")
        if on_sr_apply is not None:
            apply_btn.clicked.connect(lambda: on_sr_apply(slider.value() / 100.0))
        # Start disabled — main_window enables once the (slow) StarX split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        sr_row = QHBoxLayout()
        sr_row.addWidget(QLabel("Reduction (none → strong)"))
        sr_row.addWidget(sr_val)
        lay.addLayout(sr_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.sr_status = status
        w.sr_slider = slider
        w.sr_val = sr_val
        w.apply_btn = apply_btn

    elif stage.kind == "export":
        from ..core.colour import EIGHT_BIT_SPACES, SPACES
        box = QComboBox()
        box.addItems(EXPORT_FORMATS)
        if not split_enabled:
            box.model().item(3).setEnabled(False)  # starless+stars split needs StarX

        # Colour space. Every export is TAGGED with whichever is chosen, so a
        # reader never has to guess — an untagged file is why a correct M 16
        # export rendered dark in Photoshop.
        space_box = QComboBox()
        space_box.addItems(list(SPACES))

        def _restrict_space(fmt: str) -> None:
            """Wide gamut only for 16-bit TIFF.

            Adobe RGB spreads the same 256 levels over a larger volume, so an
            8-bit file in one bands visibly — and astro images are mostly smooth
            gradients, the worst case. Enforced by DISABLING the entries and
            pulling the selection back, not by hiding them: a user who picks
            Adobe RGB and then PNG must not quietly get a banded file.
            """
            wide_ok = fmt in SIXTEEN_BIT_FORMATS
            for i in range(space_box.count()):
                allowed = wide_ok or space_box.itemText(i) in EIGHT_BIT_SPACES
                space_box.model().item(i).setEnabled(allowed)
            if not wide_ok and space_box.currentText() not in EIGHT_BIT_SPACES:
                space_box.setCurrentText(EIGHT_BIT_SPACES[0])

        box.currentTextChanged.connect(_restrict_space)
        _restrict_space(box.currentText())

        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export is not None:
            export_btn.clicked.connect(
                lambda: on_export(box.currentText(), space_box.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(box)
        lay.addWidget(QLabel("Colour space"))
        lay.addWidget(space_box)
        lay.addWidget(_desc_label(
            "Every export is tagged, so other programs show it as you see it "
            "here. Wider spaces are for 16-bit TIFF only — in 8-bit they band."))
        lay.addWidget(export_btn)
        w.format_box = box
        w.space_box = space_box
        w.burn_annotations = QCheckBox("Burn annotations (PNG)")
        w.burn_annotations.setEnabled(False)   # main_window enables when a solve exists
        lay.addWidget(w.burn_annotations)
        if not split_enabled:
            lay.addWidget(_desc_label(
                "Starless + stars split needs RC-Astro (set its path in Settings)."))
        w.fmt_box = box
        w.export_btn = export_btn

        # --- and, optionally, the wall ---------------------------------
        #
        # HERE rather than in the Share dialog (spec 2.4). Share reframes for a
        # destination and composes without the plate, so what it sent differed
        # from what it showed — in the one dialog built around those being the
        # same thing. At the end of the pipeline nothing is transformed on the
        # way out, and this is also the moment someone has just finished
        # something they are pleased with.
        #
        # The panel RECEIVES the facts and a callback. It never touches the
        # image: composing here would be the second compose path all over again,
        # one step to the left.
        w.wall_consent = None
        w.wall_btn = None
        w.wall_note = None
        w.wall_target = None
        if wall_fields is not None:
            # The Colour step's divider, so "optional" reads the same way
            # twice in the app rather than twice differently.
            lay.addSpacing(14)
            wall_rule = QFrame()
            wall_rule.setFrameShape(QFrame.Shape.HLine)
            wall_rule.setObjectName("panelRule")
            lay.addWidget(wall_rule)
            lay.addSpacing(10)
            heading = QLabel("Send to the wall")
            heading.setObjectName("panelSectionLabel")
            lay.addWidget(heading)
            lay.addWidget(_desc_label(
                "Optional. Your picture goes to the gallery for review — it is "
                "not published straight away, and it can be taken down later."))

            # WHAT IT WILL SAY ABOUT YOU, from the same dict that gets posted,
            # so the panel cannot claim one thing and send another.
            summary = _wall_summary(wall_fields, wall_handle)
            if summary:
                lay.addWidget(_desc_label(summary))

            # ONE field, and only when the file supplied no object. A TIFF has
            # no FITS headers and finishing one is a first-class use; without
            # this such a picture reaches the wall as a byline and nothing else.
            if not (wall_fields.get("target") or "").strip():
                lay.addWidget(QLabel("Object"))
                w.wall_target = QLineEdit()
                w.wall_target.setPlaceholderText("M 31 — this file does not name one")
                lay.addWidget(w.wall_target)

            w.wall_consent = QCheckBox("Publish this on the Nocturne wall")
            w.wall_btn = QPushButton("Send to the wall")
            w.wall_btn.setEnabled(False)
            w.wall_note = QLabel("")
            w.wall_note.setWordWrap(True)
            w.wall_note.setObjectName("stepDesc")

            def _wall_state() -> None:
                if getattr(w, "_wall_sent", False):
                    return
                if not (wall_handle or "").strip():
                    w.wall_btn.setEnabled(False)
                    w.wall_note.setText(
                        "Set a handle in Settings first — it is the only credit "
                        "shown beside your picture.")
                    return
                w.wall_btn.setEnabled(w.wall_consent.isChecked())
                w.wall_note.setText("")

            def _wall_click() -> None:
                # Dead for the whole flight: two presses would queue the same
                # picture twice.
                w.wall_btn.setEnabled(False)
                w.wall_note.setText("Sending…")
                target = w.wall_target.text().strip() if w.wall_target else ""
                if on_wall_submit is not None:
                    on_wall_submit(target)

            def _wall_finished(ok: bool, message: str) -> None:
                w.wall_note.setText(message)
                if ok:
                    w._wall_sent = True          # spent; the same picture goes once
                    w.wall_btn.setEnabled(False)
                    w.wall_consent.setEnabled(False)
                else:
                    # A network blip must not cost someone their submission.
                    w.wall_btn.setEnabled(w.wall_consent.isChecked())

            w.wall_consent.toggled.connect(_wall_state)
            w.wall_btn.clicked.connect(_wall_click)
            w.wall_finished = _wall_finished
            lay.addWidget(w.wall_consent)
            lay.addWidget(w.wall_btn)
            lay.addWidget(w.wall_note)
            _wall_state()

    else:  # placeholder / unknown
        lay.addWidget(QLabel("Coming soon."))

    # Every stage that can commit gets this, in the same place. Import has
    # nothing to reset (the toolbar Reset owns that) and Export commits nothing.
    # NOT `reset_btn`: the Curves panel already owns that name for its
    # curve-preset Reset (step_panels.py, clicked by tests/ui/test_step_panels.py),
    # and the shared tail runs last, so reusing the name would silently clobber
    # it and the curve reset would start resetting the whole step.
    # Names the affordance he already had (Space peek) on every stage where
    # comparing is the point — same exclusion as Reset step below. Muted
    # help-text level: this is ambient orientation, not a status the user
    # must notice (that's pending_label, below).
    w.compare_hint = None
    if stage.id not in ("load", "export"):
        w.compare_hint = _desc_label("Press Space to toggle before and after.")
        lay.addWidget(w.compare_hint)

    # Every stage that can commit gets this, in the same place. Import has
    # nothing to reset (the toolbar Reset owns that) and Export commits nothing.
    # NOT `reset_btn`: the Curves panel already owns that name for its
    # curve-preset Reset (step_panels.py, clicked by tests/ui/test_step_panels.py),
    # and the shared tail runs last, so reusing the name would silently clobber
    # it and the curve reset would start resetting the whole step.
    #
    # BELOW the compare hint and behind a rule, moved 2026-09-13. It sat
    # directly under Apply, where Andreas read it as part of the tool: "now they
    # risk reading like they are part of the tool". It is not a parameter — it
    # is recovery, used occasionally and deliberately.
    #
    # Deliberately NOT moved to the bottom of the sidebar, which was the other
    # option considered. That buys a consistent screen position at the cost of
    # distance from the thing it acts on, and "Reset step" isolated at the foot
    # of the pane invites the reading "reset everything" — the label argues
    # against that and placement argues louder. Consistency also earns less here
    # than it would for Apply or Next: nobody builds muscle memory for a button
    # they press once in a while, and when they do press it they are already
    # looking at the panel, having just decided they dislike the result.
    #
    # Same divider idiom as the Colour step's "Optional" group, so the panel has
    # one grammar for "below this line is not the main action".
    w.reset_step_btn = None
    if stage.id not in ("load", "export"):
        lay.addSpacing(12)
        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setObjectName("panelRule")
        lay.addWidget(rule)
        lay.addSpacing(8)
        w.reset_step_btn = QPushButton("Reset step")
        w.reset_step_btn.setObjectName("resetStep")   # warm tint, see theme.py
        w.reset_step_btn.setEnabled(False)   # main_window enables when there is work
        if on_reset_step is not None:
            w.reset_step_btn.clicked.connect(lambda: on_reset_step())
        lay.addWidget(w.reset_step_btn)

    # Every stage, one place. The preview is pixel-identical to the commit by
    # design, so this line is the only thing that distinguishes them.
    w.pending_label = QLabel("Not applied yet")
    w.pending_label.setObjectName("pendingNote")
    w.pending_label.setWordWrap(True)
    w.pending_label.setVisible(False)
    # ABOVE the apply button, not below it. Below the primary action is past
    # where the eye stops — the line answering "did that apply?" has to sit in
    # the path to the button, not after it.
    anchor = getattr(w, "apply_btn", None)
    index = lay.indexOf(anchor) if anchor is not None else -1
    if index >= 0:
        lay.insertWidget(index, w.pending_label)
    else:
        lay.addWidget(w.pending_label)

    lay.addStretch(1)
    return w
