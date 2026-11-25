"""Inlet sensors tab: flow rate, humidity and temperature from the Arduino's I2C sensors
(SFM4300-50-P flow meter, CHT832X humidity sensor). Each reading can be switched on or off;
a switched-off reading is not displayed, plotted or written to the CSV."""

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.config import CHART_SECONDS

# key, title, DATA field, sensor-present flag, unit, decimals, trace colour
READINGS = [
    ("FLOW", "Flow rate", "FLOW", "FLOWOK", "slm", 2, "#1565c0"),
    ("HUM", "Humidity", "HUM", "HUMOK", "%RH", 1, "#00838f"),
    ("TEMP", "Temperature", "HTEMP", "HUMOK", "°C", 1, "#e65100"),
]


class TrendChart(QWidget):
    """Small rolling line chart, auto-scaled to the visible data."""

    def __init__(self, unit, colour):
        super().__init__()
        self.unit, self.colour = unit, colour
        self.history = []          # [(epoch_s, value)]
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add(self, t, v):
        self.history.append((t, v))
        while self.history and t - self.history[0][0] > CHART_SECONDS:
            self.history.pop(0)

    def paintEvent(self, _ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        qp.fillRect(0, 0, w, h, QColor("white"))
        L, R, T, B = 44, 10, 8, 18
        vals = [v for _t, v in self.history]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
        pad = max((hi - lo) * 0.1, 0.5)
        lo, hi = lo - pad, hi + pad

        def y(v):
            return T + (h - T - B) * (1 - (v - lo) / (hi - lo))

        small = QFont(qp.font())
        small.setPointSize(8)
        qp.setFont(small)
        for frac in (0, 0.5, 1):
            v = lo + (hi - lo) * frac
            qp.setPen(QPen(QColor("#eeeeee")))
            qp.drawLine(QPointF(L, y(v)), QPointF(w - R, y(v)))
            qp.setPen(QPen(QColor("#777777")))
            qp.drawText(QRectF(0, y(v) - 8, L - 4, 16),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:.1f}")
        qp.drawText(QRectF(L, h - B, 150, B), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"-{CHART_SECONDS}s   ({self.unit})")
        qp.drawText(QRectF(w - R - 100, h - B, 100, B),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "now")
        if len(self.history) > 1:
            now = time.time()
            poly = QPolygonF([QPointF(L + (w - L - R) * (1 - (now - t) / CHART_SECONDS), y(v))
                              for t, v in self.history])
            qp.setPen(QPen(QColor(self.colour), 2))
            qp.drawPolyline(poly)
        qp.end()


class InletSensorsTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        note = QLabel("Inlet gas sensors on the Arduino I2C bus. Untick a reading to stop "
                      "monitoring it: it is no longer shown, plotted or recorded to CSV.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        lay.addWidget(note)

        self.cards = {}
        for key, title, field, ok_key, unit, dec, colour in READINGS:
            box = QGroupBox(title)
            box.setCheckable(True)
            box.setChecked(True)
            bl = QVBoxLayout(box)
            row = QHBoxLayout()
            value = QLabel("—")
            value.setStyleSheet("font-size: 22px; font-weight: bold;")
            value.setMinimumWidth(160)
            status = QLabel("")
            status.setStyleSheet("color: gray;")
            row.addWidget(value)
            row.addWidget(status, 1)
            bl.addLayout(row)
            chart = TrendChart(unit, colour)
            bl.addWidget(chart, 1)
            box.toggled.connect(lambda on, k=key: self._toggled(k, on))
            lay.addWidget(box, 1)
            self.cards[key] = dict(box=box, value=value, status=status, chart=chart,
                                   field=field, ok_key=ok_key, unit=unit, dec=dec)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._repaint_charts)
        self._timer.start(500)

    # ------------------------------------------------------ toggles
    def enabled(self, key):
        return self.cards[key]["box"].isChecked()

    def _toggled(self, key, on):
        c = self.cards[key]
        c["chart"].setVisible(on)
        c["status"].setVisible(on)
        self.layout().setStretchFactor(c["box"], 1 if on else 0)   # collapse when off
        if on:
            c["value"].setText("—")
            c["value"].setStyleSheet("font-size: 22px; font-weight: bold;")
        else:
            c["chart"].history.clear()
            c["value"].setText("Off")
            c["value"].setStyleSheet("font-size: 22px; font-weight: bold; color: gray;")

    def get_state(self):
        return {k: self.enabled(k) for k in self.cards}

    def set_state(self, saved):
        for k, on in (saved or {}).items():
            if k in self.cards:
                self.cards[k]["box"].setChecked(bool(on))

    # ------------------------------------------------------ data
    def update_data(self, d):
        """Called with each parsed DATA line from the Arduino."""
        now = time.time()
        for c in self.cards.values():
            if not c["box"].isChecked():
                continue
            if c["ok_key"] not in d:
                c["value"].setText("—")
                c["status"].setText("not reported by the connected firmware")
            elif d[c["ok_key"]] and c["field"] in d:
                v = round(d[c["field"]], c["dec"]) or 0.0      # no "-0.00"
                c["value"].setText(f"{v:.{c['dec']}f} {c['unit']}")
                c["status"].setText("")
                c["chart"].add(now, v)
            else:
                c["value"].setText("no sensor")
                c["status"].setText("Arduino reports the sensor is not responding")

    def disconnected(self):
        for k, c in self.cards.items():
            if self.enabled(k):
                c["value"].setText("—")
                c["status"].setText("controller not connected")

    def csv_values(self, d):
        """[flow_slm, flow_sensor_temp_c, humidity_pct, inlet_temp_c]; blank when switched off."""
        flow, hum, temp = self.enabled("FLOW"), self.enabled("HUM"), self.enabled("TEMP")
        return [d.get("FLOW") if flow else "", d.get("FTEMP") if flow else "",
                d.get("HUM") if hum else "", d.get("HTEMP") if temp else ""]

    def _repaint_charts(self):
        if self.isVisible():
            for c in self.cards.values():
                if c["box"].isChecked():
                    c["chart"].update()
