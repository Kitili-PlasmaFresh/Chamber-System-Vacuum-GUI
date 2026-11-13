"""Every class, function, method and constant of the original script is present
in the package, and every function body is unchanged (compared as ASTs)."""

import ast
import os

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_FILES = ["monroe_gui.py"] + [
    os.path.join(pkg, f) for pkg in ("core", "gui", "hardware")
    for f in sorted(os.listdir(os.path.join(APP_DIR, pkg))) if f.endswith(".py")]


def parse(rel):
    with open(os.path.join(APP_DIR, rel)) as fh:
        return ast.parse(fh.read(), rel)


def functions(tree):
    """{qualified name: ast dump} for top-level functions and class methods.
    Methods of App and of the App mixins are all filed under 'App.'."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = ast.dump(node)
        elif isinstance(node, ast.ClassDef):
            owner = "App" if node.name == "App" or node.name.endswith("Mixin") else node.name
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    key = f"{owner}.{item.name}"
                    assert key not in out, f"{key} defined twice (would shadow in the MRO)"
                    out[key] = ast.dump(item)
    return out


ORIGINAL = functions(parse("monroe_gui_original.py"))
REFACTORED = {}
for _rel in PACKAGE_FILES:
    for _k, _v in functions(parse(_rel)).items():
        assert _k not in REFACTORED, f"{_k} defined in two modules"
        REFACTORED[_k] = _v


def test_nothing_missing_or_added():
    assert sorted(ORIGINAL) == sorted(REFACTORED)


@pytest.mark.parametrize("name", sorted(ORIGINAL))
def test_body_unchanged(name):
    assert REFACTORED[name] == ORIGINAL[name], f"{name} differs from the original"


def test_classes_resolve_like_the_original():
    import monroe_gui
    import monroe_gui_original as orig
    from gui.main_window import App
    from hardware.pressure_sensor import PressureSensor
    from hardware.serial_link import SerialLink
    from hardware.simulator import SimulatedBoard, SimulatedSensor
    from gui.chart import PressureChart

    assert monroe_gui.App is App
    pairs = [(App, orig.App), (SerialLink, orig.SerialLink), (SimulatedBoard, orig.SimulatedBoard),
             (PressureSensor, orig.PressureSensor), (SimulatedSensor, orig.SimulatedSensor),
             (PressureChart, orig.PressureChart)]
    for new, old in pairs:
        own = {n for n, v in vars(old).items() if callable(v) or isinstance(v, property)}
        for n in own:
            # the class that supplies n must be one of ours, not a Qt base of the same name
            owner = next(c for c in new.__mro__ if n in vars(c))
            assert not owner.__module__.startswith("PyQt6"), (new.__name__, n, owner)


def test_constants_identical():
    import core.config as cfg
    import monroe_gui_original as orig
    names = [n for n in vars(orig) if n.isupper()]
    assert names, "no constants found"
    for n in names:
        assert getattr(cfg, n) == getattr(orig, n), n
    # the settings file stays next to monroe_gui.py
    assert cfg.SETTINGS_FILE == os.path.join(APP_DIR, "monroe_settings.json")


def test_core_and_hardware_do_not_import_qt():
    for rel in PACKAGE_FILES:
        if rel.startswith(("core", "hardware")):
            src = open(os.path.join(APP_DIR, rel)).read()
            assert "PyQt6" not in src, rel


def test_no_import_cycles():
    """Layering: hardware -> core.config; core -> core; gui -> anything; entry -> gui."""
    allowed = {"core": {"core"}, "hardware": {"core", "hardware"},
               "gui": {"core", "hardware", "gui"}}
    for rel in PACKAGE_FILES:
        pkg = rel.split(os.sep)[0]
        if pkg not in allowed:
            continue
        for node in ast.walk(parse(rel)):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in ("core", "gui", "hardware"):
                    assert top in allowed[pkg], f"{rel} imports {node.module}"


def test_runs_without_pyserial():
    """Like the original, a missing pyserial still lets the window and the simulator run."""
    import subprocess
    import sys
    code = ("import sys; sys.modules['serial'] = None\n"
            "from PyQt6.QtWidgets import QApplication; app = QApplication([])\n"
            "import hardware.serial_link as sl; assert sl.serial is None\n"
            "from gui.main_window import App; w = App()\n"
            "assert w.port_box.currentText() == 'SIMULATOR (no hardware)'\n"
            "print('ok')")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, "-c", code], cwd=APP_DIR, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr
