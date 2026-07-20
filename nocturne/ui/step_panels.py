from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from ..core.color import ColorSettings
from ..core.crop import ASPECTS
from .reset_slider import ResetSlider

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
    on_enhance=None,
    on_levels_change=None,
    on_levels_auto=None,
    on_levels_clipping=None,
    on_sat_change=None,
    on_lc_change=None,
    on_sr_change=None,
    on_sr_apply=None,
    apply_enabled: bool = True,
    split_enabled: bool = False,
    option_default: str | None = None,
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
                "use Before/After (toolbar) to check the result."))
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
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(box.currentText()))
        lay.addWidget(QLabel("Strength"))
        lay.addWidget(box)
        lay.addWidget(apply_btn)
        lay.addWidget(note)
        _update_enabled()
        w.option_box = box
        w.apply_btn = apply_btn
        w.disabled_note = note

    elif stage.kind == "enhance":
        lay.addWidget(_desc_label(
            "Final targeted tweaks — tap to stack, Undo to peel back."))
        _specs = [
            ("boost_red_btn", "Boost Red (Ha)", "Boost Red"),
            ("boost_cyan_btn", "Boost Cyan (OIII)", "Boost Cyan"),
            ("boost_blue_btn", "Boost Blue", "Boost Blue"),
            ("darken_sky_btn", "Darken Sky", "Darken Sky"),
            ("lighten_sky_btn", "Lighten Sky", "Lighten Sky"),
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
        apply_btn = QPushButton("Apply Color")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(ColorSettings()))
        remove_green_btn = QPushButton("Remove Green")
        remove_green_btn.setEnabled(apply_enabled)
        if on_remove_green is not None:
            remove_green_btn.clicked.connect(lambda: on_remove_green())
        lay.addWidget(apply_btn)
        lay.addWidget(remove_green_btn)
        w.apply_btn = apply_btn
        w.remove_green_btn = remove_green_btn

    elif stage.kind == "stretch":
        lay.addWidget(_desc_label("Brighten the faint detail so the target appears."))
        slider = ResetSlider(50)
        target = QComboBox()
        target.addItems(list(STRETCH_TARGET_DEFAULTS))
        target.currentTextChanged.connect(
            lambda t: slider.setValue(STRETCH_TARGET_DEFAULTS[t])
        )
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Target"))
        lay.addWidget(target)
        lay.addWidget(QLabel("Aggressiveness (gentle → punchy)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.target_box = target
        w.stretch_slider = slider
        w.apply_btn = apply_btn

    elif stage.kind == "levels":
        lay.addWidget(_desc_label("Fine-tune black point, midtones, and white point."))
        auto_btn = QPushButton("Auto")
        if on_levels_auto is not None:
            auto_btn.clicked.connect(lambda: on_levels_auto())
        lay.addWidget(auto_btn)

        black = ResetSlider(0)
        gamma = ResetSlider(100, minimum=10, maximum=300)  # 1.00
        white = ResetSlider(100)
        black_val = QLabel("0.00")
        gamma_val = QLabel("1.00")
        white_val = QLabel("1.00")

        def _emit(*_):
            black_val.setText(f"{black.value() / 100:.2f}")
            gamma_val.setText(f"{gamma.value() / 100:.2f}")
            white_val.setText(f"{white.value() / 100:.2f}")
            if on_levels_change is not None:
                on_levels_change(
                    black.value() / 100.0, gamma.value() / 100.0, white.value() / 100.0
                )

        black.valueChanged.connect(_emit)
        gamma.valueChanged.connect(_emit)
        white.valueChanged.connect(_emit)

        apply_btn = QPushButton("Apply Levels")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(
                (black.value() / 100.0, gamma.value() / 100.0, white.value() / 100.0)
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

        clip_check = QCheckBox("Show clipping")
        if on_levels_clipping is not None:
            clip_check.toggled.connect(lambda c: on_levels_clipping(c))
        lay.addWidget(clip_check)

        lay.addWidget(apply_btn)
        w.auto_btn = auto_btn
        w.black_slider = black
        w.gamma_slider = gamma
        w.white_slider = white
        w.black_val = black_val
        w.gamma_val = gamma_val
        w.white_val = white_val
        w.clip_check = clip_check
        w.apply_btn = apply_btn

    elif stage.kind == "saturation":
        lay.addWidget(_desc_label(
            "Drag left to mute colour, right to boost. Centre = no change."))
        slider = ResetSlider(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
        sat_val = QLabel(f"{slider.value() / 100:.2f}")

        def _emit_sat(*_):
            sat_val.setText(f"{slider.value() / 100:.2f}")
            if on_sat_change is not None:
                on_sat_change(slider.value() / 100.0)

        slider.valueChanged.connect(_emit_sat)
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        sat_row = QHBoxLayout()
        sat_row.addWidget(QLabel("Saturation (mute ← native → boost)"))
        sat_row.addWidget(sat_val)
        lay.addLayout(sat_row)
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
        w.sat_val = sat_val
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
        box = QComboBox()
        box.addItems(EXPORT_FORMATS)
        if not split_enabled:
            box.model().item(3).setEnabled(False)  # starless+stars split needs StarX
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export is not None:
            export_btn.clicked.connect(lambda: on_export(box.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(box)
        lay.addWidget(export_btn)
        if not split_enabled:
            lay.addWidget(_desc_label(
                "Starless + stars split needs RC-Astro (set its path in Settings)."))
        w.fmt_box = box
        w.export_btn = export_btn

    else:  # placeholder / unknown
        lay.addWidget(QLabel("Coming soon."))

    lay.addStretch(1)
    return w
