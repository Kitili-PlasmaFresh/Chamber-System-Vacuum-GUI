"""Runs the original and the refactored window side by side (headless, simulator
ports) and checks they look the same and drive the simulated hardware the same way."""

import time

import pytest

import monroe_gui_original as orig
from gui.main_window import App as NewApp
from hardware.simulator import SimulatedBoard

VERSIONS = {"original": orig.App, "refactored": NewApp}

FAST_RECIPE = dict(target_cycles="2", target_pressure="60", evac_wait="0.2", evac_timeout="30",
                   target_freq="20000", ramp_start="1000", ramp_step="5000", ramp_interval="20",
                   treat_time="0.5", vent_valve="30", ambient_pressure="101.3", ambient_tol="20",
                   vent_wait="0.2", vent_timeout="30")


def pump(qapp, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until is None


def make(qapp, cls):
    win = cls()
    win.resize(1180, 760)
    win.show()
    pump(qapp, 0.3)
    return win


def widget_tree(win):
    """(class, text-ish property, enabled) for every child widget, in creation order."""
    from PyQt6.QtWidgets import QWidget
    rows = []
    for w in win.findChildren(QWidget):
        text = ""
        for attr in ("text", "title", "currentText", "toPlainText", "placeholderText"):
            fn = getattr(w, attr, None)
            if callable(fn):
                try:
                    text = fn()
                    break
                except TypeError:
                    pass
        rows.append((type(w).__name__, text, w.isEnabled(), w.styleSheet(), w.geometry().getRect()))
    return rows


def connect_simulators(qapp, win, sent):
    win.port_box.setCurrentText(orig.SIM_PORT)
    win.sensor_port_box.setCurrentText(orig.SIM_PORT)
    win.toggle_connection()
    real_send = win.link.send

    def spy(cmd):
        if cmd != "PING":
            sent.append(cmd)
        real_send(cmd)
    win.link.send = spy
    win.toggle_sensor()
    assert pump(qapp, 5, until=lambda: win.pressure() is not None and "READY" in win.log.toPlainText())


def test_layout_and_pixels_identical(qapp, isolated):
    a, b = make(qapp, orig.App), make(qapp, NewApp)
    try:
        assert widget_tree(a) == widget_tree(b)
        assert a.windowTitle() == b.windowTitle()
        for tab in range(a.tabs.count()):
            a.tabs.setCurrentIndex(tab)
            b.tabs.setCurrentIndex(tab)
            pump(qapp, 0.1)
            assert a.tabs.tabText(tab) == b.tabs.tabText(tab)
            img_a, img_b = a.grab().toImage(), b.grab().toImage()
            assert img_a == img_b, f"tab {a.tabs.tabText(tab)!r} renders differently"
    finally:
        for w in (a, b):
            w.hide()
            w.deleteLater()


def run_two_cycles(qapp, cls):
    win = make(qapp, cls)
    sent, states = [], []
    try:
        for k, v in FAST_RECIPE.items():
            win.fields[k][0].setText(v)
        connect_simulators(qapp, win, sent)
        win.start_run()
        assert win.armed

        def watch():
            if not states or states[-1] != win.state:
                states.append(win.state)
            return not win.armed
        assert pump(qapp, 60, until=watch), "run did not finish"
        sim = dict(win.link.s)
        return dict(win=win, sent=sent, states=states, cycles=win.cycles, sim=sim,
                    detail=win.state_detail.text(), cycle_lbl=win.cycle_lbl.text())
    finally:
        if win.link is not None:
            win.link.close()
        if win.sensor is not None:
            win.sensor.close()
        win.hide()


@pytest.fixture(scope="module")
def runs(qapp, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    import gui.persistence
    from PyQt6.QtWidgets import QMessageBox
    # each version gets its own fresh settings file, so both start from 0 cycles
    mp.setattr(orig, "SETTINGS_FILE", str(tmp_path_factory.mktemp("orig") / "monroe_settings.json"))
    mp.setattr(gui.persistence, "SETTINGS_FILE",
               str(tmp_path_factory.mktemp("new") / "monroe_settings.json"))
    boxes = []
    for kind in ("warning", "critical", "information", "question"):
        mp.setattr(QMessageBox, kind, staticmethod(lambda *a, k=kind: boxes.append((k, a[1]))))
    out = {name: run_two_cycles(qapp, cls) for name, cls in VERSIONS.items()}
    mp.undo()
    out["boxes"] = boxes
    return out


def test_full_simulated_run_completes(runs):
    for name in VERSIONS:
        r = runs[name]
        assert r["cycles"] == 2, name
        assert r["detail"] == "Complete: 2 cycle(s) done.", name
        assert r["cycle_lbl"] == "Cycles: 2 / 2", name
        assert r["sim"] == dict(SOL=0, PUMP=0, BRIDGE=0, VALVE=0.0, FREQ=0, AFREQ=0.0), name
    assert runs["boxes"] == []


def test_same_commands_and_states_as_original(runs):
    o, n = runs["original"], runs["refactored"]
    assert n["sent"] == o["sent"]
    assert n["states"] == o["states"]
    expected_cycle = ["BRIDGE OFF", "FREQ 0", "VALVE 0", "SOLENOID OFF", "PUMP ON", "PUMP OFF",
                      "FREQ 1000", "FREQ 6000", "FREQ 11000", "FREQ 16000", "FREQ 20000",
                      "BRIDGE ON", "SOLENOID ON", "VALVE 30.0",
                      "BRIDGE OFF", "FREQ 0", "VALVE 0", "SOLENOID OFF"]
    # WATCHDOG/STREAM once more when the board says READY (the first pair is sent before the spy)
    assert o["sent"] == ["WATCHDOG 5", "STREAM 200"] + expected_cycle * 2


@pytest.mark.parametrize("name", list(VERSIONS))
def test_sensor_loss_aborts_and_switches_everything_off(qapp, isolated, name):
    win = make(qapp, VERSIONS[name])
    sent = []
    try:
        for k, v in FAST_RECIPE.items():
            win.fields[k][0].setText(v)
        connect_simulators(qapp, win, sent)
        win.start_run()
        assert pump(qapp, 5, until=lambda: win.state == "EVACUATE")
        win.sensor.close()                       # readings stop, link object stays
        assert pump(qapp, 5, until=lambda: not win.armed)
        pump(qapp, 0.2)
        assert sent[-1] == "ALL OFF"
        assert win.link.s == dict(SOL=0, PUMP=0, BRIDGE=0, VALVE=0.0, FREQ=0, AFREQ=0.0)
        assert win.state == "IDLE"
        assert isolated == [("critical", "Treatment aborted")]
        assert "Lost readings from the pressure sensor" in win.state_detail.text()
    finally:
        win.link.close()
        win.hide()


@pytest.mark.parametrize("name", list(VERSIONS))
def test_buttons_are_wired(qapp, isolated, name):
    """Click the real buttons and check the command each one sends."""
    win = make(qapp, VERSIONS[name])
    sent = []
    try:
        connect_simulators(qapp, win, sent)
        assert pump(qapp, 2, until=lambda: win.data)
        sent.clear()
        win.pump_btn.click()
        win.sol_btn.click()
        win.bridge_btn.click()
        win.man_valve.setValue(12.5)
        win.man_valve_btn.click()
        win.man_freq.setValue(5000)
        win.man_freq_btn.click()
        win.raw_edit.setText("STATUS")
        win.raw_btn.click()
        win.alloff_btn.click()
        assert sent == ["PUMP ON", "SOLENOID ON", "BRIDGE ON", "VALVE 12.5", "FREQ 5000",
                        "STATUS", "ALL OFF"]
        assert win.man_valve.maximum() == 30.0
        win.man_override.setChecked(True)
        assert win.man_valve.maximum() == 100.0
        assert win.start_btn.isEnabled() and not win.abort_btn.isEnabled()
    finally:
        win.link.close()
        win.sensor.close()
        win.hide()


@pytest.mark.parametrize("name", list(VERSIONS))
def test_settings_round_trip(qapp, isolated, name, tmp_path):
    import json
    win = make(qapp, VERSIONS[name])
    win.fields["treat_time"][0].setText("42")
    win.s_cmd.setText("PX")
    win.cycles = 3
    win._save_settings()
    path = orig.SETTINGS_FILE if name == "original" else __import__("gui.persistence").persistence.SETTINGS_FILE
    saved = json.load(open(path))
    assert saved["treat_time"] == "42" and saved["sensor_cmd"] == "PX" and saved["cycles_done"] == 3
    win2 = make(qapp, VERSIONS[name])
    assert win2.get("treat_time") == 42.0 and win2.s_cmd.text() == "PX" and win2.cycles == 3
    for w in (win, win2):
        w.hide()


def test_simulator_board_matches_original():
    lines_a, lines_b = [], []
    a, b = orig.SimulatedBoard(lines_a.append), SimulatedBoard(lines_b.append)
    for board in (a, b):
        board.open(orig.SIM_PORT)
        board.stream_ms = 0
    for cmd in ("PUMP ON", "FREQ 20000", "FREQ 0", "VALVE 12.5", "33", "BOGUS", "ALL OFF", "STREAM 0"):
        a.send(cmd)
        b.send(cmd)
    a.close()
    b.close()
    strip = [line for line in lines_a if not line.startswith(("DATA", "Monroe", "GP8302", "READY"))]
    assert strip == [line for line in lines_b if not line.startswith(("DATA", "Monroe", "GP8302", "READY"))]
    assert "ERROR: Invalid command." in strip
