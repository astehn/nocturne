from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView,
)

from .annotation_pill import AnnotationPill
from .object_list_panel import ObjectListPanel
from .readout_pill import ReadoutPill
from .theme import BG_0, BG_1
from .zoom_pill import ZoomPill

_ACCENT = QColor("#2dd4bf")
_HANDLES = ("tl", "tr", "bl", "br", "t", "b", "l", "r")


class _Divider(QGraphicsRectItem):
    """Vertical Before/After divider; movable horizontally, reports its x."""

    def __init__(self, height: float, on_move) -> None:
        super().__init__(-1.5, 0, 3, height)
        self._on_move = on_move
        self._max_x = 1.0
        self.setBrush(QBrush(_ACCENT))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setZValue(6)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def set_max_x(self, max_x: float) -> None:
        self._max_x = max_x

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionChange:
            x = min(max(0.0, value.x()), self._max_x)
            value.setX(x)
            value.setY(0.0)  # constrain to horizontal movement
            self._on_move(x)
            return value
        return super().itemChange(change, value)


class _Handle(QGraphicsRectItem):
    """Constant-screen-size corner handle that resizes the crop box on drag."""

    def __init__(self, corner: str, overlay) -> None:
        super().__init__(-6, -6, 12, 12)
        self._corner = corner
        self._overlay = overlay
        self.setBrush(QBrush(_ACCENT))
        self.setPen(QPen(QColor("#06201c")))
        self.setZValue(20)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations, True)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self._overlay._resize_to(self._corner, event.scenePos())


class _Body(QGraphicsRectItem):
    """Movable crop rectangle; reports geometry changes to the overlay."""

    def __init__(self, overlay) -> None:
        super().__init__()
        self._overlay = overlay
        pen = QPen(_ACCENT, 0, Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setZValue(10)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionChange:
            value = self._overlay._clamp_body_pos(self, value)
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self._overlay._geometry_changed()
        return super().itemChange(change, value)


class ImageView(QGraphicsView):
    cropBoxChanged = Signal(int, int, int, int)
    cropBoxShown = Signal()
    cropDismissRequested = Signal()
    hovered = Signal(int, int, str)     # image x, image y, "main" | "compare"
    hoverLeft = Signal()
    annotationsToggled = Signal(bool)
    # Emitted when the display scale changes materially. The annotation overlay
    # listens: its labels are screen-fixed but its collision avoidance runs in
    # IMAGE coordinates, so the reserved boxes are only correct for one zoom.
    zoomChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0, 130))
        self._item.setGraphicsEffect(shadow)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Never show scrollbars — zoom/pan (wheel + drag) handles navigation.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._has_image = False
        # Whether the view is showing the whole image at fit scale. Drives the
        # re-fit in resizeEvent. Initialised HERE, before anything can lay the
        # widget out: Qt delivers a resizeEvent during construction, and reading
        # this attribute before it existed would raise.
        self._fitted = False
        self._crop_mode = False               # crop stage active (box may still be hidden)
        self._pixel_cursor = False            # crosshair over image pixels (opt-in)
        self._content_bounds = None           # detected content edges for the next show
        self._guides = "none"                 # composition guides: none | thirds | center
        self._box_modified = False            # user adjusted the box since it was shown
        self._body: _Body | None = None
        self._handles: dict[str, _Handle] = {}
        self._aspect: float | None = None  # width / height
        self._compare_clip = None
        self._compare_item = None
        self._divider = None
        self._split_x = 0.0
        self._annotations = None
        self._zoom_pill = ZoomPill(self.zoom_out, self.fit, self.zoom_in, self)
        self._zoom_pill.raise_()
        self._position_zoom_pill()
        self.readout_pill = ReadoutPill(self)
        self._position_readout_pill()
        self.annotation_pill = AnnotationPill(self._on_annotation_toggled, self)
        self._position_annotation_pill()
        self.object_panel = ObjectListPanel(self)
        self.object_panel.closeRequested.connect(lambda: self.show_object_list(False))
        self._position_object_panel()
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def _position_zoom_pill(self) -> None:
        pill = self._zoom_pill
        pill.adjustSize()
        m = 12
        pill.move(self.width() - pill.width() - m, self.height() - pill.height() - m)

    def _position_readout_pill(self) -> None:
        m = 12
        self.readout_pill.move(m, self.height() - self.readout_pill.height() - m)

    def set_pixel_cursor(self, enabled: bool) -> None:
        """Opt into the crosshair cursor over image pixels. Off by default: the
        crosshair means 'there is a value for this pixel', so only a view with a
        readout wired up should show one."""
        self._pixel_cursor = bool(enabled)

    def _apply_hover_cursor(self, on_image: bool) -> None:
        """Crosshair over image pixels, open hand over the letterbox margin — the
        same predicate driving hovered/hoverLeft signals, so cursor and pill stay
        in step unless the pill hides itself when it has no value for the pixel.
        Left alone entirely in crop mode, where NoDrag's arrow and the crop handles
        own the cursor."""
        if not self._pixel_cursor or self._crop_mode:
            return
        want = (Qt.CursorShape.CrossCursor if on_image
                else Qt.CursorShape.OpenHandCursor)
        if self.viewport().cursor().shape() != want:
            self.viewport().setCursor(want)

    def _position_annotation_pill(self) -> None:
        pill = self.annotation_pill
        pill.adjustSize()
        m = 12
        pill.move(self.width() - pill.width() - m, m)      # top-right, clear of the zoom pill

    def _on_annotation_toggled(self, shown: bool) -> None:
        if self._annotations is not None:
            self._annotations.setVisible(shown)
        self.annotationsToggled.emit(shown)

    def _position_object_panel(self) -> None:
        """Under the Annotations pill, tall enough to be a real list — the whole
        reason it is here rather than in the right column."""
        m = 12
        pill_bottom = self.annotation_pill.y() + self.annotation_pill.height()
        w = 260
        h = max(160, int(self.height() * 0.55))
        h = min(h, max(160, self.height() - pill_bottom - 2 * m))
        self.object_panel.setFixedSize(w, h)
        self.object_panel.move(self.width() - w - m, pill_bottom + 8)

    def show_object_list(self, shown: bool) -> None:
        self.object_panel.setVisible(bool(shown))
        if shown:
            self._position_object_panel()
            self.object_panel.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Stay fitted across a resize — but ONLY if the view is still fitted.
        # fit() previously ran solely from set_image(), so any dialog that set its
        # image during __init__ locked in a fit measured against the pre-layout
        # viewport and opened "zoomed out to looks-empty"; star_spikes_dialog
        # carried a hand-rolled showEvent workaround for exactly that.
        #
        # Gated on _fitted so a deliberate zoom survives. Resizing the window
        # while zoomed to 100% must not yank you back out.
        #
        # CLAUDE.md warns that behaviour shared by a widget used in six places
        # should be opt-in. That rule earned itself on the crosshair, which is
        # wrong in a dialog preview. This one is different: "the user has not
        # zoomed, so keep showing the whole image" is correct on every surface,
        # and the surfaces that got it wrong were the ones working around its
        # absence. Safe to reload: scrollbars are ScrollBarAlwaysOff, so
        # fitInView here cannot toggle a scrollbar and re-enter resizeEvent.
        if self._fitted:
            self.fit()
        self._position_zoom_pill()
        self._position_readout_pill()
        self._position_annotation_pill()
        self._position_object_panel()

    # --- before/after compare ---
    def set_compare(self, qimage) -> None:
        self._teardown_compare()
        if qimage is None:
            return
        pm = QPixmap.fromImage(qimage)
        self._compare_clip = QGraphicsRectItem()
        self._compare_clip.setPen(QPen(Qt.PenStyle.NoPen))
        self._compare_clip.setFlag(
            QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape, True
        )
        self._compare_clip.setZValue(5)
        self._scene.addItem(self._compare_clip)
        self._compare_item = QGraphicsPixmapItem(pm, self._compare_clip)
        self._split_x = pm.width() / 2.0
        self._divider = _Divider(pm.height(), self._on_divider)
        self._divider.set_max_x(pm.width())
        self._scene.addItem(self._divider)
        self._divider.setPos(self._split_x, 0)
        self._apply_split()

    def compare_active(self) -> bool:
        return self._compare_item is not None

    def _on_divider(self, x: float) -> None:
        self._split_x = x
        self._apply_split()

    def _apply_split(self) -> None:
        if self._compare_item is None:
            return
        h = self._compare_item.pixmap().height()
        self._compare_clip.setRect(0, 0, max(0.0, self._split_x), h)

    def _teardown_compare(self) -> None:
        for it in (self._divider, self._compare_clip):
            if it is not None:
                self._scene.removeItem(it)
        self._divider = self._compare_clip = self._compare_item = None

    # --- image ---
    def set_image(self, qimage) -> None:
        prev = self._item.pixmap()
        prev_size = (prev.width(), prev.height())
        self._item.setPixmap(QPixmap.fromImage(qimage))
        self._scene.setSceneRect(self._item.boundingRect())
        new_size = (qimage.width(), qimage.height())
        if not self._has_image or new_size != prev_size:
            # fit on first image and whenever the dimensions change (e.g. crop)
            self._has_image = True
            self.fit()

    def _note_zoom(self) -> None:
        """Announce a materially changed display scale.

        The 2% threshold keeps a drag-resize from firing a rebuild per pixel;
        the overlay rebuild is cheap but not free, and nothing visible changes
        below that."""
        z = self.transform().m11()
        prev = getattr(self, "_last_zoom", 0.0)
        if z > 0 and (prev <= 0 or abs(z - prev) / max(prev, 1e-9) > 0.02):
            self._last_zoom = z
            self.zoomChanged.emit(z)

    def zoom(self) -> float:
        """Current display scale: image pixels -> view pixels."""
        return self.transform().m11()

    def fit(self) -> None:
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
            self._fitted = True
            self._note_zoom()

    def focus_on(self, x: float, y: float, min_scale: float = 1.0) -> None:
        """Centre the view on an image pixel, zooming in if currently zoomed out.

        Used by the plate-solve object list: picking an object should take you to
        it. Zooming only when below `min_scale` means a click never yanks you
        further out than you already were, and never re-zooms if you have
        deliberately zoomed in past it."""
        if self._item.pixmap().isNull():
            return
        current = self.transform().m11()
        if current < min_scale and current > 0:
            self.scale(min_scale / current, min_scale / current)
            self._fitted = False
            self._note_zoom()       # zoomed deliberately; a resize must not undo it
        self.centerOn(float(x), float(y))

    def actual_size(self) -> None:
        self.resetTransform()
        self._fitted = False
        self._note_zoom()

    def drawBackground(self, painter, rect) -> None:
        vp = self.viewport().rect()
        grad = QRadialGradient(vp.center(), max(vp.width(), vp.height()) * 0.7)
        grad.setColorAt(0.0, QColor(BG_1))
        grad.setColorAt(1.0, QColor(BG_0))
        painter.save()
        painter.resetTransform()
        painter.fillRect(vp, QBrush(grad))
        painter.restore()

    def drawForeground(self, painter, rect) -> None:
        """When the crop box is visible: dim the viewport outside the crop rect
        and draw the selected composition guides inside it. Works in device/
        viewport coords, mirroring `drawBackground`'s save/reset/restore."""
        if not (self._crop_mode and self.crop_box_visible()):
            return
        box = self.mapFromScene(self._scene_rect()).boundingRect()
        vp = self.viewport().rect()
        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        # Dim the four regions outside the crop rect.
        dim = QColor(0, 0, 0, 120)
        left = box.left()
        right = box.right()
        top = box.top()
        bottom = box.bottom()
        painter.fillRect(QRectF(vp.left(), vp.top(),
                                vp.width(), top - vp.top()), dim)             # above
        painter.fillRect(QRectF(vp.left(), bottom,
                                vp.width(), vp.bottom() - bottom), dim)       # below
        painter.fillRect(QRectF(vp.left(), top,
                                left - vp.left(), bottom - top), dim)         # left
        painter.fillRect(QRectF(right, top,
                                vp.right() - right, bottom - top), dim)       # right
        # Composition guides inside the crop rect.
        if self._guides != "none":
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            w, h = box.width(), box.height()
            if self._guides == "thirds":
                xs = (left + w / 3.0, left + 2.0 * w / 3.0)
                ys = (top + h / 3.0, top + 2.0 * h / 3.0)
            else:  # center
                xs = (left + w / 2.0,)
                ys = (top + h / 2.0,)
            for x in xs:
                painter.drawLine(QPointF(x, top), QPointF(x, bottom))
            for y in ys:
                painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.restore()

    def zoom_in(self) -> None:
        if not self._item.pixmap().isNull():
            self.scale(1.25, 1.25)
            self._fitted = False
            self._note_zoom()

    def zoom_out(self) -> None:
        if not self._item.pixmap().isNull():
            self.scale(0.8, 0.8)
            self._fitted = False
            self._note_zoom()

    def wheelEvent(self, event) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        self._emit_hover_at_scene_pos(self.mapToScene(event.position().toPoint()),
                                      panning=bool(event.buttons()))

    def mouseReleaseEvent(self, event) -> None:
        """Qt's ScrollHandDrag release handler resets the viewport to the open
        hand; re-apply ours or the user sits on an open hand over the image until
        they nudge the mouse."""
        super().mouseReleaseEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        self._apply_hover_cursor(self._image_pixel_at(pos) is not None)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hoverLeft.emit()

    def _image_pixel_at(self, scene_pos) -> tuple[int, int] | None:
        """The image pixel under `scene_pos`, or None if there isn't one — crop
        mode, no image, or outside the frame. Scene coordinates ARE image pixel
        coordinates: the scene rect is the pixmap item's bounding rect with the
        item at the origin.

        floor(), not int(): int() truncates toward zero, which would map scene
        coordinates in (-1, 0) to pixel 0 instead of off-image."""
        if self._crop_mode or self._item.pixmap().isNull():
            return None
        x, y = math.floor(scene_pos.x()), math.floor(scene_pos.y())
        pm = self._item.pixmap()
        if not (0 <= x < pm.width() and 0 <= y < pm.height()):
            return None
        return x, y

    def _emit_hover_at_scene_pos(self, scene_pos, panning: bool = False) -> None:
        """Report the pixel under the cursor, naming which side of the
        before/after divider it is on so the caller samples the image the user is
        actually looking at, and match the cursor to it. While a button is held
        the cursor is left alone so Qt's closed 'grabbing' hand survives the pan."""
        pixel = self._image_pixel_at(scene_pos)
        if not panning:
            self._apply_hover_cursor(pixel is not None)
        if pixel is None:
            self.hoverLeft.emit()
            return
        side = "compare" if (self._compare_item is not None
                             and scene_pos.x() < self._split_x) else "main"
        self.hovered.emit(pixel[0], pixel[1], side)

    # --- crop overlay ---
    def set_crop_overlay(self, enabled: bool, content_bounds=None,
                         aspect_ratio=None) -> None:
        """Toggle crop *mode* and store the detected content bounds. Crop mode
        being on is distinct from the box being visible — this never draws the
        box; the first click (or `show_crop_box`) does."""
        self._crop_mode = enabled
        self._aspect = aspect_ratio
        self._content_bounds = content_bounds
        # Hide the floating zoom pill while cropping so it can't sit over a
        # bottom-right crop handle and swallow its drags.
        self._zoom_pill.setVisible(not enabled)
        if enabled:
            self.readout_pill.hide()
        if not enabled:
            self._teardown_overlay()
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            return
        self.setDragMode(QGraphicsView.DragMode.NoDrag)  # let the box take drags

    def show_crop_box(self) -> None:
        """Build + show the crop body/handles at the stored content bounds
        (idempotent) and announce it via `cropBoxShown`."""
        if self._body is not None:
            return  # already visible
        self._body = _Body(self)
        self._scene.addItem(self._body)
        for name in _HANDLES:
            h = _Handle(name, self)
            self._handles[name] = h
            self._scene.addItem(h)
        bounds = self._content_bounds
        if bounds is None:
            pm = self._item.pixmap()
            bounds = (0, pm.height(), 0, pm.width())
        self._set_bounds(bounds)
        self._box_modified = False  # fresh box at content edges — nothing to lose yet
        self.viewport().update()
        self.cropBoxShown.emit()

    def hide_crop_box(self) -> None:
        """Remove the crop body/handles but stay in crop mode."""
        self._teardown_overlay()
        self.viewport().update()

    def crop_box_visible(self) -> bool:
        return self._body is not None

    def crop_box_modified(self) -> bool:
        """True if the user has moved/resized/reshaped the box since it appeared."""
        return self._box_modified

    def set_guides(self, kind: str) -> None:
        """Select composition guides: "none" | "thirds" | "center"."""
        self._guides = kind
        self.viewport().update()

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        # First click while in crop mode reveals the box at the detected edges.
        if self._crop_mode and not self.crop_box_visible():
            scene_pos = self.mapToScene(pos)
            if self._item.sceneBoundingRect().contains(scene_pos):
                self.show_crop_box()
            super().mousePressEvent(event)
            return
        # A click on the dimmed area (not the box or a handle) asks to dismiss.
        if self._crop_mode and self.crop_box_visible():
            item = self.itemAt(pos)
            if item is None or item is self._item:
                self.cropDismissRequested.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if (event.key() == Qt.Key.Key_Escape
                and self._crop_mode and self.crop_box_visible()):
            self.cropDismissRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_aspect(self, aspect_ratio) -> None:
        self._aspect = aspect_ratio

    def apply_aspect(self, aspect_ratio) -> None:
        """Lock to a ratio and immediately reshape the current box to it (centered)."""
        self._aspect = aspect_ratio
        if self._body is None or aspect_ratio is None:
            return
        r = self._scene_rect()
        cx, cy = r.center().x(), r.center().y()
        w = r.width()
        h = w / aspect_ratio
        self._body.setPos(0, 0)
        self._body.setRect(QRectF(cx - w / 2, cy - h / 2, w, h))
        self._position_handles()
        self._emit_bounds()

    def _teardown_overlay(self) -> None:
        if self._body is not None:
            self._scene.removeItem(self._body)
            self._body = None
        for h in self._handles.values():
            self._scene.removeItem(h)
        self._handles.clear()

    # --- annotation overlay (DSO labels + compass + scale bar) ---
    def set_annotations(self, group) -> None:
        """Annotations are CLIPPED to the image. A big nebula's true-size circle
        legitimately runs past the frame edge, but without a clip it also paints
        across the empty canvas around the image, which reads as a broken
        overlay rather than an object larger than the field."""
        if self._annotations is not None:
            self._scene.removeItem(self._annotations)
            self._annotations = None
        if group is None:
            self.annotation_pill.hide()
            return
        self.annotation_pill.set_shown(True)
        self.annotation_pill.show()
        self.annotation_pill.raise_()
        pm = self._item.pixmap()
        clip = QGraphicsRectItem(0, 0, pm.width(), pm.height())
        clip.setPen(QPen(Qt.PenStyle.NoPen))
        clip.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        clip.setZValue(8)
        group.setParentItem(clip)
        self._scene.addItem(clip)
        self._annotations = clip

    def _set_bounds(self, bounds) -> None:
        top, bottom, left, right = bounds
        self._body.setPos(0, 0)
        self._body.setRect(QRectF(left, top, max(1, right - left), max(1, bottom - top)))
        self._position_handles()

    def _scene_rect(self) -> QRectF:
        return self._body.mapRectToScene(self._body.rect())

    def _position_handles(self) -> None:
        r = self._scene_rect()
        cx, cy = r.center().x(), r.center().y()
        pts = {
            "tl": (r.left(), r.top()), "tr": (r.right(), r.top()),
            "bl": (r.left(), r.bottom()), "br": (r.right(), r.bottom()),
            "t": (cx, r.top()), "b": (cx, r.bottom()),
            "l": (r.left(), cy), "r": (r.right(), cy),
        }
        for name, h in self._handles.items():
            x, y = pts[name]
            h.setPos(x, y)

    def _image_wh(self) -> tuple[float, float]:
        pm = self._item.pixmap()
        return float(pm.width()), float(pm.height())

    def _clamp_body_pos(self, body, pos: QPointF) -> QPointF:
        """Constrain a proposed body position so the box's scene rect stays inside
        the image — slides the box back in, preserving its size. A box larger than
        the image (shouldn't happen) pins to the top-left."""
        W, H = self._image_wh()
        r = body.rect()                       # item-local rect: carries left/top + size
        lo_x, hi_x = -r.left(), W - r.right()   # keep [left+x, right+x] within [0, W]
        lo_y, hi_y = -r.top(), H - r.bottom()
        if hi_x < lo_x:
            hi_x = lo_x
        if hi_y < lo_y:
            hi_y = lo_y
        return QPointF(min(max(pos.x(), lo_x), hi_x), min(max(pos.y(), lo_y), hi_y))

    def _resize_to(self, name: str, scene_pos) -> None:
        W, H = self._image_wh()
        r = self._scene_rect()
        x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
        px = min(max(scene_pos.x(), 0.0), W)          # clamp the drag point to the image
        py = min(max(scene_pos.y(), 0.0), H)
        if "l" in name:
            x0 = px
        if "r" in name:
            x1 = px
        if "t" in name:
            y0 = py
        if "b" in name:
            y1 = py
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if self._aspect:
            # Grow the aspect-locked box from the un-dragged anchor edge toward the
            # drag, capped so it stays inside the image (preserves ratio + bounds).
            anchor_x = x1 if "l" in name else x0
            anchor_y = y1 if "t" in name else y0
            avail_w = anchor_x if "l" in name else (W - anchor_x)
            avail_h = anchor_y if "t" in name else (H - anchor_y)
            drive_h = (y1 - y0) if name in ("t", "b") else (x1 - x0) / self._aspect
            h = max(1.0, min(drive_h, avail_h, avail_w / self._aspect))
            w = h * self._aspect
            x0, x1 = (anchor_x - w, anchor_x) if "l" in name else (anchor_x, anchor_x + w)
            y0, y1 = (anchor_y - h, anchor_y) if "t" in name else (anchor_y, anchor_y + h)
        self._body.setPos(0, 0)
        self._body.setRect(QRectF(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0)))
        self._position_handles()
        self._geometry_changed()

    def _geometry_changed(self) -> None:
        self._position_handles()
        self._emit_bounds()

    def crop_bounds(self) -> tuple[int, int, int, int]:
        r = self._scene_rect()
        pm = self._item.pixmap()
        top = max(0, min(int(round(r.top())), pm.height()))
        bottom = max(0, min(int(round(r.bottom())), pm.height()))
        left = max(0, min(int(round(r.left())), pm.width()))
        right = max(0, min(int(round(r.right())), pm.width()))
        return top, bottom, left, right

    def _emit_bounds(self) -> None:
        self._box_modified = True  # any user-driven bounds change counts as work
        self.cropBoxChanged.emit(*self.crop_bounds())
