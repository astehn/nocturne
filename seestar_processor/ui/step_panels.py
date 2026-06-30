from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

OPTIONS = ["Small", "Medium", "Large"]


def build_panel(
    stage,
    *,
    on_open=None,
    on_apply=None,
    on_export=None,
    apply_enabled: bool = True,
    option_default: str = "Medium",
) -> QWidget:
    w = QWidget()
    w.panel_kind = stage.kind
    lay = QVBoxLayout(w)

    title = QLabel(stage.label)
    title.setObjectName("stageTitle")
    lay.addWidget(title)

    if stage.kind == "load":
        btn = QPushButton("Open FITS…")
        if on_open is not None:
            btn.clicked.connect(lambda: on_open())
        lay.addWidget(btn)
        lay.addWidget(QLabel("Open a stacked Seestar FITS to begin."))

    elif stage.kind in ("process", "stretch"):
        box = QComboBox()
        box.addItems(OPTIONS)
        box.setCurrentText(option_default)
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

    elif stage.kind == "export":
        fmt = QComboBox()
        fmt.addItems(["TIFF (16-bit)", "JPEG"])
        btn = QPushButton("Export…")
        btn.setObjectName("primary")
        if on_export is not None:
            btn.clicked.connect(lambda: on_export(fmt.currentText()))
        lay.addWidget(QLabel("Format"))
        lay.addWidget(fmt)
        lay.addWidget(btn)
        w.format_box = fmt

    else:  # placeholder
        lay.addWidget(QLabel("Coming soon — not available in this version."))

    lay.addStretch(1)
    return w
