"""Omega pressure sensor: connect/disconnect, Test sensor, and handling readings."""

import queue
import threading
import time

from PyQt6.QtWidgets import QMessageBox

from core.config import CHART_SECONDS, DATA_STALE_S, SENSOR_EOLS, SENSOR_UNITS, SIM_PORT
from hardware.pressure_sensor import PressureSensor
from hardware.serial_link import serial
from hardware.simulator import SimulatedBoard, SimulatedSensor


class SensorMixin:
    """Methods moved verbatim from the original App class."""

    def toggle_sensor(self):
        if self.sensor is not None and self.sensor.connected:
            self.disconnect_sensor()
            return
        port = self.sensor_port_box.currentText()
        if port and port == self.port_box.currentText() and port != SIM_PORT:
            QMessageBox.warning(self, "Same port", "The sensor and the Arduino can't share a port.")
            return
        try:
            factor = SENSOR_UNITS[self.s_unit.currentText()]
            baud = int(self.s_baud.currentText())
        except (KeyError, ValueError):
            QMessageBox.warning(self, "Sensor settings", "Check the baud rate and unit.")
            return
        if port == SIM_PORT:
            self.sensor = SimulatedSensor(
                self.sensor_q,
                lambda: self.link.p if isinstance(self.link, SimulatedBoard) and self.link.connected
                else SimulatedBoard.AMBIENT)
        elif serial is None:
            QMessageBox.critical(self, "pyserial missing", "Install it with:  pip install pyserial")
            return
        else:
            self.sensor = PressureSensor(self.sensor_q)
        try:
            self.sensor.open(port, baud, self.s_cmd.text().strip(),
                             SENSOR_EOLS[self.s_eol.currentText()], factor, self.s_poll.value() / 1000.0)
        except Exception as exc:
            QMessageBox.critical(self, "Sensor connection failed", str(exc))
            self.sensor = None
            return
        self.sensor_btn.setText("Disconnect")
        self.sensor_lbl.setText(f"Connected to {port}, waiting for readings…")
        self.sensor_lbl.setStyleSheet("color: #e65100;")
        self.sensor_port_box.setEnabled(False)
        for w in self.sensor_widgets:
            w.setEnabled(False)
        self.append_log(f"--- pressure sensor connected on {port} ---")

    def disconnect_sensor(self, reason=None):
        if self.armed:
            self.abort(reason or "Pressure sensor disconnected")
        if self.sensor:
            self.sensor.close()
        self.sensor = None
        self.sensor_p = None
        self.sensor_btn.setText("Connect")
        self.sensor_lbl.setText("Disconnected")
        self.sensor_lbl.setStyleSheet("color: gray;")
        self.sensor_port_box.setEnabled(True)
        for w in self.sensor_widgets:
            w.setEnabled(not self.armed)
        self.pv_lbl.setText("sensor: not connected")
        self.append_log("--- pressure sensor disconnected ---")

    def test_sensor(self):
        if self.sensor is None or not self.sensor.connected:
            QMessageBox.information(self, "Test sensor", "Connect the pressure sensor first.")
            return
        cmd = self.s_cmd.text().strip()

        def worker():
            for c in ("ENQ", cmd):
                try:
                    reply = self.sensor.query(c, timeout=1.0)
                except Exception as exc:
                    reply = f"error: {exc}"
                self.sensor_q.put(("LOG", f"sensor test  > {c}   < {reply!r}"))
        threading.Thread(target=worker, daemon=True).start()

    def _drain_sensor(self):
        try:
            for _ in range(100):
                self._handle_sensor(self.sensor_q.get_nowait())
        except queue.Empty:
            pass
        if self.sensor is not None and self.sensor.connected:
            stale = time.time() - self.sensor_time > DATA_STALE_S
            if stale and self.sensor_lbl.styleSheet() == "color: green;":
                self.sensor_lbl.setText("No readings: check port, baud and command")
                self.sensor_lbl.setStyleSheet("color: #c62828;")

    def _handle_sensor(self, item):
        kind = item[0]
        if kind == "LOG":
            self.append_log(item[1])
            return
        if kind == "ERR":
            self.append_log(f"! pressure sensor: {item[1]}")
            self.disconnect_sensor("Pressure sensor connection lost")
            return
        if kind == "RAW":
            self.sensor_raw = item[1]
            self.s_raw_lbl.setText(f"Last reply: {item[1]!r} (no number found)")
            self.pv_lbl.setText(f"sensor reply: {item[1]!r}")
            return
        _k, kpa, raw = item
        now = time.time()
        self.sensor_p, self.sensor_time, self.sensor_raw = kpa, now, raw
        self.s_raw_lbl.setText(f"Last reply: {raw!r}")
        if self.sensor_lbl.styleSheet() != "color: green;":
            self.sensor_lbl.setText(f"Reading on {self.sensor_port_box.currentText()}")
            self.sensor_lbl.setStyleSheet("color: green;")
        self.history.append((now, kpa))
        while self.history and now - self.history[0][0] > CHART_SECONDS:
            self.history.pop(0)
        self.p_lbl.setText(f"{kpa:.2f} kPa")
        self.pv_lbl.setText(f"{kpa / 100:.4f} bar   (sensor sent {raw!r} {self.s_unit.currentText()})")
        if self.csv_writer:
            d = self.data
            self.csv_writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), f"{now:.2f}", self.cycles + 1,
                                      self.state, f"{kpa:.3f}", raw, int(d.get("PUMP", 0)),
                                      int(d.get("SOL", 0)), d.get("VALVE"), int(d.get("BRIDGE", 0)),
                                      d.get("AFREQ")])
