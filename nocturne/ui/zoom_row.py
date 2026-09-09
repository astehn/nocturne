"""The "Preview" zoom row — a readout plus − / + / Fit — shared by every dialog
that embeds a pan/zoom preview.

One copy, because there were two: `curves_dialog` and `starless_levels_dialog`
each built the same five widgets with the same 1.5 step and near-identical
comments, and the second copy had already drifted — its buttons drove the
`_ZoomPreview` model in all three CompareView modes, including Wipe, where the
picture is an `ImageView` that does not use that model at all. A control that
lies is worse than one that is missing.

Its own module rather than living in either dialog: `compare_view` imports
`_ZoomPreview` from `curves_dialog`, so a row defined in `compare_view` could
not be imported back into `curves_dialog` without a cycle.

A target is anything with `zoom_in()`, `zoom_out()`, `fit()`, `display_zoom()`
and a `viewChanged` signal — `_ZoomPreview` and `CompareView` both are.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton


class ZoomRow(QHBoxLayout):
    """Scroll to zoom, drag to pan — plus explicit buttons.

    The buttons exist because a trackpad gesture is not discoverable and a
    large mosaic is unusable without one. Sharper in Starless Levels than in
    Curves, because zooming there CHANGES WHAT THE CLIP MASK COVERS (whole
    frame at fit, visible region beyond it), so a user who scroll-zoomed by
    accident silently lost the whole-frame mask and needs a way back to Fit.
    """

    def __init__(self, target, caption: str = "Preview") -> None:
        super().__init__()
        self._target = target
        self.label = QLabel("1.0x")
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.clicked.connect(target.fit)
        self.in_btn = QPushButton("+")
        self.in_btn.clicked.connect(target.zoom_in)
        self.out_btn = QPushButton("−")
        self.out_btn.clicked.connect(target.zoom_out)

        self.addWidget(QLabel(caption))
        self.addStretch(1)
        self.addWidget(self.label)
        self.addWidget(self.out_btn)
        self.addWidget(self.in_btn)
        self.addWidget(self.fit_btn)

        target.viewChanged.connect(self.update_label)

    def update_label(self) -> None:
        self.label.setText(f"{self._target.display_zoom():.1f}x")
