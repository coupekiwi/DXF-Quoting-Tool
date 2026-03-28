"""PyQt6 canvas widget for rendering DXF geometry with pan, zoom, and measurement."""

import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QWheelEvent, QMouseEvent, QPaintEvent,
    QFont, QFontMetrics,
)

from core.dxf_loader import DxfPart, GeomSegment

# Colours for different loaded parts
PART_COLOURS = [
    QColor("#2196F3"),  # blue
    QColor("#4CAF50"),  # green
    QColor("#FF9800"),  # orange
    QColor("#9C27B0"),  # purple
    QColor("#F44336"),  # red
    QColor("#00BCD4"),  # cyan
    QColor("#795548"),  # brown
    QColor("#607D8B"),  # grey-blue
]


class DxfCanvas(QWidget):
    """Widget that renders DXF parts with pan/zoom and measurement."""

    measurement_changed = pyqtSignal(float)  # emits distance in file units

    def __init__(self, parent=None, colour: QColor | None = None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)
        self.part_colour = colour
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.parts: list[DxfPart] = []
        self.hidden_layers: set[str] = set()

        # View transform
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._dragging = False
        self._drag_start = QPointF()

        # Measurement
        self.measure_mode = False
        self._measure_p1: tuple[float, float] | None = None
        self._measure_p2: tuple[float, float] | None = None
        self._snap_points: list[tuple[float, float]] = []
        self._hover_snap: tuple[float, float] | None = None

        self.setStyleSheet("background-color: #1e1e1e;")

    def set_parts(self, parts: list[DxfPart]):
        self.parts = parts
        self._rebuild_snap_points()
        self.fit_view()
        self.update()

    def _rebuild_snap_points(self):
        """Collect all snappable points from loaded geometry."""
        self._snap_points = []
        for part in self.parts:
            for seg in part.segments:
                if seg.p1:
                    self._snap_points.append(seg.p1)
                if seg.p2:
                    self._snap_points.append(seg.p2)
                if seg.center:
                    self._snap_points.append(seg.center)
                    # Also add cardinal points of circles/arcs
                    if seg.kind == "circle":
                        r = seg.radius
                        cx, cy = seg.center
                        self._snap_points.extend([
                            (cx + r, cy), (cx - r, cy),
                            (cx, cy + r), (cx, cy - r),
                        ])

    def fit_view(self):
        """Zoom to fit all loaded geometry."""
        if not self.parts:
            return
        all_bboxes = [p.bbox for p in self.parts]
        minx = min(b[0] for b in all_bboxes)
        miny = min(b[1] for b in all_bboxes)
        maxx = max(b[2] for b in all_bboxes)
        maxy = max(b[3] for b in all_bboxes)

        data_w = maxx - minx
        data_h = maxy - miny
        if data_w < 1e-6 or data_h < 1e-6:
            return

        margin = 40
        view_w = self.width() - margin * 2
        view_h = self.height() - margin * 2
        if view_w < 10 or view_h < 10:
            return

        self._zoom = min(view_w / data_w, view_h / data_h)
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        self._pan_x = self.width() / 2.0 - cx * self._zoom
        self._pan_y = self.height() / 2.0 + cy * self._zoom  # flip Y

    def _to_screen(self, x: float, y: float) -> QPointF:
        """Convert DXF coords to screen coords (Y flipped)."""
        sx = x * self._zoom + self._pan_x
        sy = -y * self._zoom + self._pan_y
        return QPointF(sx, sy)

    def _to_dxf(self, sx: float, sy: float) -> tuple[float, float]:
        """Convert screen coords to DXF coords."""
        x = (sx - self._pan_x) / self._zoom
        y = -(sy - self._pan_y) / self._zoom
        return (x, y)

    def _find_snap(self, sx: float, sy: float, threshold: float = 15.0) -> tuple[float, float] | None:
        """Find the nearest snap point within threshold pixels."""
        best = None
        best_dist = threshold
        for pt in self._snap_points:
            sp = self._to_screen(pt[0], pt[1])
            dist = math.hypot(sp.x() - sx, sp.y() - sy)
            if dist < best_dist:
                best_dist = dist
                best = pt
        return best

    # --- Events ---

    def wheelEvent(self, event: QWheelEvent):
        # Zoom centred on cursor
        old_dxf = self._to_dxf(event.position().x(), event.position().y())
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        # Adjust pan so the point under cursor stays fixed
        new_screen = self._to_screen(old_dxf[0], old_dxf[1])
        self._pan_x += event.position().x() - new_screen.x()
        self._pan_y += event.position().y() - new_screen.y()
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = True
            self._drag_start = event.position()
        elif event.button() == Qt.MouseButton.LeftButton and self.measure_mode:
            snap = self._find_snap(event.position().x(), event.position().y())
            if snap:
                if self._measure_p1 is None:
                    self._measure_p1 = snap
                    self._measure_p2 = None
                else:
                    self._measure_p2 = snap
                    dist = math.hypot(
                        self._measure_p2[0] - self._measure_p1[0],
                        self._measure_p2[1] - self._measure_p1[1],
                    )
                    self.measurement_changed.emit(dist)
                self.update()

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
        elif self.measure_mode:
            self._hover_snap = self._find_snap(event.position().x(), event.position().y())
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._measure_p1 = None
            self._measure_p2 = None
            self._hover_snap = None
            self.update()

    # --- Painting ---

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        # Draw geometry
        for i, part in enumerate(self.parts):
            colour = self.part_colour if self.part_colour else PART_COLOURS[i % len(PART_COLOURS)]
            self._draw_part(painter, part, colour)

        # Draw measurement overlay
        self._draw_measurement(painter)

        # Draw snap indicator
        if self.measure_mode and self._hover_snap:
            sp = self._to_screen(self._hover_snap[0], self._hover_snap[1])
            pen = QPen(QColor("#FFEB3B"), 2)
            painter.setPen(pen)
            painter.drawEllipse(sp, 6, 6)

        painter.end()

    def _draw_part(self, painter: QPainter, part: DxfPart, colour: QColor):
        pen = QPen(colour, 1.5)
        painter.setPen(pen)

        for seg in part.segments:
            if seg.layer in self.hidden_layers:
                continue
            if seg.kind == "line" and seg.p1 and seg.p2:
                p1 = self._to_screen(*seg.p1)
                p2 = self._to_screen(*seg.p2)
                painter.drawLine(p1, p2)
            elif seg.kind == "circle" and seg.center:
                sp = self._to_screen(*seg.center)
                r_px = seg.radius * self._zoom
                painter.drawEllipse(sp, r_px, r_px)
            elif seg.kind == "arc" and seg.center:
                # Draw arcs as full circles for display (avoids Y-flip rendering issues)
                sp = self._to_screen(*seg.center)
                r_px = seg.radius * self._zoom
                painter.drawEllipse(sp, r_px, r_px)

    def _draw_measurement(self, painter: QPainter):
        if not self._measure_p1:
            return

        p1_screen = self._to_screen(*self._measure_p1)

        # Draw first point marker
        pen = QPen(QColor("#FF5722"), 2)
        painter.setPen(pen)
        painter.drawEllipse(p1_screen, 5, 5)

        if self._measure_p2:
            p2_screen = self._to_screen(*self._measure_p2)
            # Draw second point and line
            painter.drawEllipse(p2_screen, 5, 5)

            dash_pen = QPen(QColor("#FF5722"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.drawLine(p1_screen, p2_screen)

            # Draw distance label
            dist = math.hypot(
                self._measure_p2[0] - self._measure_p1[0],
                self._measure_p2[1] - self._measure_p1[1],
            )
            mid = QPointF(
                (p1_screen.x() + p2_screen.x()) / 2,
                (p1_screen.y() + p2_screen.y()) / 2 - 12,
            )
            font = QFont("Consolas", 11)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#FFFFFF")))
            painter.drawText(mid, f"{dist:.2f} mm")
