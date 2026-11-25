"""Tabs for the extra sensors the Arduino streams in its DATA line.

InputSensorsTab:       inlet flow rate and temperature from the SFM4300-50-P (I2C),
                       inlet humidity from the CHT832X (I2C).
ChamberTempsTab:       Chamber Temp Sensors 1-3, MAX31855 thermocouple converters
                       (SPI, CS on D3/D4/D5).

Each reading can be switched on or off; a switched-off reading is not displayed, plotted or
written to the CSV.
"""

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from core.config import CHART_SECONDS

# key, title, DATA field, sensor-present flag, unit, decimals, trace colour
INLET_READINGS = [
    ("FLOW", "Flow rate", "FLOW", "FLOWOK", "slm", 2, "#1565c0"),
    ("HUM", "Humidity", "HUM", "HUMOK", "%RH", 1, "#00838f"),
    ("TEMP", "Temperature", "FTEMP", "FLOWOK", "°C", 1, "#e65100"),   # SFM4300 gas temperature
]

# key, label, DATA field (TCn; flags TCnOK and fault bits TCnF), trace colour
CHAMBER_TEMPS = [
    ("TC1", "Chamber Temp Sensor 1", "TC1", "#c62828"),
    ("TC2", "Chamber Temp Sensor 2", "TC2", "#6a1b9a"),
    ("TC3", "Chamber Temp Sensor 3", "TC3", "#2e7d32"),
]

# MAX31855 fault bits as reported in TCnF by the firmware
TC_FAULTS = [(1, "open circuit (thermocouple not connected?)"), (2, "shorted to GND"),
             (4, "shorted to VCC"), (8, "no response from MAX31855")]

VALUE_STYLE = "font-size: 22px; font-weight: bold;"


def tc_fault_text(bits):
    names = [text for bit, text in TC_FAULTS if int(bits) & bit]
    return ", ".join(names) if names else "fault"


class TrendChart(QWidget):
    """Small rolling line chart with one or more series, auto-scaled to the visible data."""

    def __init__(self, unit, colours):
        super().__init__()
        self.unit = unit
        self.colours = dict(colours)                  # series key -> colour
        self.series = {k: [] for k in self.colours}   # series key -> [(epoch_s, value)]
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add(self, key, t, v):
        hist = self.series[key]
        hist.append((t, v))
        while hist and t - hist[0][0] > CHART_SECONDS:
            hist.pop(0)

    def clear(self, key):
        self.series[key].clear()

    def paintEvent(self, _ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        qp.fillRect(0, 0, w, h, QColor("white"))
        L, R, T, B = 48, 10, 8, 18
        vals = [v for hist in self.series.values() for _t, v in hist]
        lo, hi = (min(vals), max(vals)) if vals else (0.0, 1.0)
        pad = max((hi - lo) * 0.1, 0.5)
        lo, hi = lo - pad, hi + pad

        def y(v):
            return T + (h - T - B) * (1 - (v - lo) / (hi - lo))

        small = QFont(qp.font())
        small.setPointSize(8)
        qp.setFont(small)
        for frac in (0, 0.25, 0.5, 0.75, 1) if h > 250 else (0, 0.5, 1):
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
        now = time.time()
        for key, hist in self.series.items():
            if len(hist) > 1:
                poly = QPolygonF([QPointF(L + (w - L - R) * (1 - (now - t) / CHART_SECONDS), y(v))
                                  for t, v in hist])
                qp.setPen(QPen(QColor(self.colours[key]), 2))
                qp.drawPolyline(poly)
        qp.end()


def _note(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: gray;")
    return lbl


class InputSensorsTab(QWidget):
    """Inlet flow rate, humidity and temperature: one card and chart per reading."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = self._lay = QVBoxLayout(body)
        lay.addWidget(_note("Inlet gas sensors on the Arduino I2C bus. Untick a reading to stop "
                            "monitoring it: it is no longer shown, plotted or recorded to CSV."))

        self.cards = {}
        for key, title, field, ok_key, unit, dec, colour in INLET_READINGS:
            box = QGroupBox(f"Inlet {title.lower()}")
            box.setCheckable(True)
            box.setChecked(True)
            bl = QVBoxLayout(box)
            row = QHBoxLayout()
            value = QLabel("—")
            value.setStyleSheet(VALUE_STYLE)
            value.setMinimumWidth(160)
            status = QLabel("")
            status.setStyleSheet("color: gray;")
            row.addWidget(value)
            row.addWidget(status, 1)
            bl.addLayout(row)
            chart = TrendChart(unit, {key: colour})
            bl.addWidget(chart, 1)
            box.toggled.connect(lambda on, k=key: self._toggled(k, on))
            lay.addWidget(box, 1)
            self.cards[key] = dict(box=box, value=value, status=status, chart=chart,
                                   field=field, ok_key=ok_key, unit=unit, dec=dec)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._repaint_charts)
        self._timer.start(500)

    def enabled(self, key):
        return self.cards[key]["box"].isChecked()

    def _toggled(self, key, on):
        c = self.cards[key]
        c["chart"].setVisible(on)
        c["status"].setVisible(on)
        self._lay.setStretchFactor(c["box"], 1 if on else 0)   # collapse when off
        if on:
            c["value"].setText("—")
            c["value"].setStyleSheet(VALUE_STYLE)
        else:
            c["chart"].clear(key)
            c["value"].setText("Off")
            c["value"].setStyleSheet(VALUE_STYLE + " color: gray;")

    def get_state(self):
        return {k: self.enabled(k) for k in self.cards}

    def set_state(self, saved):
        for k, on in (saved or {}).items():
            if k in self.cards:
                self.cards[k]["box"].setChecked(bool(on))

    def update_data(self, d):
        """Called with each parsed DATA line from the Arduino."""
        now = time.time()
        for key, c in self.cards.items():
            if not c["box"].isChecked():
                continue
            if c["ok_key"] not in d:
                c["value"].setText("—")
                c["status"].setText("not reported by the connected firmware")
            elif d[c["ok_key"]] and c["field"] in d:
                v = round(d[c["field"]], c["dec"]) or 0.0      # no "-0.00"
                c["value"].setText(f"{v:.{c['dec']}f} {c['unit']}")
                c["status"].setText("")
                c["chart"].add(key, now, v)
            else:
                c["value"].setText("no sensor")
                c["status"].setText("Arduino reports the sensor is not responding")

    def disconnected(self):
        for k, c in self.cards.items():
            if self.enabled(k):
                c["value"].setText("—")
                c["status"].setText("controller not connected")

    def csv_values(self, d):
        """[flow_slm, inlet_temp_c, humidity_pct, humidity_sensor_temp_c]; blank when switched off.
        Inlet temperature comes from the SFM4300; the CHT832X's own temperature is logged with
        humidity."""
        flow, hum, temp = self.enabled("FLOW"), self.enabled("HUM"), self.enabled("TEMP")
        return [d.get("FLOW") if flow else "", d.get("FTEMP") if temp else "",
                d.get("HUM") if hum else "", d.get("HTEMP") if hum else ""]

    def _repaint_charts(self):
        if self.isVisible():
            for c in self.cards.values():
                if c["box"].isChecked():
                    c["chart"].update()


class ChamberTempsTab(QWidget):
    """Chamber Temp Sensors 1-3 (MAX31855): one row per sensor, all on one chart."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_note("MAX31855 thermocouple converters on the Arduino SPI bus "
                            "(MISO D12, SCK D13, CS D3 / D4 / D5). Untick a sensor to stop "
                            "monitoring it: it is no longer shown, plotted or recorded to CSV."))

        grid = QGridLayout()
        lay.addLayout(grid)
        self.chart = TrendChart("°C", {k: col for k, _l, _f, col in CHAMBER_TEMPS})
        self.tcs = {}
        for row, (key, label, field, colour) in enumerate(CHAMBER_TEMPS):
            chk = QCheckBox(label)
            chk.setChecked(True)
            chk.setStyleSheet(f"color: {colour}; font-weight: bold; font-size: 14px;")
            value = QLabel("—")
            value.setStyleSheet(VALUE_STYLE)
            value.setMinimumWidth(140)
            status = QLabel("")
            status.setStyleSheet("color: gray;")
            grid.addWidget(chk, row, 0)
            grid.addWidget(value, row, 1)
            grid.addWidget(status, row, 2)
            chk.toggled.connect(lambda on, k=key: self._toggled(k, on))
            self.tcs[key] = dict(chk=chk, value=value, status=status, field=field)
        grid.setColumnStretch(2, 1)
        lay.addWidget(self.chart, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._repaint_chart)
        self._timer.start(500)

    def enabled(self, key):
        return self.tcs[key]["chk"].isChecked()

    def _toggled(self, key, on):
        t = self.tcs[key]
        t["status"].setText("")
        if on:
            t["value"].setText("—")
            t["value"].setStyleSheet(VALUE_STYLE)
        else:
            self.chart.clear(key)
            t["value"].setText("Off")
            t["value"].setStyleSheet(VALUE_STYLE + " color: gray;")

    def get_state(self):
        return {k: self.enabled(k) for k in self.tcs}

    def set_state(self, saved):
        for k, on in (saved or {}).items():
            if k in self.tcs:
                self.tcs[k]["chk"].setChecked(bool(on))

    def update_data(self, d):
        """Called with each parsed DATA line from the Arduino."""
        now = time.time()
        for key, t in self.tcs.items():
            if not t["chk"].isChecked():
                continue
            f = t["field"]
            if f + "OK" not in d:
                t["value"].setText("—")
                t["status"].setText("not reported by the connected firmware")
            elif d[f + "OK"] and f in d:
                v = round(d[f], 2) or 0.0
                t["value"].setText(f"{v:.2f} °C")
                t["status"].setText("")
                self.chart.add(key, now, v)
            else:
                t["value"].setText("fault")
                t["status"].setText(tc_fault_text(d.get(f + "F", 0)))

    def disconnected(self):
        for k, t in self.tcs.items():
            if self.enabled(k):
                t["value"].setText("—")
                t["status"].setText("controller not connected")

    def csv_values(self, d):
        """[chamber_temp_1_c, chamber_temp_2_c, chamber_temp_3_c]; blank when off or faulted."""
        return [d.get(t["field"]) if self.enabled(k) and d.get(t["field"] + "OK") else ""
                for k, t in self.tcs.items()]

    def _repaint_chart(self):
        if self.isVisible():
            self.chart.update()
