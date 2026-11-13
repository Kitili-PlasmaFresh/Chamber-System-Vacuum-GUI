"""Arduino controller: port list, connect/disconnect, sending commands,
incoming serial lines, live indicators and the watchdog heartbeat."""

import queue
import time

from PyQt6.QtWidgets import QMessageBox

from core.config import KV_RE, SIM_PORT, WATCHDOG_S
from hardware.serial_link import SerialLink, serial
from hardware.simulator import SimulatedBoard


class BoardMixin:
    """Methods moved verbatim from the original App class."""

    def refresh_ports(self):
        ports, likely = [], []
        if serial is not None:
            infos = serial.tools.list_ports.comports()
            ports = [p.device for p in infos]
            likely = [p.device for p in infos
                      if any(s in (p.description or "").lower() for s in ("arduino", "ch340", "usb"))]
        choices = ports + [SIM_PORT]
        board = self.port_box.currentText() or self._saved_board_port
        sens = self.sensor_port_box.currentText() or self._saved_sensor_port
        for box in (self.port_box, self.sensor_port_box):
            box.clear()
            box.addItems(choices)
        if board not in choices:
            board = likely[0] if likely else (ports[0] if ports else SIM_PORT)
        if sens not in choices:
            others = [p for p in ports if p != board]
            sens = others[0] if others else SIM_PORT
        self.port_box.setCurrentText(board)
        self.sensor_port_box.setCurrentText(sens)

    def toggle_connection(self):
        if self.link is not None and self.link.connected:
            self.disconnect()
            return
        port = self.port_box.currentText()
        if not port:
            QMessageBox.warning(self, "No port", "Select a serial port first.")
            return
        if port == SIM_PORT:
            self.link = SimulatedBoard(self.rx.put)
        elif serial is None:
            QMessageBox.critical(self, "pyserial missing", "Install it with:  pip install pyserial")
            return
        else:
            self.link = SerialLink(self.rx.put)
        try:
            self.link.open(port)
        except Exception as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            self.link = None
            return
        self.conn_btn.setText("Disconnect")
        self.conn_lbl.setText(f"Connected to {port}, waiting for board…")
        self.conn_lbl.setStyleSheet("color: #e65100;")
        self.port_box.setEnabled(False)
        self.append_log(f"--- connected to {port} ---")
        self._configure_board()
        self._set_connected_ui(True)

    def _configure_board(self):
        self.send(f"WATCHDOG {WATCHDOG_S}", quiet=True)
        self.send("STREAM 200", quiet=True)

    def disconnect(self, reason=None):
        if self.armed:
            self.abort(reason or "Disconnected")
        if self.link:
            self.link.close()
        self.link = None
        self.data = {}
        self.conn_btn.setText("Connect")
        self.conn_lbl.setText("Disconnected")
        self.conn_lbl.setStyleSheet("color: gray;")
        self.port_box.setEnabled(True)
        self.append_log("--- disconnected ---")
        self._set_connected_ui(False)

    def send(self, cmd, quiet=False):
        try:
            self.link.send(cmd)
            if not quiet:
                self.append_log(f"> {cmd}")
            return True
        except Exception as exc:
            self.append_log(f"! send failed ({cmd}): {exc}")
            return False

    def _drain_rx(self):
        try:
            for _ in range(200):
                self._handle_line(self.rx.get_nowait())
        except queue.Empty:
            pass

    def _handle_line(self, line):
        if line.startswith("__ERROR__"):
            self.append_log("! " + line[10:])
            self.disconnect("Serial connection lost")
            return
        if line.startswith("DATA "):
            parsed = {}
            for k, v in KV_RE.findall(line):
                try:
                    parsed[k] = float(v)
                except ValueError:
                    pass
            self.data = parsed
            self.data_time = time.time()
            self._on_data()
            return
        self.append_log(line)
        if line == "READY":
            self.conn_lbl.setText(f"Connected to {self.port_box.currentText()}")
            self.conn_lbl.setStyleSheet("color: green;")
            self._configure_board()
        elif line.startswith("WATCHDOG"):
            if self.armed:
                self.abort("Board watchdog tripped (lost contact with PC)")
        elif "GP8302 not detected" in line:
            QMessageBox.critical(self, "Hardware error", "The Arduino reports the GP8302 DAC is not "
                                 "detected. It halts until fixed and reset.")

    def _on_data(self):
        d = self.data
        for k in ("PUMP", "SOL", "BRIDGE"):
            on = bool(d.get(k))
            self.ind[k].setText("ON" if on else "OFF")
            self.ind[k].setStyleSheet("color: green; font-weight: bold;" if on else "color: gray;")
        self.ind["VALVE"].setText(f"{d.get('VALVE', 0):.1f} %")
        af = d.get("AFREQ", 0)
        self.ind["AFREQ"].setText(f"{af:,.0f} Hz" if af else "off")
        self.ind["AFREQ"].setStyleSheet("color: green; font-weight: bold;" if af else "color: gray;")

    def _ping(self):
        if self.link is not None and self.link.connected:
            self.send("PING", quiet=True)
