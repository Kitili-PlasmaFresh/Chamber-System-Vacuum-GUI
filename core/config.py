"""Shared constants: serial settings, timing, sensor options, recipe fields, cycle states."""

import os
import re

BAUD = 115200
VALVE_IDEAL_MAX = 30.0
FREQ_MAX = 40000
SIM_PORT = "SIMULATOR (no hardware)"
# Same location as before the refactor: next to monroe_gui.py (one level above this package).
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(APP_DIR, "monroe_settings.json")

TICK_MS = 100            # state-machine tick
PING_MS = 1000           # heartbeat to the firmware watchdog
WATCHDOG_S = 5           # firmware turns everything off if the GUI goes quiet
DATA_STALE_S = 2.0       # abort a running cycle if pressure readings stop

# Omega USBH transmitter defaults (editable on the Pressure sensor tab)
SENSOR_BAUDS = ["115200", "9600", "19200", "38400", "57600"]
SENSOR_EOLS = {"CR": "\r", "CRLF": "\r\n", "LF": "\n"}
# multiply a reading in this unit by the factor to get kPa
SENSOR_UNITS = {"bar": 100.0, "mbar": 0.1, "kPa": 1.0, "Pa": 0.001, "psi": 6.894757,
                "Torr": 0.1333224, "inHg": 3.386389, "atm": 101.325}
SENSOR_DEFAULTS = dict(sensor_baud="115200", sensor_cmd="P", sensor_eol="CR",
                       sensor_unit="bar", sensor_poll_ms=200)
CHART_SECONDS = 180

KV_RE = re.compile(r"(\w+)=([-\d.]+)")

# Recipe / calibration fields: key -> (label, default, type, min, max)
RECIPE_FIELDS = [
    ("target_cycles", "Target cycles", 1, int, 1, 10000),
    ("target_pressure", "Target (evacuated) pressure, kPa", 10.0, float, 0, 200),
    ("evac_wait", "Wait t1 after evacuation, s", 5.0, float, 0, 3600),
    ("evac_timeout", "Evacuation timeout, s", 300.0, float, 1, 36000),
    ("target_freq", "Target gate frequency, Hz", 20000, int, 1, FREQ_MAX),
    ("ramp_start", "Ramp start frequency, Hz", 1000, int, 1, FREQ_MAX),
    ("ramp_step", "Ramp step, Hz (0 = no ramp)", 1000, int, 0, FREQ_MAX),
    ("ramp_interval", "Ramp step interval, ms", 100, int, 20, 10000),
    ("treat_time", "Treatment time (plasma on), s", 60.0, float, 0.1, 86400),
    ("vent_valve", "Vent: solenoid valve opening, %", 20.0, float, 0, 100),
    ("ambient_pressure", "Ambient pressure, kPa", 101.3, float, 0, 200),
    ("ambient_tol", "Ambient tolerance, kPa", 2.0, float, 0, 50),
    ("vent_wait", "Wait t2 after ambient reached, s", 5.0, float, 0, 3600),
    ("vent_timeout", "Venting timeout, s", 300.0, float, 1, 36000),
]

# Cycle states, in flowchart order. (key, label shown in the step list)
STATES = [
    ("IDLE", "Idle"),
    ("EVACUATE", "Chamber evacuation: pump ON"),
    ("EVAC_WAIT", "Pump OFF, wait t1"),
    ("FREQ_RAMP", "Ramp gate to target frequency"),
    ("PLASMA", "Half-bridge ON: plasma engaged"),
    ("VENT", "Valve to target %, wait ambient"),
    ("VENT_WAIT", "Ambient reached, wait t2"),
    ("DISENGAGE", "Half-bridge OFF, cycles += 1"),
]
STATE_LABEL = dict(STATES)
