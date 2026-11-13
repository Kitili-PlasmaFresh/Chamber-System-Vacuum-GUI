"""Rolling chamber-pressure chart drawn with QPainter."""

import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QSizePolicy, QWidget

from core.config import CHART_SECONDS


class PressureChart(QWidget):
    """Lightweight rolling pressure plot drawn with QPainter."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        qp.fillRect(0, 0, w, h, QColor("white"))
        L, R, T, B = 44, 10, 10, 20
        hist = self.app.history
        pts = [p for _t, p in hist]
        marks = []
        for key, col, name in (("target_pressure", "#2e7d32", "target"),
                               ("ambient_pressure", "#1565c0", "ambient")):
            try:
                marks.append((self.app.get(key), col, name))
            except ValueError:
                pass
        ymax = max([110.0] + pts + [m[0] * 1.05 for m in marks])
        ymin = min([0.0] + pts)

        def y(v):
            return T + (h - T - B) * (1 - (v - ymin) / ((ymax - ymin) or 1))

        small = QFont(qp.font())
        small.setPointSize(8)
        qp.setFont(small)
        for frac in (0, 0.25, 0.5, 0.75, 1):
            v = ymin + (ymax - ymin) * frac
            qp.setPen(QPen(QColor("#eeeeee")))
            qp.drawLine(QPointF(L, y(v)), QPointF(w - R, y(v)))
            qp.setPen(QPen(QColor("#777777")))
            qp.drawText(QRectF(0, y(v) - 8, L - 4, 16),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:.0f}")
        for v, col, name in marks:
            pen = QPen(QColor(col))
            pen.setStyle(Qt.PenStyle.DashLine)
            qp.setPen(pen)
            qp.drawLine(QPointF(L, y(v)), QPointF(w - R, y(v)))
            qp.drawText(QRectF(L, y(v) - 16, w - R - L - 2, 14), Qt.AlignmentFlag.AlignRight, name)
        qp.setPen(QPen(QColor("#777777")))
        qp.drawText(QRectF(L, h - B, 100, B), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"-{CHART_SECONDS}s   (kPa)")
        qp.drawText(QRectF(w - R - 100, h - B, 100, B),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "now")
        if len(hist) > 1:
            now = time.time()
            poly = QPolygonF([QPointF(L + (w - L - R) * (1 - (now - t) / CHART_SECONDS), y(p))
                              for t, p in hist])
            qp.setPen(QPen(QColor("#c62828"), 2))
            qp.drawPolyline(poly)
        qp.end()
