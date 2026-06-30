from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ..core.crop import ASPECTS

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
}
EXTERNAL_FORMATS = ["Single 16-bit TIFF", "Two TIFFs: starless + stars"]
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS"]
_DESCRIPTIONS = {
    "background": "Removes light-pollution gradients so the sky background is even.",
    "noise_sharpen": "Reduces grain and recovers fine detail.",
}


def _desc_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def build_panel(
    stage,
    *,
    on_open=None,
    on_destination=None,
    on_apply=None,
    on_crop_apply=None,
    on_crop_change=None,
    on_export_external=None,
    on_export=None,
    apply_enabled: bool = True,
) -> QWidget:
    w = QWidget()
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

    elif stage.kind == "destination":
        ext = QPushButton("Continue in external software")
        ext.setMinimumHeight(40)
        fin = QPushButton("Finish here")
        fin.setMinimumHeight(40)
        fin.setObjectName("primary")
        if on_destination is not None:
            ext.clicked.connect(lambda: on_destination("external"))
            fin.clicked.connect(lambda: on_destination("in_app"))
        lay.addWidget(ext)
        lay.addWidget(_desc_label(
            "Runs the core steps, exports a 16-bit TIFF for Photoshop/PixInsight, then stops."
        ))
        lay.addSpacing(10)
        lay.addWidget(fin)
        lay.addWidget(_desc_label("Takes the image all the way to a share-ready file in the app."))
        w.external_btn = ext
        w.in_app_btn = fin

    elif stage.kind == "crop":
        lay.addWidget(_desc_label("Drag the box on the image to set the crop area."))
        aspect = QComboBox()
        aspect.addItems(ASPECTS)
        if on_crop_change is not None:
            aspect.currentTextChanged.connect(lambda t: on_crop_change(t))
        rotate_btn = QPushButton("Rotate 90°")
        w.rotate = 0

        def _cycle_rotate():
            w.rotate = (w.rotate + 90) % 360
            rotate_btn.setText(f"Rotate 90°  (now {w.rotate}°)")

        rotate_btn.clicked.connect(_cycle_rotate)
        flip_h = QPushButton("Flip H")
        flip_h.setCheckable(True)
        flip_v = QPushButton("Flip V")
        flip_v.setCheckable(True)
        margin = QSlider(Qt.Orientation.Horizontal)
        margin.setRange(0, 20)
        margin.setValue(0)
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
        lay.addWidget(QLabel("Extra margin"))
        lay.addWidget(margin)
        lay.addWidget(apply_btn)
        w.aspect_box = aspect
        w.rotate_btn = rotate_btn
        w.flip_h_btn = flip_h
        w.flip_v_btn = flip_v
        w.margin_slider = margin
        w.apply_btn = apply_btn

    elif stage.kind == "process":
        desc = _DESCRIPTIONS.get(stage.id)
        if desc:
            lay.addWidget(_desc_label(desc))
        box = QComboBox()
        box.addItems(_PROCESS_OPTIONS[stage.id])
        apply_btn = QPushButton(f"Apply {stage.label}")
        apply_btn.setObjectName("primary")
        note = _desc_label("Needs GraXpert — set its path in Settings.")
        note.setVisible(False)

        def _update_enabled(*_):
            if stage.id == "background":
                off = box.currentText() == "off"
                apply_btn.setEnabled(apply_enabled or off)
                note.setVisible(not apply_enabled and not off)
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
            "Automatic background neutralization and white balance — no settings."
        ))
        apply_btn = QPushButton("Apply Color")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(None))
        lay.addWidget(apply_btn)
        w.apply_btn = apply_btn

    elif stage.kind == "stretch":
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Aggressiveness (gentle → punchy)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.stretch_slider = slider
        w.apply_btn = apply_btn

    elif stage.kind == "saturation":
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(40)
        apply_btn = QPushButton("Apply Saturation")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Saturation"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.sat_slider = slider
        w.apply_btn = apply_btn

    elif stage.kind == "export_external":
        box = QComboBox()
        box.addItems(EXTERNAL_FORMATS)
        if not apply_enabled:
            box.model().item(1).setEnabled(False)  # split needs StarX
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export_external is not None:
            export_btn.clicked.connect(lambda: on_export_external(box.currentText()))
        lay.addWidget(QLabel("Output"))
        lay.addWidget(box)
        lay.addWidget(export_btn)
        if not apply_enabled:
            lay.addWidget(_desc_label("Split needs RC-Astro (set its path in Settings)."))
        w.fmt_box = box
        w.export_btn = export_btn

    elif stage.kind == "export":
        box = QComboBox()
        box.addItems(EXPORT_FORMATS)
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export is not None:
            export_btn.clicked.connect(lambda: on_export(box.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(box)
        lay.addWidget(export_btn)
        w.fmt_box = box
        w.export_btn = export_btn

    else:  # placeholder / unknown
        lay.addWidget(QLabel("Coming soon."))

    lay.addStretch(1)
    return w
