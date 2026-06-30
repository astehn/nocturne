from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
)

_ACCENT = QColor("#2dd4bf")
_HANDLES = ("tl", "tr", "bl", "br", "t", "b", "l", "r")


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
        self.setBrush(QBrush(QColor(45, 212, 191, 40)))
        self.setZValue(10)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionHasChanged:
            self._overlay._geometry_changed()
        return super().itemChange(change, value)


class ImageView(QGraphicsView):
    cropBoxChanged = Signal(int, int, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._has_image = False
        self._body: _Body | None = None
        self._handles: dict[str, _Handle] = {}
        self._aspect: float | None = None  # width / height

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

    def fit(self) -> None:
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.resetTransform()

    def wheelEvent(self, event) -> None:
        if self._item.pixmap().isNull():
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    # --- crop overlay ---
    def set_crop_overlay(self, enabled: bool, bounds=None, aspect_ratio=None) -> None:
        self._aspect = aspect_ratio
        if not enabled:
            self._teardown_overlay()
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            return
        self.setDragMode(QGraphicsView.DragMode.NoDrag)  # let the box take drags
        if self._body is None:
            self._body = _Body(self)
            self._scene.addItem(self._body)
            for name in _HANDLES:
                h = _Handle(name, self)
                self._handles[name] = h
                self._scene.addItem(h)
        if bounds is None:
            pm = self._item.pixmap()
            bounds = (0, pm.height(), 0, pm.width())
        self._set_bounds(bounds)

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

    def _resize_to(self, name: str, scene_pos) -> None:
        r = self._scene_rect()
        x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
        if "l" in name:
            x0 = scene_pos.x()
        if "r" in name:
            x1 = scene_pos.x()
        if "t" in name:
            y0 = scene_pos.y()
        if "b" in name:
            y1 = scene_pos.y()
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
        if self._aspect:
            if name in ("t", "b"):  # height-driven
                w = h * self._aspect
                x1 = x0 + w
            else:  # width-driven (corners, left/right)
                h = w / self._aspect
                y1 = y0 + h
        self._body.setPos(0, 0)
        self._body.setRect(QRectF(x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0)))
        self._position_handles()
        self._emit_bounds()

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
        self.cropBoxChanged.emit(*self.crop_bounds())
