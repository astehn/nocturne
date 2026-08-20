from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from ..core.color import ColorSettings
from ..core.crop import ASPECTS
from .curve_editor import CurveEditor
from .reset_slider import ResetSlider

# Black-point slider resolution. Ten times the other two levels sliders —
# see the levels panel for why.
BLACK_STEPS = 1000

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "deconvolution": ["light", "medium", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
}
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"]
# Target-type stretch presets → default aggressiveness (slider 0–100).
STRETCH_TARGET_DEFAULTS = {"Auto": 50, "Nebula": 60, "Galaxy": 40, "Cluster": 50}
# Inline "needs <tool>" note text per process stage that can be gated.
_GATE_NOTE = {
    "background": "Needs GraXpert — set its path in Settings.",
}


def _desc_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("stepDesc")
    label.setWordWrap(True)
    return label


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
    on_remove_green=None,
    on_removegreen_change=None, on_tint_change=None, on_apply_tint=None,
    on_enhance=None,
    on_stretch_change=None,
    on_levels_change=None,
    on_levels_auto=None,
    on_sat_change=None,
    on_sat_apply=None,
    on_fringe_change=None,
    on_fringe_apply=None,
    on_lc_change=None,
    on_show_model=None,
    on_curve_change=None,
    on_curve_preset=None, on_curve_expand=None,
    on_recover_change=None,
    on_sr_change=None,
    on_sr_apply=None,
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
        btn = QPushButton("Open FITS…")
        if on_open is not None:
            btn.clicked.connect(lambda: on_open())
        lay.addWidget(btn)
        meta = _desc_label("Open a stacked Seestar FITS to begin.")
        meta.setObjectName("importMeta")   # brighter/larger than stepDesc — the FITS info must be readable
        meta.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(meta)
        w.meta_label = meta
        note = _desc_label(
            "Teal cast and a flat histogram are normal here — this is your "
            "un-stretched data. Colour and contrast come in the next steps.")
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
        guides.addItems(["None", "Rule of thirds", "Center cross"])
        _GUIDE_KIND = {"None": "none", "Rule of thirds": "thirds",
                       "Center cross": "center"}
        if on_guides_change is not None:
            guides.currentTextChanged.connect(
                lambda t: on_guides_change(_GUIDE_KIND[t]))
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
            engine_box.addItems(denoise_engine_choices)   # ["Default","RC-Astro","GraXpert"]
            lay.addWidget(QLabel("Engine"))
            lay.addWidget(engine_box)
            w.engine_box = engine_box

        def _noise_apply_option():
            level = box.currentText()
            if stage.id != "noise_sharpen":
                return level                              # background / deconvolution: bare level
            if engine_box is not None:
                sel = engine_box.currentText()
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
        # Nocturne shipped Remove Green for a cast its own stacks never have, and
        # nothing for the one they always do.
        #
        # Multiplicative gains on linear data, applied here rather than after the
        # stretch, for a measured reason: an ADDITIVE move at this point is erased
        # by neutral_stretch's background re-levelling (shift 0.00000), while a
        # gain survives. It also leaves the background alone (also 0.00000), which
        # is what we want -- the magenta is in the nebulosity, and the background
        # is already faintly GREEN from chroma noise.
        lay.addWidget(_desc_label(
            "Optional. Nudge the overall colour if it looks too magenta or too "
            "green. Double-click a slider to re-centre it."))
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

        apply_tint_btn = QPushButton("Apply Tint")
        apply_tint_btn.setEnabled(apply_enabled)
        if on_apply_tint is not None:
            apply_tint_btn.clicked.connect(
                lambda: on_apply_tint(tint_slider.value() / 100.0,
                                      temp_slider.value() / 100.0))
        lay.addWidget(apply_tint_btn)
        w.apply_tint_btn = apply_tint_btn

        # Remove Green (SCNR) with a strength dial + live preview — a knob, not a
        # hammer. 1.00 == the classic full clamp.
        #
        # Default OFF, not 0.40. SCNR clamps green only where it exceeds the
        # red/blue average, and on data with no green cast that happens only in
        # the noise — so it shaves the upper half of green's fluctuations, skews
        # the distribution the stretch neutralises on, and makes the sky GREENER.
        # Measured on a real M 31 mosaic: the stretched sky went 0.983 -> 1.003 at
        # strength 0.40 and -> 1.027 at 1.00, where 1.000 is neutral. A default
        # that harms the common case is the wrong default.
        lay.addWidget(_desc_label(
            "Optional, and usually unnecessary: the stretch already neutralises "
            "the sky. Reach for this only if a green cast survives it, then drag "
            "for strength (right = stronger)."))
        rg_slider = ResetSlider(0)           # off until the user asks for it
        rg_val = QLabel("0.00")
        rg_row = QHBoxLayout()
        rg_row.addWidget(QLabel("Green removal"))
        rg_row.addWidget(rg_val)
        remove_green_btn = QPushButton("Remove Green")
        remove_green_btn.setEnabled(apply_enabled)
        if on_removegreen_change is not None:
            rg_slider.valueChanged.connect(
                lambda v: (rg_val.setText(f"{v / 100:.2f}"), on_removegreen_change(v / 100.0)))
        if on_remove_green is not None:
            remove_green_btn.clicked.connect(
                lambda: on_remove_green(rg_slider.value() / 100.0))
        lay.addLayout(rg_row)
        lay.addWidget(rg_slider)
        lay.addWidget(remove_green_btn)
        w.apply_btn = apply_btn
        w.remove_green_btn = remove_green_btn
        w.rg_slider = rg_slider

    elif stage.kind == "stretch":
        lay.addWidget(_desc_label("Brighten the faint detail so the target appears."))
        slider = ResetSlider(50)
        target = QComboBox()
        target.addItems(list(STRETCH_TARGET_DEFAULTS))
        target.currentTextChanged.connect(
            lambda t: slider.setValue(STRETCH_TARGET_DEFAULTS[t])
        )
        stretch_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_stretch(*_):
            stretch_val.setText(f"{slider.value() / 100:.2f}")
            if on_stretch_change is not None:
                on_stretch_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_stretch)
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Target"))
        lay.addWidget(target)
        agg_row = QHBoxLayout()
        agg_row.addWidget(QLabel("Aggressiveness (gentle → punchy)"))
        agg_row.addWidget(stretch_val)
        lay.addLayout(agg_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.target_box = target
        w.stretch_slider = slider
        w.stretch_val = stretch_val
        w.apply_btn = apply_btn

    elif stage.kind == "levels":
        lay.addWidget(_desc_label("Fine-tune black point, midtones, and white point."))
        auto_btn = QPushButton("Auto")
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
        lay.addWidget(_desc_label(
            "Remove the green colour fringe around stars. De-greens only the region "
            "around stars, so nebula colour is untouched. 0 = off. Works without "
            "RC-Astro; RC-Astro (StarX) gives a cleaner result."))
        status = _desc_label("")   # main_window sets "Separating stars…" / gate text
        lay.addWidget(status)
        slider = ResetSlider(0)
        fringe_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_fringe(*_):
            fringe_val.setText(f"{slider.value() / 100:.2f}")
            if on_fringe_change is not None:
                on_fringe_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_fringe)
        apply_btn = QPushButton("Apply Remove Green Fringe")
        apply_btn.setObjectName("primary")
        if on_fringe_apply is not None:
            apply_btn.clicked.connect(lambda: on_fringe_apply(slider.value() / 100.0))
        # Start disabled — main_window enables once the (slow) StarX split is ready.
        slider.setEnabled(False)
        apply_btn.setEnabled(False)
        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Strength (off → full)"))
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
            wide_ok = fmt.startswith("TIFF")
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

    else:  # placeholder / unknown
        lay.addWidget(QLabel("Coming soon."))

    lay.addStretch(1)
    return w
