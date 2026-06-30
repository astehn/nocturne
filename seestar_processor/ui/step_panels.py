from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QLabel, QPushButton, QRadioButton, QSlider,
    QVBoxLayout, QWidget,
)

_PROCESS_OPTIONS = {
    "background": ["off", "light", "strong"],
    "noise_sharpen": ["light", "medium", "strong"],
}
STRETCH_PRESETS = ["gentle", "balanced", "punchy"]
EXTERNAL_FORMATS = ["Single 16-bit TIFF", "Two TIFFs: starless + stars"]
EXPORT_FORMATS = ["TIFF (16-bit)", "PNG", "FITS"]


def build_panel(
    stage,
    *,
    on_open=None,
    on_destination=None,
    on_apply=None,
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
        meta = QLabel("Open a stacked Seestar FITS to begin.")
        meta.setWordWrap(True)
        lay.addWidget(meta)
        w.meta_label = meta

    elif stage.kind == "destination":
        external = QRadioButton("Continue in external software")
        in_app = QRadioButton("Finish here")
        in_app.setChecked(True)
        group = QButtonGroup(w)
        group.addButton(external)
        group.addButton(in_app)
        if on_destination is not None:
            external.toggled.connect(
                lambda on: on and on_destination("external")
            )
            in_app.toggled.connect(lambda on: on and on_destination("in_app"))
        lay.addWidget(external)
        lay.addWidget(in_app)
        w.external_radio = external
        w.in_app_radio = in_app

    elif stage.kind == "crop":
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 20)
        slider.setValue(0)
        apply_btn = QPushButton("Apply Crop")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(slider.value() / 100.0))
        lay.addWidget(QLabel("Extra margin (auto-detects the border)"))
        lay.addWidget(slider)
        lay.addWidget(apply_btn)
        w.margin_slider = slider
        w.apply_btn = apply_btn

    elif stage.kind == "process":
        box = QComboBox()
        box.addItems(_PROCESS_OPTIONS[stage.id])
        apply_btn = QPushButton(f"Apply {stage.label}")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(box.currentText()))
        lay.addWidget(QLabel("Strength"))
        lay.addWidget(box)
        lay.addWidget(apply_btn)
        w.option_box = box
        w.apply_btn = apply_btn

    elif stage.kind == "auto":
        lay.addWidget(QLabel("Automatic — no settings."))
        apply_btn = QPushButton("Apply Color")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(None))
        lay.addWidget(apply_btn)
        w.apply_btn = apply_btn

    elif stage.kind == "stretch":
        box = QComboBox()
        box.addItems(STRETCH_PRESETS)
        box.setCurrentText("balanced")
        apply_btn = QPushButton("Apply Stretch")
        apply_btn.setObjectName("primary")
        apply_btn.setEnabled(apply_enabled)
        if on_apply is not None:
            apply_btn.clicked.connect(lambda: on_apply(box.currentText()))
        lay.addWidget(QLabel("Aggressiveness"))
        lay.addWidget(box)
        lay.addWidget(apply_btn)
        w.option_box = box
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
            # split needs StarX; disable the second item via a model flag
            box.model().item(1).setEnabled(False)
        export_btn = QPushButton("Export…")
        export_btn.setObjectName("primary")
        if on_export_external is not None:
            export_btn.clicked.connect(lambda: on_export_external(box.currentText()))
        lay.addWidget(QLabel("Output"))
        lay.addWidget(box)
        lay.addWidget(export_btn)
        if not apply_enabled:
            lay.addWidget(QLabel("Split needs RC-Astro (set its path in Settings)."))
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
