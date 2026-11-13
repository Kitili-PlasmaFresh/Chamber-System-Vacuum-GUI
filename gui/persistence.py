"""Files on disk: monroe_settings.json and the optional per-run CSV recording."""

import csv
import json
import time

from PyQt6.QtWidgets import QFileDialog

from core.config import SENSOR_DEFAULTS, SETTINGS_FILE


class PersistenceMixin:
    """Methods moved verbatim from the original App class."""

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return
        for key, (edit, *_rest) in self.fields.items():
            if key in saved:
                edit.setText(str(saved[key]))
        self.vent_override.setChecked(bool(saved.get("vent_override", False)))
        self.cycles = int(saved.get("cycles_done", 0))
        self._apply_sensor_defaults({k: saved[k] for k in SENSOR_DEFAULTS if k in saved})
        self._saved_sensor_port = saved.get("sensor_port", "")
        self._saved_board_port = saved.get("board_port", "")

    def _save_settings(self):
        out = {k: v[0].text() for k, v in self.fields.items()}
        out["vent_override"] = self.vent_override.isChecked()
        out["cycles_done"] = self.cycles
        out.update(sensor_baud=self.s_baud.currentText(), sensor_cmd=self.s_cmd.text(),
                   sensor_eol=self.s_eol.currentText(), sensor_unit=self.s_unit.currentText(),
                   sensor_poll_ms=self.s_poll.value(), sensor_port=self.sensor_port_box.currentText(),
                   board_port=self.port_box.currentText())
        try:
            with open(SETTINGS_FILE, "w") as fh:
                json.dump(out, fh, indent=2)
        except OSError as exc:
            self.append_log(f"! could not save settings: {exc}")

    def _open_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save run data", time.strftime("monroe_run_%Y%m%d_%H%M%S.csv"), "CSV (*.csv)")
        if not path:
            return
        self.csv_file = open(path, "w", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["time", "epoch_s", "cycle", "state", "pressure_kpa", "sensor_reply",
                                  "pump", "solenoid", "valve_pct", "bridge", "gate_hz"])
        self.append_log(f"Recording to {path}")

    def _close_csv(self):
        if self.csv_file:
            self.csv_file.close()
        self.csv_file = self.csv_writer = None
