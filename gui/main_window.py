"""Main window: shared state, timers, small UI helpers and shutdown.

App combines the mixins below. Each mixin holds one group of the original
App methods, unchanged, so every method still runs on the same object and
sees the same attributes it did in the single-file version.
"""

import queue
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from core.config import DATA_STALE_S, PING_MS, SENSOR_DEFAULTS, TICK_MS
from core.cycle import CycleMixin
from gui.board_panel import BoardMixin
from gui.controls import ManualControlsMixin
from gui.layout import LayoutMixin
from gui.persistence import PersistenceMixin
from gui.run_panel import RunControlMixin
from gui.sensor_panel import SensorMixin


class App(LayoutMixin, BoardMixin, SensorMixin, ManualControlsMixin, RunControlMixin,
          CycleMixin, PersistenceMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monroe Controller")
        self.resize(1180, 760)

        self.rx = queue.Queue()
        self.link = None
        self.data = {}
        self.data_time = 0.0
        self.history = []
        self.sensor_q = queue.Queue()
        self.sensor = None
        self.sensor_p = None       # latest pressure, kPa
        self.sensor_time = 0.0
        self.sensor_raw = ""

        self.state = "IDLE"
        self.armed = False
        self.cycles = 0
        self.state_t0 = time.time()
        self.ramp_f = 0
        self.ramp_next = 0.0
        self.ramp_done_t = None
        self.csv_file = None
        self.csv_writer = None
        self.detail_kind = "idle"   # idle | running | done | error

        self.fields = {}   # key -> (QLineEdit, type, lo, hi, label)
        self._saved_sensor_port = self._saved_board_port = ""
        self._build_ui()
        self._load_settings()
        self._set_connected_ui(False)
        self.refresh_ports()
        self._enter_state("IDLE")

        self._timer(30, self._drain_rx)
        self._timer(30, self._drain_sensor)
        self._timer(TICK_MS, self._tick)
        self._timer(PING_MS, self._ping)
        self._timer(500, self.chart.update)

    def _timer(self, ms, fn):
        t = QTimer(self)
        t.timeout.connect(fn)
        t.start(ms)
        return t

    # ------------------------------------------------------ UI helpers
    def append_log(self, text):
        self.log.appendPlainText(time.strftime("%H:%M:%S ") + text)

    def _set_connected_ui(self, connected):
        self._update_locks(connected)
        self.alloff_btn.setEnabled(connected)

    def _update_locks(self, connected=None):
        if connected is None:
            connected = self.link is not None and self.link.connected
        manual_ok = connected and not self.armed
        for w in self.manual_widgets + [self.raw_edit, self.raw_btn]:
            w.setEnabled(manual_ok)
        for e in list(self.recipe_edits.values()) + [self.vent_override]:
            e.setEnabled(not self.armed)
        self.start_btn.setEnabled(connected and not self.armed)
        self.abort_btn.setEnabled(self.armed)
        self.reset_btn.setEnabled(not self.armed)

    def _set_detail(self, text, kind):
        self.detail_kind = kind
        col = {"error": "#c62828", "done": "#2e7d32"}.get(kind, "")
        self.state_detail.setStyleSheet(f"color: {col};" if col else "")
        self.state_detail.setText(text)

    def get(self, key):
        edit, typ, lo, hi, label = self.fields[key]
        try:
            val = typ(float(edit.text()))
        except ValueError:
            raise ValueError(f"'{label}' must be a number.")
        if not lo <= val <= hi:
            raise ValueError(f"'{label}' must be between {lo} and {hi}.")
        return val

    def pressure(self):
        """Latest chamber pressure in kPa from the Omega sensor, or None if stale."""
        if self.sensor_p is None or time.time() - self.sensor_time > DATA_STALE_S:
            return None
        return self.sensor_p

    def _apply_sensor_defaults(self, saved=None):
        v = dict(SENSOR_DEFAULTS, **(saved or {}))
        self.s_baud.setCurrentText(str(v["sensor_baud"]))
        self.s_cmd.setText(str(v["sensor_cmd"]))
        self.s_eol.setCurrentText(str(v["sensor_eol"]))
        self.s_unit.setCurrentText(str(v["sensor_unit"]))
        self.s_poll.setValue(int(v["sensor_poll_ms"]))

    # ------------------------------------------------------ exit
    def closeEvent(self, ev):
        if self.armed:
            ans = QMessageBox.question(self, "Quit", "A treatment is running. Abort it and quit?")
            if ans != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self.abort("Closed by user")
        if self.link is not None and self.link.connected:
            self.send("ALL OFF")
            time.sleep(0.2)
            self.link.close()
        if self.sensor is not None:
            self.sensor.close()
        self._close_csv()
        self._save_settings()
        ev.accept()
