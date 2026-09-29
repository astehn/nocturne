"""The full frame, small: where the crop is and which part of it the two
views show. Click or drag to move both views there."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme

CROP_COLOUR = "#4aa3ff"
VISIBLE_COLOUR = "#ffd24a"


class UpscaleNavigator(QWidget):
    centreRequested = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._frame = QPixmap()
        self._fw = self._fh = 1
        self._crop = None          # (top, bottom, left, right) in frame px
        self._scale = 2
        self._visible = None       # (x, y, w, h) in result px
        self.setMinimumHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_frame(self, qimage: QImage) -> None:
        self._frame = QPixmap.fromImage(qimage)
        self._fw, self._fh = max(1, qimage.width()), max(1, qimage.height())
        self.update()

    def set_crop(self, crop, scale: int) -> None:
        self._crop, self._scale = crop, scale
        self.update()

    def set_visible_rect(self, x, y, w, h) -> None:
        self._visible = (x, y, w, h)
        self.update()

    # --- geometry ---
    def _frame_rect(self) -> QRectF:
        s = min(self.width() / self._fw, self.height() / self._fh)
        w, h = self._fw * s, self._fh * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _k(self) -> float:
        return self._frame_rect().width() / self._fw

    def _crop_px(self):
        return self._crop or (0, self._fh, 0, self._fw)

    def crop_rect_on_widget(self) -> QRectF:
        top, bottom, left, right = self._crop_px()
        fr, k = self._frame_rect(), self._k()
        return QRectF(fr.left() + left * k, fr.top() + top * k,
                      (right - left) * k, (bottom - top) * k)

    def visible_rect_on_widget(self) -> QRectF:
        if self._visible is None:
            return QRectF()
        x, y, w, h = self._visible
        cr, k = self.crop_rect_on_widget(), self._k() / self._scale
        return QRectF(cr.left() + x * k, cr.top() + y * k, w * k, h * k).intersected(cr)

    # --- painting / input ---
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG_2))
        if not self._frame.isNull():
            p.drawPixmap(self._frame_rect(), self._frame, QRectF(self._frame.rect()))
        p.setPen(QPen(QColor(CROP_COLOUR), 1.5, Qt.PenStyle.DashLine))
        p.drawRect(self.crop_rect_on_widget())
        vr = self.visible_rect_on_widget()
        if not vr.isEmpty():
            p.setPen(QPen(QColor(VISIBLE_COLOUR), 1.5))
            p.drawRect(vr)
        p.end()

    def _request(self, pos: QPointF) -> None:
        cr, k = self.crop_rect_on_widget(), self._k() / self._scale
        if k <= 0:
            return
        x = min(max(pos.x(), cr.left()), cr.right()) - cr.left()
        y = min(max(pos.y(), cr.top()), cr.bottom()) - cr.top()
        self.centreRequested.emit(x / k, y / k)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._request(e.position())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._request(e.position())
