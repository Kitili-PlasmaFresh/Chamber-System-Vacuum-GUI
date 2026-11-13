"""The real serial classes against fake devices on a pseudo-terminal (Linux/macOS only).
Checks the bytes on the wire are what the firmware and the Omega transmitter expect."""

import os
import queue
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="needs a pty")

from hardware.pressure_sensor import PressureSensor
from hardware.serial_link import SerialLink


def pty_pair():
    master, slave = os.openpty()
    return master, os.ttyname(slave), slave


def read_until(fd, marker, timeout=2.0):
    buf, end = b"", time.time() + timeout
    os.set_blocking(fd, False)
    while time.time() < end and marker not in buf:
        try:
            buf += os.read(fd, 256)
        except BlockingIOError:
            time.sleep(0.01)
    return buf


def test_serial_link_line_framing():
    master, port, slave = pty_pair()
    lines = []
    link = SerialLink(lines.append)
    link.open(port)
    try:
        assert link.connected
        link.send("  PUMP ON ")
        assert read_until(master, b"\n") == b"PUMP ON\n"
        os.write(master, b"READY\r\nDATA MS=1 SOL=0 PUMP=1 BRIDGE=0 VALVE=0.0 FREQ=0 AFREQ=0.0\n\n")
        end = time.time() + 2
        while len(lines) < 2 and time.time() < end:
            time.sleep(0.01)
        assert lines == ["READY", "DATA MS=1 SOL=0 PUMP=1 BRIDGE=0 VALVE=0.0 FREQ=0 AFREQ=0.0"]
    finally:
        link.close()
        os.close(master)
        os.close(slave)
    with pytest.raises(IOError):
        link.send("PING")


def test_pressure_sensor_polls_and_converts():
    master, port, slave = pty_pair()
    stop = threading.Event()

    def fake_omega():                      # replies 1.01325 (bar) to "P\r", an ID to "ENQ\r"
        os.set_blocking(master, False)
        buf = b""
        while not stop.is_set():
            try:
                buf += os.read(master, 64)
            except (BlockingIOError, OSError):
                time.sleep(0.005)
                continue
            while b"\r" in buf:
                cmd, buf = buf.split(b"\r", 1)
                reply = b"PXM409 FAKE" if cmd == b"ENQ" else b"1.01325"
                os.write(master, reply + b"\r\n")
    t = threading.Thread(target=fake_omega, daemon=True)
    t.start()
    q = queue.Queue()
    sensor = PressureSensor(q)
    sensor.open(port, 115200, "P", "\r", 100.0, 0.05)
    try:
        kind, kpa, raw = q.get(timeout=3)
        assert kind == "P" and raw == "1.01325" and kpa == pytest.approx(101.325)
        assert sensor.query("ENQ") == "PXM409 FAKE"
    finally:
        sensor.close()
        stop.set()
        os.close(slave)


def test_pressure_parse_and_echo_strip():
    s = PressureSensor(queue.Queue())
    s.factor = 100.0
    assert s.parse("P 1.5e-1 bar") == pytest.approx(15.0)
    assert s.parse("no number") is None
