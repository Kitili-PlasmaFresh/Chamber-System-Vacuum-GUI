"""Omega PX409/PXM409-USBH pressure transmitter on its own USB virtual COM port."""

import re
import threading
import time

from hardware.serial_link import serial


class PressureSensor:
    """Omega PX409/PXM409-USBH transmitter on its own USB virtual COM port.

    Polls with an ASCII read command and takes the first number in each reply
    as the pressure, in the unit chosen on the Pressure sensor tab.
    Results go to the queue as ("P", kpa, raw_text), ("RAW", text) or ("ERR", msg).
    """

    NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

    def __init__(self, out_queue):
        self.q = out_queue
        self.ser = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port, baud, cmd, eol, unit_factor, period_s):
        self.cmd, self.eol, self.factor, self.period = cmd, eol, unit_factor, period_s
        self.ser = serial.Serial(port, int(baud), timeout=0.05)
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def close(self):
        self._stop.set()
        with self._lock:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    def query(self, cmd, timeout=0.6):
        """Send one command, return the first non-empty reply line ('' on timeout)."""
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write((cmd + self.eol).encode("ascii"))
            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                b = self.ser.read(1)
                if not b:
                    continue
                if b in (b"\r", b"\n"):
                    if buf.strip():
                        break
                    continue
                buf += b
        text = buf.decode("ascii", "replace").strip()
        if text.upper().startswith(cmd.upper()) and len(text) > len(cmd):
            text = text[len(cmd):].strip()   # drop an echoed command
        return text

    def parse(self, text):
        m = self.NUM_RE.search(text)
        return None if m is None else float(m.group()) * self.factor

    def _run(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                text = self.query(self.cmd)
            except Exception as exc:
                if not self._stop.is_set():
                    self.q.put(("ERR", str(exc)))
                return
            kpa = self.parse(text) if text else None
            self.q.put(("P", kpa, text) if kpa is not None else ("RAW", text or "(no reply)"))
            self._stop.wait(max(0.0, self.period - (time.time() - t0)))
