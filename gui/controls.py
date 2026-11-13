"""Manual tab buttons, raw command entry, and the ALL OFF button."""

from core.config import VALVE_IDEAL_MAX


class ManualControlsMixin:
    """Methods moved verbatim from the original App class."""

    def _toggle(self, key):
        on = bool(self.data.get(key))
        name = {"PUMP": "PUMP", "SOL": "SOLENOID", "BRIDGE": "BRIDGE"}[key]
        self.send(f"{name} {'OFF' if on else 'ON'}")

    def _manual_override(self, on):
        top = 100.0 if on else VALVE_IDEAL_MAX
        self.man_valve.setMaximum(top)
        self.man_valve_slider.setMaximum(int(top * 2))

    def _manual_valve(self):
        self.send(f"VALVE {self.man_valve.value():.1f}")

    def send_raw(self):
        cmd = self.raw_edit.text().strip()
        if cmd:
            self.send(cmd)
            self.raw_edit.clear()

    def all_off(self):
        if self.armed:
            self.abort("ALL OFF pressed")
        else:
            self.send("ALL OFF")
