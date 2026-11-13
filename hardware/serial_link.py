"""Arduino controller over USB serial: background reader thread + thread-safe writer."""

import threading

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # still lets the simulator run
    serial = None

from core.config import BAUD


class SerialLink:
    """Real board: background reader thread + thread-safe writer."""

    def __init__(self, on_line):
        self.ser = None
        self.on_line = on_line
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port):
        self.ser = serial.Serial(port, BAUD, timeout=0.2)
        self._stop.clear()
        threading.Thread(target=self._read_loop, daemon=True).start()

    def close(self):
        self._stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def send(self, cmd):
        if not self.connected:
            raise IOError("Not connected")
        with self._lock:
            self.ser.write((cmd.strip() + "\n").encode("ascii"))

    def _read_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self.ser.read(256)
            except Exception as exc:
                if not self._stop.is_set():
                    self.on_line(f"__ERROR__ {exc}")
                break
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("ascii", "replace").strip()
                if text:
                    self.on_line(text)
