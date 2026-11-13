#!/usr/bin/env python3
"""
Monroe Controller GUI

Runs the plasma treatment cycle on the PC and drives the thin Arduino
firmware (SolenoidValveControl.ino) over USB serial at 115200 baud.
Built with PyQt6.

Cycle (from the treatment flowchart):
  Idle -> [Cycles >= Target?] -> [Start Treatment?]
  -> Chamber Evacuation: pump ON until pressure <= target, pump OFF, wait t1
  -> Ramp half-bridge gate to target frequency, half-bridge power ON
  -> Plasma Engaged for the treatment time
  -> Solenoid valve to target %, wait for ambient pressure, wait t2
  -> Half-bridge power OFF -> Plasma Disengaged -> Cycles += 1 -> Idle

Hardware: Arduino controller (USB serial) + Omega PXM409-USBH pressure
transmitter (its own USB virtual COM port), read directly by this GUI.

Requires:  pip install PyQt6 pyserial
Run:       python monroe_gui.py
"""

import sys

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    sys.exit("PyQt6 is required:  pip install PyQt6 pyserial")

from gui.main_window import App


def main():
    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")
    win = App()
    win.show()
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
