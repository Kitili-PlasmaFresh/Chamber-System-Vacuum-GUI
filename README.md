# Monroe Controller: treatment-cycle GUI + thin Arduino firmware

## Files
- `monroe_gui.py`: Python GUI (**PyQt6** + pyserial) entry point. **Runs the treatment cycle.** The code it starts lives in the `core/`, `hardware/` and `gui/` folders next to it, so keep those together with it (see `REFACTORING.md` for what is where).
- `monroe_gui_original.py`: the single-file version from before the split, kept for reference.
- `tests/`: automated checks (`pip install -r requirements-dev.txt`, then `python -m pytest tests`). They run the simulator headless; no hardware needed.
- `SolenoidValveControl/SolenoidValveControl.ino`: thin firmware. It streams data and applies commands. **Upload this first.**
- `monroe_settings.json` is created next to the GUI and remembers your recipe, sensor settings, ports and cycle count.

## Running
1. `pip install -r requirements.txt` (PyQt6 + pyserial, Python 3.9 or newer).
2. `python monroe_gui.py`
3. Pick the Arduino's port and click **Connect**. Close the Arduino Serial Monitor first.
4. To try it with no hardware, pick **SIMULATOR (no hardware)** for both the controller and the pressure sensor. It fakes a chamber that pumps down and vents.

## The treatment cycle (from your flowchart)
| # | Step | What the GUI does | Moves on when |
|---|---|---|---|
| 0 | Idle | If cycles >= target cycles: stop, run complete. Otherwise, if Start was pressed, begin a cycle | |
| 1 | Chamber evacuation | Bridge off, gate off, valve 0 %, solenoid off, **pump ON** | pressure <= target pressure |
| 2 | Pump off, wait t1 | **pump OFF** | t1 seconds pass |
| 3 | Ramp to target frequency | Steps the D9 gate from the ramp start frequency to the target (set ramp step 0 to jump straight there) | board reports the gate within 1 % of target |
| 4 | Half-bridge power ON | **BRIDGE ON**: plasma engaged | treatment time passes |
| 5 | Solenoid valve to target % | **solenoid ON + valve to the vent %** | pressure >= ambient - tolerance |
| 6 | Wait t2 | | t2 seconds pass |
| 7 | Half-bridge power OFF | **BRIDGE OFF**, gate off, valve 0 %, solenoid off. Cycles += 1 | back to Idle |

The flowchart step list highlights where the run is. The cycle count is shown large, and the live pressure chart shows target and ambient lines.

### Things I added that aren't in the flowchart (please check)
- **Timeouts and aborts.** If evacuation or venting takes longer than its timeout, or pressure data stops for 2 s, the gate doesn't reach target, or the serial link drops, the GUI sends `ALL OFF` and stops the run. **Abort** and the red **ALL OFF** do the same at any time.
- **Valve closed at the end of each cycle (step 7)** and at the start of evacuation. The flowchart doesn't say when the valve closes, and it must be closed to pump down.
- **"Solenoid valve %" step** turns on the solenoid relay (D2), which powers the valve, and sets the proportional valve (GP8302) to the vent %. The vent % is limited to 0-30 % unless you tick the override on the Recipe tab.
- **"= target" checks** use <= target pressure and >= ambient minus a tolerance, since an exact match never happens with a real sensor.
- Optional CSV recording of every data point during a run.

## Pressure sensor: Omega PXM409-3.5BAUSBH (USB)
The transmitter plugs into the PC and shows up as its own serial (COM) port. The GUI reads it directly; the Arduino is not involved.

1. Plug in both USB cables. On the top bar, pick the Arduino's port on the **Controller** row and the Omega's port on the **Pressure sensor** row, then press both **Connect** buttons.
2. On the **Pressure sensor** tab, press **Test sensor**. The Log tab shows what the transmitter replies to `ENQ` (identify) and to the read command.
3. The live reading shows in kPa (and bar) and drives the cycle. A run won't start without readings, and it aborts if readings stop for 2 s.

Settings on the Pressure sensor tab (saved between sessions):
| Setting | Default | Notes |
|---|---|---|
| Baud rate | 115200 | |
| Read command | `P` | sent every poll; the first number in the reply is the pressure |
| Command line ending | CR | |
| Unit the sensor reports in | bar | the 3.5BA model is a 0-3.5 bar absolute transmitter; change this if you set the transmitter to another unit |
| Poll interval | 200 ms | |

**These defaults are not yet confirmed.** I couldn't open Omega's USBH command reference from here, so they're my best understanding of the protocol. If Test sensor shows no reply or the wrong number, send me the Log lines (or Omega's "USBH Transducer Command Reference") and I'll set the right command.

## Firmware: what it does now
The firmware no longer makes decisions. It:
- streams one line every 200 ms:
  `DATA MS=12345 SOL=0 PUMP=1 BRIDGE=0 VALVE=0.0 FREQ=20000 AFREQ=20000.0`
- applies these commands:

| Command | Effect |
|---|---|
| `PUMP ON/OFF` | D7 vacuum pump |
| `SOLENOID ON/OFF` | D2 solenoid relay |
| `BRIDGE ON/OFF` | D8 half-bridge power |
| `VALVE 0-100` (or a bare number) | proportional valve via GP8302 |
| `FREQ 0-40000` | D9 gate, 50 % duty, Timer1. `0` stops it and holds D9 LOW |
| `ALL OFF` | bridge off, gate off, pump off, valve 0 %, solenoid off |
| `STREAM <ms>` | DATA period (0 = off) |
| `WATCHDOG <s>` | safety timeout, default 5 s (0 = off) |
| `PING` / `STATUS` | keep-alive / send one DATA line now |

**Changes from the previous version:**
- The treatment timer (`TIME`, `START`, `STOP`) moved out of the firmware and into the GUI.
- D9 and D8 are now independent, so the GUI can bring the gate up to frequency **before** powering the bridge, as the flowchart shows. At power-up the gate is off (D9 LOW).
- **New safety watchdog.** The timing now lives on the PC, so the firmware switches everything off if it hears nothing from the PC for 5 s (crash, cable pulled, laptop asleep). The GUI sends `PING` every second to keep it fed. If you use the Serial Monitor by hand, send `WATCHDOG 0` first or outputs will switch off after 5 s.
- No longer reads a pressure sensor (the A0 input from the last version is gone).

## Board note
The Timer1 frequency code is for an **Uno / Nano (ATmega328P)**. On a Mega, D9 is on a different timer and the code needs changing.

## Testing done
- The firmware compiles with no warnings for the Uno using avr-gcc and the Arduino AVR core.
- In the built-in simulator (controller and sensor both set to SIMULATOR), the PyQt6 GUI ran two full cycles end to end: evacuate, wait, ramp 1 kHz to 35 kHz, plasma, vent, wait, disengage, count. Losing the pressure readings during a run triggered the abort and switched every output off.
- Not tested on your hardware. Check D9 on a scope and the pressure reading against a gauge before a real run.
- The sensor reader was tested against a fake Omega device on a virtual serial port (replying `1.01325` bar to `P`), which displayed 101.33 kPa.
