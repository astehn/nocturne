"""The preset browser: pick a saved look for this picture, or tidy the library.

One QListWidget in two view modes rather than the start page's painted cards:
it brings selection, keyboard, disabled items and both views for free, and a
stylesheet gives it the start page's dark rounded look.

A preset made on dual-band data is shown but cannot be chosen for a broadband
picture — hiding it would make a saved preset look lost.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

from ..user_presets import (SORT_KEYS, Preset, PresetError, can_apply, filter_presets,
                            saved_label, sort_presets)
from . import theme
from .welcome import _card_pixmap

# Available screen height below which the browser opens as a list. Measured on
# this Mac: 1280×800 leaves ~775 px available, 1440×900 ~875 (see the commit).
COMPACT_BELOW_HEIGHT = 860

ICON_W, ICON_H = 200, 133
DETAILS_W = 240
_CELL_PAD, _CELL_TEXT = 28, 80       # card padding round the icon; three text lines under it
_SORT_LABELS = {"created": "Newest first", "last_used": "Last used",
                "name": "Name", "target": "Target"}
_DATA_WORDS = {"dualband": "dual-band", "broadband": "broadband"}
_EMPTY = ("No presets yet. Process a picture through to Enhancements, then press "
          "Save as Preset… — it keeps every step after the crop, ready for similar pictures.")
_NO_MATCH = "No preset matches."
_NOTHING_SELECTED = "Select a preset to see what it does."
_BROADBAND_MARK = " · made on broadband data"

_STYLE = f"""
QListWidget#presetItems {{ background: {theme.BG_1}; padding: 8px; }}
QListWidget#presetItems::item {{ background: {theme.BG_0}; color: {theme.TEXT};
    border: 1px solid #2a2c31; border-radius: 10px; padding: 6px; margin: 4px; }}
QListWidget#presetItems::item:hover {{ border-color: {theme.BORDER}; }}
QListWidget#presetItems::item:selected {{ border: 1px solid {theme.ACCENT};
    background: {theme.BG_2}; color: {theme.TEXT}; }}
QListWidget#presetItems::item:disabled {{ color: {theme.TEXT_FAINT}; }}
QToolButton#viewToggle {{ padding: 3px 10px; border: 1px solid transparent; border-radius: 5px; }}
QToolButton#viewToggle:checked {{ background: {theme.BG_3}; border-color: {theme.ACCENT}; }}
"""


def _steps_text(n: int) -> str:
    return f"{n} step" if n == 1 else f"{n} steps"


class PresetBrowser(QDialog):
    def __init__(self, library, *, picture_type: str, settings,
                 on_settings_changed: Callable[[], None] | None = None,
                 current_id: str | None = None, screen_height: int | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Presets")
        self.setStyleSheet(_STYLE)
        self._library = library
        self._picture_type = picture_type
        self._settings = settings
        self._on_settings_changed = on_settings_changed
        self._current_id = current_id
        self._chosen: Preset | None = None
        self._shown: dict[str, Preset] = {}
        self._icons: dict[tuple, QIcon] = {}
        self.cleared = False
        self.deleted_current = False

        if screen_height is None:
            screen = QApplication.primaryScreen()
            screen_height = screen.availableGeometry().height() if screen else 10_000
        self._screen_height = screen_height
        view = settings.preset_view
        if view not in ("grid", "list"):
            view = "list" if screen_height < COMPACT_BELOW_HEIGHT else "grid"
        self._view = view

        # --- top bar: search, filter, sort, view ---
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or target")
        self.search.setClearButtonEnabled(True)
        self.type_filter = QCheckBox("Only presets for this kind of data")
        self.sort_box = QComboBox()
        for key in SORT_KEYS:
            self.sort_box.addItem(_SORT_LABELS[key], key)
        i = self.sort_box.findData(settings.preset_sort)
        self.sort_box.setCurrentIndex(max(i, 0))
        self.grid_btn, self.list_btn = QToolButton(), QToolButton()
        for btn, text, tip in ((self.grid_btn, "Grid", "Show previews"),
                               (self.list_btn, "List", "A compact list without previews")):
            btn.setText(text)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setObjectName("viewToggle")
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.grid_btn)
        group.addButton(self.list_btn)
        (self.grid_btn if view == "grid" else self.list_btn).setChecked(True)

        # Two rows: in one, the compact view's 560 px crushed the search box to "…".
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addSpacing(12)
        top.addWidget(self.grid_btn)
        top.addWidget(self.list_btn)
        second = QHBoxLayout()
        second.addWidget(self.type_filter)
        second.addStretch(1)
        second.addWidget(QLabel("Sort"))
        second.addWidget(self.sort_box)

        # --- the list ---
        self.items = QListWidget()
        self.items.setObjectName("presetItems")
        self.items.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.items.setMovement(QListWidget.Movement.Static)
        self.items.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.items.setUniformItemSizes(True)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("emptyNote")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()

        # --- details ---
        self.details = QWidget()
        self.details_title = QLabel()
        self.details_title.setWordWrap(True)
        f = self.details_title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.details_title.setFont(f)
        self.details_saved = QLabel()
        self.details_saved.setWordWrap(True)
        self.details_meta = QLabel()
        self.details_meta.setWordWrap(True)
        self.details_meta.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self.details_note = QLabel()        # why it cannot be chosen, or the broadband caveat
        self.details_note.setWordWrap(True)
        self.details_note.setStyleSheet(f"color: {theme.WARNING};")
        self.details_steps = QListWidget()
        self.details_steps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.details_steps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.details_left_out = QLabel()
        self.details_left_out.setWordWrap(True)
        self.details_left_out.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete…")
        manage = QHBoxLayout()
        manage.addWidget(self.rename_btn)
        manage.addWidget(self.delete_btn)
        manage.addStretch(1)
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        for w in (self.details_title, self.details_saved, self.details_meta, self.details_note):
            dl.addWidget(w)
        dl.addWidget(self.details_steps, 1)
        dl.addWidget(self.details_left_out)
        dl.addLayout(manage)

        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body.addWidget(self.items, 1)
        self.body.addWidget(self.empty_label, 1)
        self.body.addWidget(self.details)

        # --- bottom ---
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {theme.WARNING};")
        self.warning.hide()
        self.no_preset_btn = QPushButton("Use no preset")
        self.no_preset_btn.setVisible(current_id is not None)
        cancel = QPushButton("Cancel")
        self.choose_btn = QPushButton("Choose")
        self.choose_btn.setObjectName("primary")
        self.choose_btn.setDefault(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.no_preset_btn)
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        bottom.addWidget(self.choose_btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(second)
        lay.addLayout(self.body, 1)
        lay.addWidget(self.warning)
        lay.addLayout(bottom)

        self.search.textChanged.connect(lambda _t: self._reload())
        self.type_filter.toggled.connect(lambda _c: self._reload())
        self.sort_box.currentIndexChanged.connect(self._on_sort)
        self.grid_btn.clicked.connect(lambda: self._set_view("grid"))
        self.list_btn.clicked.connect(lambda: self._set_view("list"))
        self.items.currentItemChanged.connect(lambda *_: self._sync_selection())
        self.items.itemDoubleClicked.connect(lambda _i: self._choose())
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn.clicked.connect(self._delete)
        self.choose_btn.clicked.connect(self._choose)
        cancel.clicked.connect(self.reject)
        self.no_preset_btn.clicked.connect(self._use_none)

        self._apply_view_mode()
        self._reload(select_id=current_id)
        self._size_for_view()

    # --- public ---
    def chosen(self) -> Preset | None:
        return self._chosen

    # --- seams for tests ---
    def _ask_name(self, current: str) -> str | None:
        text, ok = QInputDialog.getText(self, "Rename Preset", "Name",
                                        QLineEdit.EchoMode.Normal, current)
        return text if ok else None

    def _ask_delete(self, p: Preset) -> bool:
        resp = QMessageBox.question(
            self, "Delete Preset", f"Delete the preset “{p.name}”? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return resp == QMessageBox.StandardButton.Yes

    # --- view ---
    def _set_view(self, view: str) -> None:
        if view == self._view:
            return
        self._view = view
        self._settings.preset_view = view
        self._notify()
        self._apply_view_mode()
        self._reload()
        self._size_for_view()

    def _apply_view_mode(self) -> None:
        grid = self._view == "grid"
        self.items.setViewMode(QListWidget.ViewMode.IconMode if grid
                               else QListWidget.ViewMode.ListMode)
        # setViewMode resets these, so they are set after it.
        self.items.setMovement(QListWidget.Movement.Static)
        self.items.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.items.setWrapping(grid)
        self.items.setWordWrap(grid)
        self.items.setIconSize(QSize(ICON_W, ICON_H) if grid else QSize(0, 0))
        # A fixed cell, or IconMode sizes columns from the longest text and wraps early.
        self.items.setGridSize(QSize(ICON_W + _CELL_PAD, ICON_H + _CELL_TEXT) if grid
                               else QSize())
        self.items.setSpacing(4 if grid else 0)
        # Compact: the details fold under the list, so the dialog fits 1280×800.
        if grid:
            self.body.setDirection(QBoxLayout.Direction.LeftToRight)
            self.details.setFixedWidth(DETAILS_W)
            self.details_steps.setMaximumHeight(16_777_215)
        else:
            self.body.setDirection(QBoxLayout.Direction.TopToBottom)
            self.details.setMinimumWidth(0)
            self.details.setMaximumWidth(16_777_215)
            self.details_steps.setMaximumHeight(120)

    def _size_for_view(self) -> None:
        avail = self._screen_height - 60       # title bar and a margin
        if self._view == "grid":
            # Three cells plus the list's padding and scroll bar: at +72 it wrapped to two.
            self.resize(3 * (ICON_W + _CELL_PAD) + DETAILS_W + 110, min(660, avail))
        else:
            self.resize(560, min(700, avail))

    # --- data ---
    def _on_sort(self, _index: int) -> None:
        self._settings.preset_sort = self.sort_box.currentData()
        self._notify()
        self._reload()

    def _notify(self) -> None:
        if self._on_settings_changed is not None:
            self._on_settings_changed()

    def _icon(self, p: Preset) -> QIcon:
        dpr = self.devicePixelRatioF()
        key = (p.id, p.created, p.has_preview, dpr)
        if key not in self._icons:
            jpeg = None
            if p.has_preview:
                try:
                    with open(p.preview_path, "rb") as fh:
                        jpeg = fh.read()
                except OSError:
                    jpeg = None
            try:
                pm = _card_pixmap(jpeg, dpr, (ICON_W, ICON_H))
            except Exception:
                pm = _card_pixmap(None, dpr, (ICON_W, ICON_H))
            self._icons[key] = QIcon(pm)
        return self._icons[key]

    def _reload(self, select_id: str | None = None) -> None:
        if select_id is None:
            cur = self.items.currentItem()
            select_id = cur.data(Qt.ItemDataRole.UserRole) if cur is not None else None
        every = self._library.list()
        data_type = self._picture_type if self.type_filter.isChecked() else None
        shown = sort_presets(filter_presets(every, self.search.text(), data_type),
                             self.sort_box.currentData())
        grid = self._view == "grid"
        self.items.blockSignals(True)
        self.items.clear()
        self._shown = {}
        selected = None
        for p in shown:
            ok, note = can_apply(p, self._picture_type)
            label = saved_label(p)
            text = (f"{p.name}\n{label}" if grid
                    else f"{p.name} — {label} · {_steps_text(p.step_count)}")
            if ok and note:
                # Its own line in a card: appended, it wrapped and the cell clipped it.
                text += "\n" + _BROADBAND_MARK[3:] if grid else _BROADBAND_MARK
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            if grid:
                item.setIcon(self._icon(p))
                # Every card one size, three lines high: from its own text, a
                # two-line card set the size and clipped a three-line one.
                item.setSizeHint(QSize(ICON_W + _CELL_PAD - 8, ICON_H + _CELL_TEXT - 8))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            if note:
                item.setToolTip(note)
            if not ok:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.items.addItem(item)
            self._shown[p.id] = p
            if p.id == select_id:
                selected = item
        if selected is not None:
            self.items.setCurrentItem(selected)
        self.items.blockSignals(False)

        has_any, has_shown = bool(every), bool(shown)
        self.empty_label.setText(_NO_MATCH if has_any else _EMPTY)
        self.empty_label.setVisible(not has_shown)
        self.items.setVisible(has_shown)
        self.details.setVisible(has_shown)
        for w in (self.search, self.type_filter, self.sort_box, self.grid_btn, self.list_btn):
            w.setEnabled(has_any)
        self._sync_selection()

    def _current(self) -> tuple[Preset | None, bool]:
        """The selected preset and whether it may be chosen for this picture."""
        item = self.items.currentItem()
        if item is None or self.items.isHidden():
            return None, False
        p = self._shown.get(item.data(Qt.ItemDataRole.UserRole))
        return p, bool(p is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled)

    def _sync_selection(self) -> None:
        p, ok = self._current()
        self.choose_btn.setEnabled(ok)
        self.rename_btn.setEnabled(p is not None)
        self.delete_btn.setEnabled(p is not None)
        self.details_steps.clear()
        if p is None:
            self.details_title.setText(_NOTHING_SELECTED)
            for w in (self.details_saved, self.details_meta, self.details_note,
                      self.details_left_out):
                w.setText("")
                w.hide()
            self.details_steps.hide()
            return
        self.details_title.setText(p.name)
        self.details_saved.setText(saved_label(p))
        meta = f"{_DATA_WORDS.get(p.data_type, 'unknown')} data · {_steps_text(p.step_count)}"
        if p.app:
            meta += f" · Nocturne {p.app}"
        self.details_meta.setText(meta)
        note = can_apply(p, self._picture_type)[1]
        self.details_note.setText(note)
        self.details_steps.addItems(p.step_names())
        self.details_left_out.setText(
            f"Not included when saved: {', '.join(p.left_out)}" if p.left_out else "")
        self.details_saved.show()
        self.details_meta.show()
        self.details_steps.show()
        self.details_note.setVisible(bool(note))
        self.details_left_out.setVisible(bool(p.left_out))

    # --- actions ---
    def _say(self, text: str) -> None:
        self.warning.setText(text)
        self.warning.setVisible(bool(text))

    def _rename(self) -> None:
        p, _ok = self._current()
        if p is None:
            return
        name = self._ask_name(p.name)
        if name is None or name.strip() == p.name:
            return
        try:
            self._library.rename(p, name)
        except PresetError as exc:
            msg = str(exc)
            self._say(f"Not renamed: {msg[:1].lower()}{msg[1:]}.")
        except ValueError as exc:
            # Not a PresetError: the manifest went bad between listing and rewrite
            # (json.load's JSONDecodeError).
            self._say(f"Could not rename “{p.name}” — its preset file is damaged ({exc}).")
        except OSError as exc:
            self._say(f"Could not rename “{p.name}” — another program may be using it "
                      f"({exc.strerror or exc}).")
        else:
            self._say("")
        self._reload(select_id=p.id)

    def _delete(self) -> None:
        p, _ok = self._current()
        if p is None or not self._ask_delete(p):
            return
        try:
            self._library.delete(p)
        except (OSError, ValueError) as exc:
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
            self._say(f"Could not delete “{p.name}” — another program may be using it "
                      f"({reason}).")
            self._reload(select_id=p.id)
            return
        self._say("")
        if p.id == self._current_id:
            self.deleted_current = True
        self._reload()

    def _choose(self) -> None:
        p, ok = self._current()
        if not ok:
            return
        self._chosen = p
        self.cleared = False
        self.accept()

    def _use_none(self) -> None:
        self._chosen = None
        self.cleared = True
        self.accept()
