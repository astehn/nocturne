"""A click-only "More ▾" for the main toolbar.

Qt's own overflow is a chevron whose popup collapses the moment the pointer
leaves it — unusable on a trackpad, and it bit Andreas many times on the laptop
(TODO "Small screens", 2026-09-24). This replaces it: the toolbar is always made
to FIT, by moving tools into a menu that opens on click and stays open until a
choice or a click elsewhere.

What goes first is decided, not accidental (Andreas, 2026-09-26): tools leave
from the right end of the tools section inward — Batch, Save Recipe, Share… —
and the file actions, Auto Enhance, Undo/Redo/Reset, Before/After, Fit and 100%
never leave. Which tools are in the menu depends on the toolbar's width and
style only, never on the step or on what is greyed out, so nothing moves
between steps (piece 1's rule).
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton


_SLACK = 8


class ToolbarOverflow(QObject):
    def __init__(self, toolbar: QToolBar, overflow_order: list[QAction],
                 more_button: QToolButton, more_action: QAction,
                 budget, watch) -> None:
        """`overflow_order`: the tools that may leave, FIRST to leave first.
        `more_action`: what `toolbar.addWidget(more_button)` returned.
        `budget()`: the width the bar may use. NOT the toolbar's own width —
        QMainWindow gives a row's spare width to its LAST toolbar, so this one
        is only as wide as its contents, and hiding tools would shrink the
        budget with them. `watch`: the widget whose resize means re-measure."""
        super().__init__(toolbar)
        self._budget = budget
        self._tb = toolbar
        self._order = list(overflow_order)
        self._movable = set(self._order)
        self._all = list(toolbar.actions())     # the full bar, in order
        self._more = more_button
        self._more_act = more_action
        self._menu = QMenu(more_button)
        more_button.setMenu(self._menu)
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # Proxies in TOOLBAR order, so the menu reads like the bar it continues.
        self._proxy: dict[QAction, QAction] = {}
        for act in toolbar.actions():
            if act in self._movable:
                proxy = QAction(act.icon(), act.text(), self._menu)
                proxy.triggered.connect(lambda _c=False, a=act: a.trigger())
                act.changed.connect(lambda a=act: self._mirror(a))
                self._menu.addAction(proxy)
                self._proxy[act] = proxy
                self._mirror(act)
        self.hidden: list[QAction] = []
        self._pending = False
        self.prefer_text = True
        # Measures tools that are not on the bar. A child of the toolbar so the
        # "QToolBar QToolButton" rules reach it; never shown, never in the layout.
        self._probe = QToolButton(toolbar)
        self._probe.hide()
        toolbar.installEventFilter(self)
        watch.installEventFilter(self)
        toolbar.toolButtonStyleChanged.connect(self._on_style)
        for act in toolbar.actions():          # e.g. the tools warning appearing
            if act not in self._movable and act is not more_action and not act.isSeparator():
                act.visibleChanged.connect(self.schedule)
        self.relayout()

    # --- mirroring -------------------------------------------------------
    def _mirror(self, act: QAction) -> None:
        proxy = self._proxy[act]
        proxy.setEnabled(act.isEnabled())
        proxy.setCheckable(act.isCheckable())
        proxy.setChecked(act.isChecked())
        proxy.setText(act.text())
        proxy.setIcon(act.icon())
        proxy.setToolTip(act.toolTip())

    @property
    def all_actions(self) -> list[QAction]:
        """Every toolbar item in its original order — including tools that
        are in the More menu right now, which `toolbar.actions()` omits."""
        return list(self._all)

    def proxy_for(self, act: QAction) -> QAction:
        return self._proxy[act]

    # --- layout ------------------------------------------------------------
    def _on_style(self, style) -> None:
        self._more.setToolButtonStyle(style)
        self.schedule()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.StyleChange,
                            QEvent.Type.FontChange):
            self.schedule()
        return False

    def schedule(self) -> None:
        if not self._pending:
            self._pending = True
            # Tied to this object: a relayout queued by a window being closed
            # must not run against its deleted actions.
            QTimer.singleShot(0, self, self.relayout)

    def set_prefer_text(self, prefer: bool) -> None:
        """Settings ▸ General ▸ Toolbar. With text preferred, text is shown
        whenever the never-leave set fits with it; below that width the bar
        drops to icons by itself (Andreas, 2026-09-26) — never cutting a tool."""
        self.prefer_text = prefer
        self.schedule()

    def _is_text(self) -> bool:
        return self._tb.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonIconOnly

    def _width(self, act, text: bool) -> int:
        """`act`'s width with text or icons only. A button on the bar in that
        style is measured directly; anything else — a tool in More, or the
        other style — is measured on `_probe`, a never-shown button inside the
        toolbar that the same stylesheet rules reach. Never remembered: a
        cache wiped by a font change once priced every tool in More at 0 px,
        and the bar put them all back for a few frames and cut Undo…100%."""
        style = (Qt.ToolButtonStyle.ToolButtonTextUnderIcon if text
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        if act is self._more_act:
            src_text, src_icon, w = self._more.text(), self._more.icon(), self._more
        else:
            src_text, src_icon = act.text(), act.icon()
            w = self._tb.widgetForAction(act)
            if act.isSeparator() or (w is not None and not isinstance(w, QToolButton)):
                return 0 if w is None else max(0, w.sizeHint().width())   # separators, the spacer
        if w is not None and w.isVisible() and self._tb.toolButtonStyle() == style:
            return max(0, w.sizeHint().width())
        p = self._probe
        p.setToolButtonStyle(style)
        p.setIconSize(self._tb.iconSize())
        p.setText(src_text)
        p.setIcon(src_icon)
        return max(0, p.sizeHint().width())

    def _needed(self, shown: list[QAction], text: bool) -> int:
        """Width the shown items take, with separators collapsed exactly as
        `_apply` will collapse them."""
        spacing = self._tb.layout().spacing()
        items = self._collapse(shown)
        return sum(self._width(a, text) for a in items) + spacing * max(0, len(items) - 1)

    def _collapse(self, shown: list[QAction]) -> list[QAction]:
        """Drop separators that would sit first, last, or next to another."""
        out: list[QAction] = []
        for a in shown:
            if a.isSeparator() and (not out or out[-1].isSeparator()):
                continue
            out.append(a)
        while out and out[-1].isSeparator():
            out.pop()
        return out

    def _candidates(self) -> list[QAction]:
        """Every item that would be on the bar, in order: the movable tools and
        the separators always count; anything else counts while it is visible.
        The expanding spacer is a widget with no width of its own."""
        acts = []
        for a in self._all:
            if a is self._more_act:
                continue
            if a in self._movable or a.isSeparator() or a.isVisible():
                acts.append(a)
        return acts

    def _plan(self, all_items, budget: int, text: bool):
        """(hidden tools, fits) for one style."""
        more_w = self._width(self._more_act, text) + self._tb.layout().spacing()
        if self._needed(all_items, text) <= budget:
            return [], True
        hidden: list[QAction] = []
        for act in self._order:
            hidden.append(act)
            if self._needed([a for a in all_items if a not in hidden], text) + more_w <= budget:
                return hidden, True
        return hidden, False

    def relayout(self) -> None:
        self._pending = False
        if not shiboken6.isValid(self._tb):
            return
        all_items = self._candidates()
        # The probe takes the toolbar's CURRENT stylesheet (iconsOnly etc.).
        self._probe.style().unpolish(self._probe)
        self._probe.style().polish(self._probe)
        m = self._tb.contentsMargins()
        lay = self._tb.layout().contentsMargins()
        # A few px of slack: an estimate a hair short would let Qt push the
        # last item off the bar.
        budget = self._budget() - m.left() - m.right() - lay.left() - lay.right() - _SLACK
        want_text = self.prefer_text and self._plan(all_items, budget, True)[1]
        style = (Qt.ToolButtonStyle.ToolButtonTextUnderIcon if want_text
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        if self._tb.toolButtonStyle() != style:
            self._tb.setToolButtonStyle(style)   # re-enters via toolButtonStyleChanged
            return
        hidden, _fits = self._plan(all_items, budget, want_text)
        self._apply(all_items, hidden)

    def _next_on_bar(self, act: QAction) -> QAction | None:
        """The first item after `act`, in the bar's original order, that is on
        the bar now — where `act` goes back in."""
        on_bar = set(self._tb.actions())
        after = self._all[self._all.index(act) + 1:]
        return next((a for a in after if a in on_bar), None)

    def _apply(self, all_items: list[QAction], hidden: list[QAction]) -> None:
        self.hidden = hidden
        hide = set(hidden)
        shown = [a for a in all_items if a not in hide]
        keep = set(self._collapse(shown))
        # Tools that leave are REMOVED from the bar, not hidden: QAction ties
        # enabled to visible, so a hidden tool is a disabled one — its menu
        # entry went grey and did nothing. Removed, it stays live.
        on_bar = set(self._tb.actions())
        for a in self._all:
            if a in self._movable:
                if a in hide and a in on_bar:
                    self._tb.removeAction(a)
                elif a not in hide and a not in on_bar:
                    self._tb.insertAction(self._next_on_bar(a), a)
                on_bar = set(self._tb.actions())
            elif a.isSeparator():
                a.setVisible(a in keep)
        for act, proxy in self._proxy.items():
            proxy.setVisible(act in hide)
        self._more_act.setVisible(bool(hidden))
        if not hidden and self._menu.isVisible():
            self._menu.hide()     # the window grew under an open menu: nothing left in it
