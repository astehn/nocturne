from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
    QWidget,
)

from ..core.color import ColorSettings
from ..core.crop import ASPECTS
from .reset_slider import ResetSlider

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
    "local_contrast": ["light", "medium", "strong"],
    "star_reduction": ["light", "medium", "strong"],
}
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS", "Starless + Stars (two TIFFs)"]
# Target-type stretch presets → default aggressiveness (slider 0–100).
STRETCH_TARGET_DEFAULTS = {"Auto": 50, "Nebula": 60, "Galaxy": 40, "Cluster": 50}
_DESCRIPTIONS = {
    "background": "Removes light-pollution gradients so the sky background is even.",
    "noise_sharpen": "Reduces grain and recovers fine detail.",
    "local_contrast": "Boosts mid-scale structure (local contrast).",
    "star_reduction": "Shrinks stars so nebulosity stands out.",
}
# Inline "needs <tool>" note text per process stage that can be gated.
_GATE_NOTE = {
    "background": "Needs GraXpert — set its path in Settings.",
    "star_reduction": "Needs RC-Astro — set its path in Settings.",
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
    on_rotate=None,
    on_flip_h=None,
    on_flip_v=None,
    on_export=None,
    on_remove_green=None,
    apply_enabled: bool = True,
    split_enabled: bool = False,
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
        lay.addWidget(meta)
        w.meta_label = meta

    elif stage.kind == "crop":
        lay.addWidget(_desc_label(
            "Drag the box then Apply Crop. Rotate/Flip apply instantly."))
        aspect = QComboBox()
        aspect.addItems(ASPECTS)
        if on_crop_change is not None:
            aspect.currentTextChanged.connect(lambda t: on_crop_change(t))
        rotate_btn = QPushButton("Rotate 90°")
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
        apply_btn.setEnabled(apply_enabled)
        if on_crop_apply is not None:
            apply_btn.clicked.connect(lambda: on_crop_apply())
        lay.addWidget(QLabel("Aspect ratio"))
        lay.addWidget(aspect)
        lay.addWidget(rotate_btn)
        flips = QHBoxLayout()
        flips.addWidget(flip_h)
        flips.addWidget(flip_v)
        lay.addLayout(flips)
        lay.addWidget(apply_btn)
        w.aspect_box = aspect
        w.rotate_btn = rotate_btn
        w.flip_h_btn = flip_h
        w.flip_v_btn = flip_v
        w.apply_btn = apply_btn

    elif stage.kind == "process":
        desc = _DESCRIPTIONS.get(stage.id)
        if desc:
            lay.addWidget(_desc_label(desc))
        box = QComboBox()
        box.addItems(_PROCESS_OPTIONS[stage.id])
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

    elif stage.kind == "auto":
        lay.addWidget(_desc_label(
            "Automatic background neutralization and white balance."
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
        black = ResetSlider(0)
        gamma = ResetSlider(100, minimum=10, maximum=300)  # 1.00
        white = ResetSlider(100)
        apply_btn = QPushButton("Apply Levels")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(
                (black.value() / 100.0, gamma.value() / 100.0, white.value() / 100.0)
            ))
        lay.addWidget(QLabel("Black point"))
        lay.addWidget(black)
        lay.addWidget(QLabel("Midtones (gamma)"))
        lay.addWidget(gamma)
        lay.addWidget(QLabel("White point"))
        lay.addWidget(white)
        lay.addWidget(apply_btn)
        w.black_slider = black
        w.gamma_slider = gamma
        w.white_slider = white
        w.apply_btn = apply_btn

    elif stage.kind == "saturation":
        lay.addWidget(_desc_label(
            "Drag left to mute colour, right to boost. Centre = no change."))
        slider = ResetSlider(50)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(50)
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Saturation (mute ← native → boost)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
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
