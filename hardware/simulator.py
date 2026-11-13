"""SIMULATOR port: a pretend Arduino with a toy chamber model, and a pretend Omega sensor."""

import random
import threading
import time

from hardware.pressure_sensor import PressureSensor


class SimulatedBoard:
    """Pretend Arduino running the same command set, with a toy chamber model.
    The chamber pressure (self.p, kPa) is read by SimulatedSensor."""

    AMBIENT = 101.3

    def __init__(self, on_line):
        self.on_line = on_line
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._connected = False

    @property
    def connected(self):
        return self._connected

    def open(self, _port):
        self.p = self.AMBIENT
        self.s = dict(SOL=0, PUMP=0, BRIDGE=0, VALVE=0.0, FREQ=0, AFREQ=0.0)
        self.stream_ms = 200
        self._connected = True
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def close(self):
        self._stop.set()
        self._connected = False

    def send(self, cmd):
        if not self._connected:
            raise IOError("Not connected")
        c = cmd.strip().upper()
        out = []
        with self._lock:
            s = self.s
            if c in ("PING", ""):
                pass
            elif c == "STATUS":
                out.append(self._data())
            elif c in ("SOLENOID ON", "SOLENOID OFF"):
                s["SOL"] = int(c.endswith("ON")); out.append(f"Solenoid: {c[9:]}")
            elif c in ("PUMP ON", "PUMP OFF"):
                s["PUMP"] = int(c.endswith("ON")); out.append(f"Pump: {c[5:]}")
            elif c in ("BRIDGE ON", "BRIDGE OFF"):
                s["BRIDGE"] = int(c.endswith("ON")); out.append(f"Bridge: {c[7:]}")
            elif c == "ALL OFF":
                s.update(SOL=0, PUMP=0, BRIDGE=0, VALVE=0.0, FREQ=0, AFREQ=0.0)
                out += ["Bridge: OFF", "Gate: OFF", "Pump: OFF", "Valve: 0.0%", "Solenoid: OFF"]
            elif c.startswith("FREQ "):
                f = int(c[5:]); s["FREQ"] = f
                if f:
                    top = round(16e6 / f) - 1
                    s["AFREQ"] = 16e6 / (top + 1)
                    out.append(f"Gate frequency: {s['AFREQ']:.1f} Hz")
                else:
                    s["AFREQ"] = 0.0; out.append("Gate: OFF")
            elif c.startswith("STREAM "):
                self.stream_ms = int(c[7:])
            elif c.startswith("WATCHDOG "):
                pass
            else:
                v = c[6:] if c.startswith("VALVE ") else c
                try:
                    s["VALVE"] = float(v); out.append(f"Valve: {s['VALVE']:.1f}%")
                except ValueError:
                    out.append("ERROR: Invalid command.")
        for line in out:
            self.on_line(line)

    def _data(self):
        s = self.s
        return (f"DATA MS={int(time.time() * 1000) % 10**9} SOL={s['SOL']} PUMP={s['PUMP']} "
                f"BRIDGE={s['BRIDGE']} VALVE={s['VALVE']:.1f} FREQ={s['FREQ']} "
                f"AFREQ={s['AFREQ']:.1f}")

    def _run(self):
        time.sleep(0.5)
        for line in ("Monroe Controller (simulator)", "GP8302 detected at 0x58.", "READY"):
            self.on_line(line)
        last = time.time()
        next_data = last
        while not self._stop.is_set():
            time.sleep(0.02)
            now = time.time()
            dt, last = now - last, now
            with self._lock:
                s = self.s
                if s["PUMP"]:
                    self.p += -(self.p - 1.0) * dt / 4.0          # pump down, tau 4 s
                if s["SOL"] and s["VALVE"] > 0:
                    self.p += (self.AMBIENT - self.p) * dt * s["VALVE"] / 30.0 / 2.0
                elif not s["PUMP"]:
                    self.p += (self.AMBIENT - self.p) * dt / 600.0  # small leak
                if self.stream_ms and now >= next_data:
                    next_data = now + self.stream_ms / 1000.0
                    line = self._data()
                else:
                    line = None
            if line:
                self.on_line(line)


class SimulatedSensor(PressureSensor):
    """Stands in for the Omega transmitter. Reports the simulated chamber's
    pressure (in bar) when the controller is also the simulator."""

    def __init__(self, out_queue, chamber):
        super().__init__(out_queue)
        self.chamber = chamber          # callable -> kPa
        self._on = False

    @property
    def connected(self):
        return self._on

    def open(self, port, baud, cmd, eol, unit_factor, period_s):
        self.cmd, self.eol, self.factor, self.period = cmd, eol, unit_factor, period_s
        self._on = True
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def close(self):
        self._stop.set()
        self._on = False

    def query(self, cmd, timeout=0.6):
        if cmd.upper() == "ENQ":
            return "PXM409-3.5BAUSBH SIMULATOR 0-3.5 bar abs"
        kpa = self.chamber() + random.uniform(-0.05, 0.05)
        return f"{kpa / self.factor:.5f}"
