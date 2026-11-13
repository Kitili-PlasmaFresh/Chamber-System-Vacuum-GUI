"""Treatment-cycle state machine (flowchart steps IDLE -> ... -> DISENGAGE).

Mixed into gui.main_window.App. It drives the hardware only through
self.send(), reads the recipe through self.get() and the chamber pressure
through self.pressure(), and stops through self.abort().
"""

import math
import time

from core.config import STATE_LABEL


class CycleMixin:
    """Methods moved verbatim from the original App class."""

    def _enter_state(self, state):
        self.state = state
        self.state_t0 = time.time()
        for key, lbl in self.step_lbls.items():
            lbl.setStyleSheet("background:#1565c0; color:white; font-weight:bold; padding:2px;"
                              if key == state else "padding:2px;")
        if self.armed and state != "IDLE":
            self.append_log(f"[cycle {self.cycles + 1}] {STATE_LABEL[state]}")

    def _elapsed(self):
        return time.time() - self.state_t0

    def _tick(self):
        try:
            self._step()
        except Exception as exc:  # never leave hardware running on a bug
            if self.armed:
                self.abort(f"Internal error: {exc}")
            else:
                self.append_log(f"! {exc}")
        self._show_cycles()

    def _step(self):
        st = self.state
        if not self.armed:
            if st != "IDLE":
                self._enter_state("IDLE")
            if self.detail_kind in ("idle", "running"):
                self._set_detail("Idle. Press Start Treatment to run the recipe.", "idle")
            return

        p = self.pressure()
        if p is None or math.isnan(p):
            self.abort("Lost readings from the pressure sensor")
            return
        el = self._elapsed()
        g = self.get

        if st == "IDLE":
            # Cycles >= Target?  True -> stay idle (run complete)
            if self.cycles >= g("target_cycles"):
                self.armed = False
                self._close_csv()
                self._update_locks()
                self.append_log(f"=== Treatment complete: {self.cycles} cycle(s) ===")
                self._set_detail(f"Complete: {self.cycles} cycle(s) done.", "done")
                return
            # Start Treatment? True -> Chamber Evacuation
            for cmd in ("BRIDGE OFF", "FREQ 0", "VALVE 0", "SOLENOID OFF", "PUMP ON"):
                self.send(cmd)
            self._enter_state("EVACUATE")

        elif st == "EVACUATE":
            self._detail(f"Pumping down: {p:.1f} kPa → target {g('target_pressure'):.1f} kPa", el)
            if p <= g("target_pressure"):
                self.send("PUMP OFF")
                self._enter_state("EVAC_WAIT")
            elif el > g("evac_timeout"):
                self.abort(f"Evacuation timeout: {p:.1f} kPa after {el:.0f} s")

        elif st == "EVAC_WAIT":
            self._detail(f"Waiting t1: {max(0, g('evac_wait') - el):.1f} s left", el)
            if el >= g("evac_wait"):
                target = g("target_freq")
                self.ramp_f = target if g("ramp_step") == 0 else min(g("ramp_start"), target)
                self.send(f"FREQ {self.ramp_f}")
                self.ramp_next = time.time() + g("ramp_interval") / 1000.0
                self.ramp_done_t = None
                self._enter_state("FREQ_RAMP")

        elif st == "FREQ_RAMP":
            target = g("target_freq")
            if self.ramp_f < target and time.time() >= self.ramp_next:
                self.ramp_f = min(target, self.ramp_f + g("ramp_step"))
                self.send(f"FREQ {self.ramp_f}", quiet=self.ramp_f != target)
                self.ramp_next = time.time() + g("ramp_interval") / 1000.0
            af = self.data.get("AFREQ", 0)
            self._detail(f"Gate {af:,.0f} Hz → target {target:,} Hz", el)
            # HBridge frequency == target frequency? (board-reported, within 1 %)
            if self.ramp_f == target:
                if self.ramp_done_t is None:
                    self.ramp_done_t = time.time()
                if abs(af - target) <= max(0.01 * target, 1.0):
                    self.send("BRIDGE ON")
                    self._enter_state("PLASMA")
                elif time.time() - self.ramp_done_t > 3.0:
                    self.abort(f"Gate frequency did not reach {target} Hz (board reports {af:.0f} Hz)")

        elif st == "PLASMA":
            left = g("treat_time") - el
            self._detail(f"Plasma ON: {max(0, left):.1f} s left of {g('treat_time'):g} s", el)
            if el >= g("treat_time"):
                self.send("SOLENOID ON")
                self.send(f"VALVE {g('vent_valve'):.1f}")
                self._enter_state("VENT")

        elif st == "VENT":
            amb = g("ambient_pressure") - g("ambient_tol")
            self._detail(f"Venting: {p:.1f} kPa → ambient ≥ {amb:.1f} kPa", el)
            if p >= amb:
                self._enter_state("VENT_WAIT")
            elif el > g("vent_timeout"):
                self.abort(f"Venting timeout: {p:.1f} kPa after {el:.0f} s")

        elif st == "VENT_WAIT":
            self._detail(f"Waiting t2: {max(0, g('vent_wait') - el):.1f} s left", el)
            if el >= g("vent_wait"):
                for cmd in ("BRIDGE OFF", "FREQ 0", "VALVE 0", "SOLENOID OFF"):
                    self.send(cmd)
                self._enter_state("DISENGAGE")

        elif st == "DISENGAGE":
            self.cycles += 1
            self._save_settings()
            self.append_log(f"Cycle {self.cycles} complete")
            self._enter_state("IDLE")

    def _detail(self, text, el):
        self._set_detail(f"{text}   (step {el:.0f} s)", "running")
