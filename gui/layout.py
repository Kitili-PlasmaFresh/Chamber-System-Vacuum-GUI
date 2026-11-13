"""Builds every widget of the main window (connection bar, run panel, tabs)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget)

from core.config import (
    CHART_SECONDS, FREQ_MAX, RECIPE_FIELDS, SENSOR_BAUDS, SENSOR_DEFAULTS, SENSOR_EOLS,
    SENSOR_UNITS, STATES, VALVE_IDEAL_MAX)
from gui.chart import PressureChart


class LayoutMixin:
    """Methods moved verbatim from the original App class."""

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Connection bar: Arduino controller + Omega pressure transmitter
        conn = QHBoxLayout()
        root.addLayout(conn)
        cg = QGridLayout()
        conn.addLayout(cg)
        cg.addWidget(QLabel("Controller (Arduino):"), 0, 0)
        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(240)
        cg.addWidget(self.port_box, 0, 1)
        self.conn_btn = QPushButton("Connect")
        self.conn_btn.clicked.connect(self.toggle_connection)
        cg.addWidget(self.conn_btn, 0, 2)
        self.conn_lbl = QLabel("Disconnected")
        self.conn_lbl.setStyleSheet("color: gray;")
        cg.addWidget(self.conn_lbl, 0, 3)
        cg.addWidget(QLabel("Pressure sensor (Omega USB):"), 1, 0)
        self.sensor_port_box = QComboBox()
        self.sensor_port_box.setMinimumWidth(240)
        cg.addWidget(self.sensor_port_box, 1, 1)
        self.sensor_btn = QPushButton("Connect")
        self.sensor_btn.clicked.connect(self.toggle_sensor)
        cg.addWidget(self.sensor_btn, 1, 2)
        self.sensor_lbl = QLabel("Disconnected")
        self.sensor_lbl.setStyleSheet("color: gray;")
        cg.addWidget(self.sensor_lbl, 1, 3)
        b = QPushButton("Refresh ports")
        b.clicked.connect(self.refresh_ports)
        cg.addWidget(b, 0, 4, 2, 1)
        conn.addStretch(1)
        self.alloff_btn = QPushButton("ALL OFF")
        self.alloff_btn.setMinimumWidth(140)
        self.alloff_btn.setStyleSheet(
            "QPushButton { background:#c62828; color:white; font-weight:bold; font-size:14px; padding:6px; }"
            "QPushButton:disabled { background:#e0a0a0; }")
        self.alloff_btn.clicked.connect(self.all_off)
        conn.addWidget(self.alloff_btn)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        # ---------------- left: run panel
        left = QWidget()
        lg = QGridLayout(left)
        lg.setContentsMargins(0, 0, 0, 0)
        split.addWidget(left)

        run = QGroupBox("Treatment cycle")
        rl = QVBoxLayout(run)
        self.cycle_lbl = QLabel("Cycles: 0 / 1")
        self.cycle_lbl.setStyleSheet("font-size: 26px; font-weight: bold;")
        rl.addWidget(self.cycle_lbl)
        self.state_detail = QLabel("")
        self.state_detail.setWordWrap(True)
        self.state_detail.setMinimumHeight(36)
        rl.addWidget(self.state_detail)
        bl = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start Treatment")
        self.start_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.start_btn.clicked.connect(self.start_run)
        self.abort_btn = QPushButton("■  Abort")
        self.abort_btn.setStyleSheet("padding: 6px;")
        self.abort_btn.clicked.connect(lambda: self.abort("Aborted by user"))
        self.reset_btn = QPushButton("Reset count")
        self.reset_btn.clicked.connect(self.reset_cycles)
        for w in (self.start_btn, self.abort_btn, self.reset_btn):
            bl.addWidget(w)
        rl.addLayout(bl)
        self.csv_chk = QCheckBox("Record data to CSV during runs")
        rl.addWidget(self.csv_chk)
        rl.addStretch(1)
        lg.addWidget(run, 0, 0)

        steps = QGroupBox("Flowchart step")
        sl = QVBoxLayout(steps)
        sl.setSpacing(2)
        self.step_lbls = {}
        for i, (key, label) in enumerate(STATES):
            lbl = QLabel(f" {i}. {label} ")
            sl.addWidget(lbl)
            self.step_lbls[key] = lbl
        sl.addStretch(1)
        lg.addWidget(steps, 0, 1)

        live = QGroupBox("Live data")
        ll = QGridLayout(live)
        self.p_lbl = QLabel("— kPa")
        self.p_lbl.setStyleSheet("font-size: 28px; font-weight: bold;")
        self.p_lbl.setMinimumWidth(180)
        ll.addWidget(self.p_lbl, 0, 0, 2, 1)
        self.pv_lbl = QLabel("sensor: not connected")
        self.pv_lbl.setStyleSheet("color: gray;")
        ll.addWidget(self.pv_lbl, 2, 0)
        self.ind = {}
        for i, (k, name) in enumerate([("PUMP", "Vacuum pump"), ("SOL", "Solenoid"),
                                       ("BRIDGE", "Half-bridge"), ("VALVE", "Valve"),
                                       ("AFREQ", "Gate freq")]):
            n = QLabel(name + ":")
            n.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            ll.addWidget(n, i % 3, 1 + 2 * (i // 3))
            lbl = QLabel("—")
            lbl.setMinimumWidth(80)
            ll.addWidget(lbl, i % 3, 2 + 2 * (i // 3))
            self.ind[k] = lbl
        ll.setColumnStretch(0, 1)
        lg.addWidget(live, 1, 0, 1, 2)

        chartbox = QGroupBox(f"Chamber pressure (last {CHART_SECONDS} s)")
        cl = QVBoxLayout(chartbox)
        self.chart = PressureChart(self)
        cl.addWidget(self.chart)
        lg.addWidget(chartbox, 2, 0, 1, 2)
        lg.setRowStretch(2, 1)

        # ---------------- right: tabs
        tabs = QTabWidget()
        split.addWidget(tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        recipe = QWidget()
        rf = QFormLayout(recipe)
        self.recipe_edits = self._add_fields(rf, RECIPE_FIELDS)
        self.vent_override = QCheckBox("Allow vent valve above 30 % (outside ideal range)")
        rf.addRow(self.vent_override)
        tabs.addTab(recipe, "Recipe")

        manual = QWidget()
        self._build_manual(manual)
        tabs.addTab(manual, "Manual")

        cal = QWidget()
        cf = QFormLayout(cal)
        note = QLabel("Omega PXM409-USBH transmitter, read directly over its own USB port. The GUI "
                      "sends the read command, takes the first number in the reply, and converts it "
                      "from the unit below to kPa. Use 'Test sensor' to see the raw replies.")
        note.setWordWrap(True)
        cf.addRow(note)
        self.s_baud = QComboBox()
        self.s_baud.addItems(SENSOR_BAUDS)
        self.s_baud.setEditable(True)
        cf.addRow("Baud rate", self.s_baud)
        self.s_cmd = QLineEdit(SENSOR_DEFAULTS["sensor_cmd"])
        cf.addRow("Read command", self.s_cmd)
        self.s_eol = QComboBox()
        self.s_eol.addItems(list(SENSOR_EOLS))
        cf.addRow("Command line ending", self.s_eol)
        self.s_unit = QComboBox()
        self.s_unit.addItems(list(SENSOR_UNITS))
        cf.addRow("Unit the sensor reports in", self.s_unit)
        self.s_poll = QSpinBox()
        self.s_poll.setRange(50, 5000)
        self.s_poll.setSingleStep(50)
        self.s_poll.setSuffix(" ms")
        self.s_poll.setValue(SENSOR_DEFAULTS["sensor_poll_ms"])
        cf.addRow("Poll interval", self.s_poll)
        self.s_test_btn = QPushButton("Test sensor (send ENQ and read command, show raw replies)")
        self.s_test_btn.clicked.connect(self.test_sensor)
        cf.addRow(self.s_test_btn)
        self.s_raw_lbl = QLabel("Last reply: —")
        self.s_raw_lbl.setStyleSheet("font-family: monospace;")
        self.s_raw_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cf.addRow(self.s_raw_lbl)
        self._apply_sensor_defaults()
        self.sensor_widgets = [self.s_baud, self.s_cmd, self.s_eol, self.s_unit, self.s_poll]
        tabs.addTab(cal, "Pressure sensor")

        logw = QWidget()
        lv = QVBoxLayout(logw)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        lv.addWidget(self.log)
        rawl = QHBoxLayout()
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("Raw command, e.g. STATUS")
        self.raw_edit.returnPressed.connect(self.send_raw)
        self.raw_btn = QPushButton("Send")
        self.raw_btn.clicked.connect(self.send_raw)
        rawl.addWidget(self.raw_edit)
        rawl.addWidget(self.raw_btn)
        lv.addLayout(rawl)
        tabs.addTab(logw, "Log")
        self.tabs = tabs

    def _add_fields(self, form, fields):
        edits = {}
        for key, label, default, typ, lo, hi in fields:
            e = QLineEdit(str(default))
            e.setAlignment(Qt.AlignmentFlag.AlignRight)
            e.setMaximumWidth(110)
            e.textChanged.connect(lambda _t, e=e: e.setStyleSheet(""))
            form.addRow(label, e)
            self.fields[key] = (e, typ, lo, hi, label)
            edits[key] = e
        return edits

    def _build_manual(self, w):
        g = QGridLayout(w)
        note = QLabel("Direct control of each output. Locked while a treatment run is active.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        g.addWidget(note, 0, 0, 1, 3)
        self.pump_btn = QPushButton("Vacuum pump ON/OFF")
        self.pump_btn.clicked.connect(lambda: self._toggle("PUMP"))
        self.sol_btn = QPushButton("Solenoid ON/OFF")
        self.sol_btn.clicked.connect(lambda: self._toggle("SOL"))
        self.bridge_btn = QPushButton("Half-bridge power ON/OFF")
        self.bridge_btn.clicked.connect(lambda: self._toggle("BRIDGE"))
        for r, b in enumerate((self.pump_btn, self.sol_btn, self.bridge_btn), start=1):
            g.addWidget(b, r, 0, 1, 3)

        g.addWidget(QLabel("Valve %"), 4, 0)
        self.man_valve = QDoubleSpinBox()
        self.man_valve.setRange(0, VALVE_IDEAL_MAX)
        self.man_valve.setDecimals(1)
        self.man_valve.setSingleStep(0.5)
        g.addWidget(self.man_valve, 4, 1)
        self.man_valve_btn = QPushButton("Set")
        self.man_valve_btn.clicked.connect(self._manual_valve)
        g.addWidget(self.man_valve_btn, 4, 2)
        self.man_valve_slider = QSlider(Qt.Orientation.Horizontal)
        self.man_valve_slider.setRange(0, int(VALVE_IDEAL_MAX * 2))
        self.man_valve_slider.valueChanged.connect(lambda v: self.man_valve.setValue(v / 2))
        self.man_valve.valueChanged.connect(lambda v: self.man_valve_slider.setValue(int(round(v * 2))))
        self.man_valve_slider.sliderReleased.connect(self._manual_valve)
        g.addWidget(self.man_valve_slider, 5, 0, 1, 3)
        self.man_override = QCheckBox("Allow above 30 %")
        self.man_override.toggled.connect(self._manual_override)
        g.addWidget(self.man_override, 6, 0, 1, 3)

        g.addWidget(QLabel("Gate frequency, Hz"), 7, 0)
        self.man_freq = QSpinBox()
        self.man_freq.setRange(0, FREQ_MAX)
        self.man_freq.setSingleStep(500)
        g.addWidget(self.man_freq, 7, 1)
        self.man_freq_btn = QPushButton("Set")
        self.man_freq_btn.clicked.connect(lambda: self.send(f"FREQ {self.man_freq.value()}"))
        g.addWidget(self.man_freq_btn, 7, 2)
        g.setRowStretch(8, 1)
        g.setColumnStretch(0, 1)

        self.manual_widgets = [self.pump_btn, self.sol_btn, self.bridge_btn, self.man_valve,
                               self.man_valve_btn, self.man_valve_slider, self.man_override,
                               self.man_freq, self.man_freq_btn]
