"""Treatment-cycle buttons: Start Treatment, Abort, Reset count, and the cycle counter."""

from PyQt6.QtWidgets import QMessageBox

from core.config import VALVE_IDEAL_MAX


class RunControlMixin:
    """Methods moved verbatim from the original App class."""

    def start_run(self):
        try:
            for k in self.fields:
                self.get(k)
            if self.get("vent_valve") > VALVE_IDEAL_MAX and not self.vent_override.isChecked():
                raise ValueError("Vent valve % is above the 0-30 % ideal range. "
                                 "Lower it or tick the override on the Recipe tab.")
            if self.get("target_pressure") >= self.get("ambient_pressure") - self.get("ambient_tol"):
                raise ValueError("Target pressure must be below ambient pressure minus tolerance.")
        except ValueError as exc:
            QMessageBox.warning(self, "Check recipe", str(exc))
            return
        if self.pressure() is None:
            QMessageBox.warning(self, "No sensor data", "No readings from the pressure sensor. Connect it on the second row at the top "
                                "and check the Pressure sensor tab.")
            return
        if self.cycles >= self.get("target_cycles"):
            ans = QMessageBox.question(self, "Target reached",
                                       f"{self.cycles} cycles already done (target "
                                       f"{self.get('target_cycles')}). Reset the count and start?")
            if ans != QMessageBox.StandardButton.Yes:
                return
            self.cycles = 0
        self._save_settings()
        if self.csv_chk.isChecked():
            self._open_csv()
        self.armed = True
        self.append_log(f"=== Treatment started: {self.get('target_cycles')} cycle(s) ===")
        self._update_locks()

    def abort(self, reason):
        self.send("ALL OFF")
        was = self.armed
        self.armed = False
        self._enter_state("IDLE")
        self._close_csv()
        self._update_locks()
        self.append_log(f"!!! {reason}: everything switched OFF")
        if was:
            self._set_detail(f"Stopped: {reason}", "error")
            if reason not in ("Aborted by user", "ALL OFF pressed"):
                QMessageBox.critical(self, "Treatment aborted", f"{reason}.\nAll outputs were switched off.")

    def reset_cycles(self):
        self.cycles = 0
        self._save_settings()
        self._show_cycles()

    def _show_cycles(self):
        try:
            tgt = self.get("target_cycles")
        except ValueError:
            tgt = "?"
        self.cycle_lbl.setText(f"Cycles: {self.cycles} / {tgt}")
