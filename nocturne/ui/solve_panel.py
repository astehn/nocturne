"""Collapsible right-hand panel exposing the plate-solve result and the
annotation overlay's layer toggles / density. Standalone widget -- Task 8
wires it into main_window (creating it, calling set_state/set_result, and
persisting layers()/density() into Settings on change)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from ..core.annotate import (
    compass_angles, format_dec_dms, format_orientation, format_ra_hms,
    is_mirrored,
)
from ..settings import DEFAULT_ANNOTATION_DENSITY, DEFAULT_ANNOTATION_LAYERS

_SOLVER_NAME = "ASTAP"   # the only plate-solver Nocturne integrates

STATE_LABELS = {
    "not_solved": "Not solved",
    "solving": "Solving…",
    "solved": "Solved",
    "cached": "Cached",
    "stale": "Needs re-solve",
}

_LAYER_LABELS = [   # (key, checkbox label) -- order drives the checkbox layout
    ("objects", "Objects"),
    ("stars", "Named stars"),
    ("grid", "RA/Dec grid"),
    ("compass", "Compass"),
    ("scale", "Scale bar"),
    ("by_type", "Colour by type"),
]

_DENSITY_LABELS = [   # (key, combo label)
    ("minimal", "Minimal"),
    ("balanced", "Balanced"),
    ("all", "All"),
]


class SolvePanel(QWidget):
    """Header row + collapsible body: result card, layer checkboxes, density
    selector, action row. Deliberately holds no solving logic of its own --
    it only reports layers()/density() and asks for a (re-)solve via
    resolveRequested; the caller drives set_state/set_result."""

    layersChanged = Signal(dict)
    densityChanged = Signal(str)
    resolveRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("solvePanel")
        self._state = "not_solved"
        self._layers = dict(DEFAULT_ANNOTATION_LAYERS)
        self._density = DEFAULT_ANNOTATION_DENSITY
        self._expanded = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.header_btn = QPushButton()
        self.header_btn.setObjectName("solveHeader")
        self.header_btn.setFlat(True)
        self.header_btn.clicked.connect(self._toggle_expanded)
        outer.addWidget(self.header_btn)

        self.content = QWidget()
        self.content.setObjectName("stepCard")
        content_lay = QVBoxLayout(self.content)

        self.result_label = QLabel("")
        self.result_label.setObjectName("solveResultCard")
        self.result_label.setWordWrap(True)
        content_lay.addWidget(self.result_label)

        self.layer_checks: dict[str, QCheckBox] = {}
        for key, label in _LAYER_LABELS:
            box = QCheckBox(label)
            box.setChecked(self._layers[key])
            box.toggled.connect(lambda checked, k=key: self._on_layer_toggled(k, checked))
            content_lay.addWidget(box)
            self.layer_checks[key] = box

        density_row = QHBoxLayout()
        density_row.addWidget(QLabel("Density"))
        self.density_box = QComboBox()
        for key, label in _DENSITY_LABELS:
            self.density_box.addItem(label, key)
        self.density_box.setCurrentIndex(
            [k for k, _ in _DENSITY_LABELS].index(self._density))
        self.density_box.currentIndexChanged.connect(self._on_density_changed)
        density_row.addWidget(self.density_box)
        content_lay.addLayout(density_row)

        action_row = QHBoxLayout()
        self.resolve_btn = QPushButton()
        self.resolve_btn.setObjectName("primary")
        self.resolve_btn.clicked.connect(lambda: self.resolveRequested.emit())
        action_row.addWidget(self.resolve_btn)
        content_lay.addLayout(action_row)

        # No "Objects in field" button here. The list appears on the canvas by
        # itself once a solve lands, and follows the Annotations toggle -- one
        # idea, one control. A button in this column was a second switch for
        # something the pill already governs, and it put the control a long way
        # from the thing it controlled. The list's own title carries the count.

        outer.addWidget(self.content)

        self._update_header()
        self._update_resolve_button()
        self.content.setVisible(self._expanded)

    # --- collapse / expand --------------------------------------------

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.content.setVisible(self._expanded)
        self._update_header()

    def _update_header(self) -> None:
        label = STATE_LABELS.get(self._state, self._state)
        arrow = "▾" if self._expanded else "▸"
        self.header_btn.setText(f"Plate solve · {label} {arrow}")

    # --- layers / density ------------------------------------------------

    def _on_layer_toggled(self, key: str, checked: bool) -> None:
        self._layers[key] = checked
        self.layersChanged.emit(dict(self._layers))   # complete dict, not a delta

    def layers(self) -> dict:
        return dict(self._layers)

    def set_layers(self, layers: dict) -> None:
        """Programmatic hydration from persisted settings (called once at
        startup, and whenever main_window needs to re-sync the panel to a
        settings value it didn't originate). Deliberately does NOT emit
        layersChanged -- that signal means "the user just changed something,
        rebuild the overlay", which would be redundant/wrong immediately
        after applying the very state the overlay is about to be built from."""
        self._layers = dict(layers)
        for key, box in self.layer_checks.items():
            box.blockSignals(True)
            box.setChecked(self._layers.get(key, False))
            box.blockSignals(False)

    def _on_density_changed(self, index: int) -> None:
        self._density = self.density_box.itemData(index)
        self.densityChanged.emit(self._density)

    def density(self) -> str:
        return self._density

    def set_density(self, density: str) -> None:
        """Programmatic hydration, mirrors set_layers -- no densityChanged."""
        self._density = density
        keys = [k for k, _ in _DENSITY_LABELS]
        idx = keys.index(density) if density in keys else keys.index(DEFAULT_ANNOTATION_DENSITY)
        self.density_box.blockSignals(True)
        self.density_box.setCurrentIndex(idx)
        self.density_box.blockSignals(False)

    # --- state / result ---------------------------------------------------

    def _update_resolve_button(self) -> None:
        if self._state == "solving":
            self.resolve_btn.setText("Solving…")
            self.resolve_btn.setEnabled(False)
        elif self._state in ("solved", "cached", "stale"):
            self.resolve_btn.setText("Re-solve")
            self.resolve_btn.setEnabled(True)
        else:
            self.resolve_btn.setText("Solve")
            self.resolve_btn.setEnabled(True)

    def set_state(self, state: str) -> None:
        """`state` is one of not_solved / solving / solved / cached / stale;
        drives both the header badge and the action button's label/enabled."""
        self._state = state
        self._update_header()
        self._update_resolve_button()

    def set_result(self, res, target: str, shape, pixscale: float,
                   elapsed: float, cached: bool, scale_source: str = "header") -> None:
        """Fills the result card. `res` is a nocturne.tools.astap.SolveResult
        (or any object exposing center_ra_deg/center_dec_deg/wcs); `shape` is
        (h, w) in pixels; `pixscale` is arcsec/px. Deliberately carries NO
        quality/confidence field -- the ASTAP parser discards match count,
        star count and residual, so there is no metric to show, and a
        fabricated score would be worse than nothing."""
        lines = []
        if target:
            lines.append(target)

        lines.append(f"{format_ra_hms(res.center_ra_deg)}   "
                      f"{format_dec_dms(res.center_dec_deg)}")

        h, w = shape
        fov_w_deg = w * pixscale / 3600.0
        fov_h_deg = h * pixscale / 3600.0
        orientation = ""
        wcs = getattr(res, "wcs", None)
        if wcs is not None:
            north, _east = compass_angles(wcs, shape)
            # Parity is NOT reported. is_mirrored() derives from the same screen
            # convention as the projection, so it inverted when FITS_Y_DOWN was
            # corrected (2026-07-31) — and it claimed "mirrored" on a Seestar
            # frame the user confirmed matches Stellarium's view, i.e. not
            # mirrored. On the one panel whose job is to say whether a solve can
            # be trusted, an unverified claim is worse than a missing field.
            # Restore it only with ground truth from a frame of known handedness.
            orientation = "  ·  " + format_orientation(north)
        lines.append(f"{fov_w_deg:.1f}° × {fov_h_deg:.1f}°  ·  "
                     f"{pixscale:.2f}″/px{orientation}")

        cache_phrase = "reused from cache" if cached else "freshly solved"
        solver_line = f"{_SOLVER_NAME} · solved in {elapsed:.1f} s · {cache_phrase}"
        if scale_source == "profile":
            # The file carried no optics, so the scale hint came from the Seestar
            # profile rather than the header. Say so: a solve that leaned on an
            # assumed scale is still a good solve, but the user should know the
            # assumption was made — especially on data from another instrument.
            solver_line += " · scale assumed from Seestar profile"
        lines.append(solver_line)

        self.result_label.setText("\n".join(lines))
