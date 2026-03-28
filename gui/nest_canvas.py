"""Canvas that shows the nested sheet layout preview - all sheets side by side."""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush, QWheelEvent, QMouseEvent

from core.nesting import NestResult

PART_FILLS = [
    QColor(33, 150, 243, 60),   # blue
    QColor(76, 175, 80, 60),    # green
    QColor(255, 152, 0, 60),    # orange
    QColor(156, 39, 176, 60),   # purple
    QColor(244, 67, 54, 60),    # red
    QColor(0, 188, 212, 60),    # cyan
]

PART_BORDERS = [
    QColor("#2196F3"),
    QColor("#4CAF50"),
    QColor("#FF9800"),
    QColor("#9C27B0"),
    QColor("#F44336"),
    QColor("#00BCD4"),
]

SHEET_GAP = 40  # pixel gap between sheets


class NestCanvas(QWidget):
    """Shows a visual preview of the nested layout with all sheets side by side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 200)
        self.nest_result: NestResult | None = None
        self._part_colour_map: dict[str, int] = {}
        self.setStyleSheet("background-color: #252525;")
        self.setMouseTracking(True)

        # Pan and zoom
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._dragging = False
        self._drag_start = QPointF()

    def set_result(self, result: NestResult, colour_map: dict[str, int]):
        self.nest_result = result
        self._part_colour_map = colour_map
        self._fit_all_sheets()
        self.update()

    def set_sheet(self, index: int):
        # No longer needed since we show all sheets, but keep for compatibility
        self.update()

    def _fit_all_sheets(self):
        """Zoom/pan to fit all sheets side by side."""
        nr = self.nest_result
        if not nr or nr.sheets_used == 0:
            return

        total_w = nr.sheets_used * nr.sheet_width + (nr.sheets_used - 1) * (SHEET_GAP / 1.0)
        total_h = nr.sheet_height

        margin = 30
        view_w = self.width() - margin * 2
        view_h = self.height() - margin * 2
        if view_w < 10 or view_h < 10:
            return

        # Scale so the gap is in data-space; we'll use a fixed data-space gap
        data_gap = nr.sheet_width * 0.05  # 5% of sheet width between sheets
        total_data_w = nr.sheets_used * nr.sheet_width + (nr.sheets_used - 1) * data_gap
        total_data_h = nr.sheet_height

        self._zoom = min(view_w / total_data_w, view_h / total_data_h)
        self._pan_x = margin + (view_w - total_data_w * self._zoom) / 2
        self._pan_y = margin + (view_h - total_data_h * self._zoom) / 2
        # Store the data-space gap for painting
        self._data_gap = data_gap

    # --- Events ---

    def wheelEvent(self, event: QWheelEvent):
        old_x = (event.position().x() - self._pan_x) / self._zoom
        old_y = (event.position().y() - self._pan_y) / self._zoom
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        self._pan_x = event.position().x() - old_x * self._zoom
        self._pan_y = event.position().y() - old_y * self._zoom
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = True
            self._drag_start = event.position()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = False

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            dx = event.position().x() - self._drag_start.x()
            dy = event.position().y() - self._drag_start.y()
            self._pan_x += dx
            self._pan_y += dy
            self._drag_start = event.position()
            self.update()

    # --- Painting ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252525"))

        if not self.nest_result or not self.nest_result.placements:
            painter.setPen(QColor("#666666"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No nesting result")
            painter.end()
            return

        nr = self.nest_result
        data_gap = getattr(self, "_data_gap", nr.sheet_width * 0.05)

        for sheet_idx in range(nr.sheets_used):
            # Each sheet offset in data space
            sheet_ox = sheet_idx * (nr.sheet_width + data_gap)
            sheet_oy = 0.0

            # Screen coords for this sheet
            sx = sheet_ox * self._zoom + self._pan_x
            sy = sheet_oy * self._zoom + self._pan_y
            sw = nr.sheet_width * self._zoom
            sh = nr.sheet_height * self._zoom

            # Draw sheet outline
            painter.setPen(QPen(QColor("#555555"), 1.5))
            painter.setBrush(QBrush(QColor("#2a2a2a")))
            painter.drawRect(QRectF(sx, sy, sw, sh))

            # Draw placed parts on this sheet
            font = QFont("Consolas", 8)
            painter.setFont(font)

            for p in nr.placements:
                if p.sheet_index != sheet_idx:
                    continue

                ci = self._part_colour_map.get(p.name, 0) % len(PART_FILLS)
                fill = PART_FILLS[ci]
                border = PART_BORDERS[ci]

                rx = (sheet_ox + p.x) * self._zoom + self._pan_x
                ry = (sheet_oy + p.y) * self._zoom + self._pan_y
                rw = p.width * self._zoom
                rh = p.height * self._zoom

                painter.setPen(QPen(border, 1.5))
                painter.setBrush(QBrush(fill))
                painter.drawRect(QRectF(rx, ry, rw, rh))

                # Label (only if rect is big enough)
                if rw > 30 and rh > 14:
                    painter.setPen(QColor("#cccccc"))
                    label = p.name[:20]
                    if p.rotated:
                        label += " (90\u00b0)"
                    rect = QRectF(rx + 2, ry + 2, rw - 4, rh - 4)
                    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

            # Sheet label below
            painter.setPen(QColor("#999999"))
            painter.setFont(QFont("Segoe UI", 9))
            label_y = sy + sh + 14
            painter.drawText(
                int(sx), int(label_y),
                f"Sheet {sheet_idx + 1}"
            )

        # Overall label
        painter.setPen(QColor("#777777"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            6, self.height() - 6,
            f"{nr.sheets_used} sheet{'s' if nr.sheets_used != 1 else ''}"
            f"  |  {nr.sheet_width:.0f} x {nr.sheet_height:.0f} mm each"
            f"  |  middle-click drag to pan, scroll to zoom"
        )

        painter.end()
