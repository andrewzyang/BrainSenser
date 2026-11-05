"""
Layer rules of the responsive-UI code (plan §4.7 layer table, R1, R5, R6, R8; mvvm Q10).

- Every import of the new pure policy, port, adapter and ViewModel modules is on
  its layer's allowlist, function-level imports and ``from PySide6 import X``
  included (AST). The two ViewModels may take only QObject, Signal and Slot from
  QtCore, a few pure standard-library modules and ``logging.getLogger``; the
  pure modules only those standard-library modules. None of them opens files,
  runs or imports code dynamically or reflects past its imports.
- The two new ViewModels are loaded BY PATH, bypassing
  src/ui/viewmodels/__init__.py (whose SplashViewModel pulls in QtMultimedia),
  and every command is run while every PySide6 module but QtCore is blocked and
  QtCore's QSettings and QProcess raise; the pure modules load with all of
  PySide6 and shiboken6 blocked. Negative controls prove the blockers bite. The
  child processes run in a throwaway sandbox (HOME, BRAINSENSER_DATA_DIR,
  MPLCONFIGDIR, cwd) behind the responsive harness's open guard.
- Existing ViewModels keep their per-module status under the same blocker.
- Only the composition root imports the preference adapters and the restarter;
  QSettings appears only in the preference stores, never bare.
- R5 and ViewModel placement: plot modules import no ViewModel, scale policy,
  infrastructure or QSettings; only the shell's binding imports the shell
  ViewModels; pages and chrome hold none, ResponsiveContext and ScreenWatcher no
  ViewModel at all.
"""

import ast
import json
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.ui.responsive.runner import child_environment

PROJECT_ROOT = Path(__file__).parent.parent.parent

QTCORE = "PySide6.QtCore"
POLICY = "src.ui.policy"
PORTS = "src.domain.ui_preferences"


@dataclass(frozen=True)
class Allowed:
    """What a module may import: whole ``modules`` (with everything in them),
    single ``names`` ("module" or "module.name") and, if ``stdlib``, any module
    of the standard library."""

    modules: tuple = ()
    names: tuple = ()
    stdlib: bool = False

    def __contains__(self, target: str) -> bool:
        return (target in self.names
                or any(target == m or target.startswith(m + ".") for m in self.modules)
                or (self.stdlib and target.split(".")[0] in sys.stdlib_module_names))


# Standard-library modules that reach no file, process, network or other code;
# the policy also builds read-only mappings (types.MappingProxyType).
VIEWMODEL_STDLIB = ("__future__", "collections", "dataclasses", "enum", "functools", "math",
                    "typing")
PURE_STDLIB = (*VIEWMODEL_STDLIB, "types")
PURE = Allowed(modules=(POLICY, *PURE_STDLIB))
# QtCore's object model only: no QSettings, QProcess, QFile, … and no QtCore module object.
VIEWMODEL = Allowed(modules=(POLICY, PORTS, *VIEWMODEL_STDLIB),
                    names=(f"{QTCORE}.QObject", f"{QTCORE}.Signal", f"{QTCORE}.Slot",
                           "logging", "logging.getLogger"))
ADAPTER = Allowed(modules=(QTCORE, PORTS), stdlib=True)

# Module -> what it may import.
LAYERS = {
    # Pure policy: the pure standard library and each other. Ports: the pure standard library.
    "src/ui/policy/__init__.py": PURE,
    "src/ui/policy/scale.py": PURE,
    "src/ui/policy/layout.py": PURE,
    "src/ui/policy/tokens.py": PURE,
    "src/domain/ui_preferences.py": Allowed(modules=PURE_STDLIB),
    # Adapters: the standard library, QtCore and the ports.
    "src/infrastructure/preferences/__init__.py": Allowed(
        modules=("src.infrastructure.preferences",), stdlib=True),
    "src/infrastructure/preferences/in_memory_ui_preferences.py": Allowed(
        modules=(PORTS,), stdlib=True),
    "src/infrastructure/preferences/qsettings_ui_preferences.py": ADAPTER,
    "src/infrastructure/app_restart.py": ADAPTER,
    # ViewModels: QtCore's object model, policy and ports.
    "src/ui/viewmodels/ui_scale_viewmodel.py": VIEWMODEL,
    "src/ui/viewmodels/shell_viewmodel.py": VIEWMODEL,
}
NEW_VIEWMODELS = ("src/ui/viewmodels/ui_scale_viewmodel.py", "src/ui/viewmodels/shell_viewmodel.py")
PURE_CODE = [path for path, allowed in LAYERS.items() if not allowed.stdlib]

# Names that open files, run or import code at run time, or reach past the
# imports (the builtins, reflection); as names or attributes.
DYNAMIC_NAMES = frozenset({"open", "exec", "eval", "compile", "__import__", "importlib",
                           "__builtins__", "globals", "locals", "vars", "getattr", "setattr",
                           "delattr", "breakpoint"})
ALLOWED_DUNDERS = frozenset({"__init__", "__name__"})

# ViewModel files that do not load with QtGui & co. blocked, and why.
POISONED_LOAD_FAILS = {
    "splash_viewmodel.py": "owns the QMediaPlayer (QtMultimedia)",
}

# Only the container imports the adapters; everything else gets them injected.
COMPOSITION_ROOT = {"src/infrastructure/container.py"}
ADAPTER_MODULES = ("src.infrastructure.preferences", "src.infrastructure.app_restart")

# The only modules where QSettings may appear: the app's settings scope lives there.
QSETTINGS_HOMES = ("src/infrastructure/preferences/", "src/domain/effect_size_preference.py")

# Child-process prologue: argv[1] is the project root, argv[2] the blocker. It
# checks its sandbox and refuses to touch real data before anything else runs.
_BLOCKER = r'''
import importlib.abc, importlib.util, os, sys
from pathlib import Path
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
GUI_ONLY = sys.argv[2] == "gui"

from tests.ui.responsive import _safety
_safety.check_child_environment(Path(os.environ["HOME"]).parent)
_safety.install_open_guard()

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if GUI_ONLY:
            blocked = name.startswith("PySide6.Qt") and name != "PySide6.QtCore"
        else:
            blocked = top in ("PySide6", "shiboken6", "PyQt5", "PyQt6", "PySide2")
        if blocked:
            raise ImportError(f"blocked: {name}")
        return None

sys.meta_path.insert(0, Blocker())

if GUI_ONLY:
    # QtCore stays, but nothing here may reach a settings store or start a process.
    import PySide6.QtCore as QtCore

    class _Blocked(type):
        def __call__(cls, *args, **kwargs):
            raise RuntimeError(f"blocked: PySide6.QtCore.{cls.__name__}")

        def __getattr__(cls, name):
            raise RuntimeError(f"blocked: PySide6.QtCore.{cls.__name__}.{name}")

    for _name in ("QSettings", "QProcess"):
        setattr(QtCore, _name, _Blocked(_name, (), {}))

def load(relative_path, name):
    spec = importlib.util.spec_from_file_location(name, f"{ROOT}/{relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
'''

_EXERCISE_VIEWMODELS = _BLOCKER + r'''
scale_module = load("src/ui/viewmodels/ui_scale_viewmodel.py", "ui_scale_vm_under_test")
shell_module = load("src/ui/viewmodels/shell_viewmodel.py", "shell_vm_under_test")
store_module = load("src/infrastructure/preferences/in_memory_ui_preferences.py", "store_for_vms")
from src.ui.policy.scale import ScreenMetrics

class Restarter:
    restarts = 0
    def restart(self):
        Restarter.restarts += 1

store = store_module.InMemoryUiPreferences()
vm = scale_module.UiScaleViewModel(store, Restarter(), active_factor=1.0)
states = []
vm.state_changed.connect(states.append)
vm.set_current_display(ScreenMetrics("4K", 3840, 2160, 1.0))
assert vm.state.suggest_percent == 125, vm.state
vm.dismiss_suggestion()
vm.accept_suggestion()
vm.zoom_in()
vm.zoom_out()
vm.reset_zoom()
vm.zoom_in()
vm.postpone_restart()
vm.restart_now()
assert (vm.state.chosen_percent, vm.state.notice.value, Restarter.restarts, len(states)) == (
    110, "none", 1, 6), vm.state

shell = shell_module.ShellViewModel(store)
modes = []
shell.sidebar_mode_changed.connect(modes.append)
shell.set_width_class("narrow")
shell.toggle_sidebar()
shell.set_sidebar_preference("icons")
shell.remember_window_geometry(b"memento", "4K")
assert shell.saved_window_geometry(["4K"]) == b"memento" and shell.last_screen_name == "4K"
assert (shell.sidebar_preference, shell.sidebar_mode, modes) == (
    "icons", "icons", ["icons", "labels", "icons"])

loaded = sorted(m for m in sys.modules if m.startswith("PySide6.Qt"))
assert loaded == ["PySide6.QtCore"], loaded
print("OK")
'''

_IMPORT_PURE = _BLOCKER + r'''
import src.ui.policy.layout
import src.ui.policy.scale
import src.ui.policy.tokens
import src.domain.ui_preferences
load("src/infrastructure/preferences/in_memory_ui_preferences.py", "store_under_test")
from src.ui.policy.scale import compose_scale_env
assert compose_scale_env({"d": 3}, {}, launch_display="d")["QT_SCALE_FACTOR"] == "1.25"
assert not [m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6")]
print("OK")
'''

_LOAD_EACH = _BLOCKER + r'''
import json
status = {}
for relative_path in sys.argv[3:]:
    try:
        load(relative_path, "vm_" + relative_path.replace("/", "_")[:-3])
        status[relative_path.rsplit("/", 1)[1]] = "ok"
    except ImportError as exc:
        status[relative_path.rsplit("/", 1)[1]] = str(exc)
print(json.dumps(status))
'''


def run_child(code: str, blocker: str, *args: str, sandbox: Path) -> subprocess.CompletedProcess:
    """A fresh isolated interpreter (-I: no user site, no PYTHON* variables; -B: no
    .pyc) in ``sandbox``, with the suite's child isolation: HOME, the data dir
    and the cwd in the sandbox, MPLCONFIGDIR in the harness's cache."""
    for folder in ("home", "appdata", "cwd"):
        (sandbox / folder).mkdir(parents=True, exist_ok=True)
    return subprocess.run([sys.executable, "-I", "-B", "-c", code, str(PROJECT_ROOT), blocker,
                           *args], cwd=sandbox / "cwd", capture_output=True, text=True,
                          timeout=300, env=child_environment(sandbox, "offscreen", PROJECT_ROOT))


def imported_modules(path: Path) -> list[tuple[int, str]]:
    """(line, dotted target) of every import in ``path``; ``from m import x`` gives m.x."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    try:
        package = list(path.relative_to(PROJECT_ROOT).parts[:-1])
    except ValueError:
        package = []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package[:len(package) - node.level + 1]
                base = ".".join(parent + ([node.module] if node.module else []))
            found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names]
    return found


def identifiers(path: Path):
    """(line, name) of every identifier used in ``path``: names, attributes,
    parameters and keyword arguments."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield node.value.lineno, node.arg


def _project_sources():
    yield PROJECT_ROOT / "main.py"
    yield from sorted(p for p in (PROJECT_ROOT / "src").rglob("*.py")
                      if "__pycache__" not in p.parts)


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _probe(tmp_path: Path, source: str, name: str = "probe_module.py") -> Path:
    probe = tmp_path / name
    probe.write_text(source)
    return probe


# ------------------------------------------------------------------ AST allowlists

@pytest.mark.parametrize("relative_path", sorted(LAYERS))
def test_imports_stay_on_the_layer_allowlist(relative_path):
    allowed = LAYERS[relative_path]
    violations = [f"{relative_path}:{line}: imports {target}"
                  for line, target in imported_modules(PROJECT_ROOT / relative_path)
                  if target not in allowed]
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("snippet, allowed", [
    ("from PySide6.QtCore import QObject, Signal, Slot", True),
    ("from PySide6.QtCore import QSettings", False),
    ("from PySide6.QtCore import QProcess", False),
    ("from PySide6.QtCore import QFile", False),
    ("from PySide6.QtCore import QTimer", False),
    ("from PySide6 import QtCore", False),          # the module object holds QSettings
    ("import PySide6.QtCore", False),
    ("from PySide6 import QtGui", False),
    ("def f():\n    from PySide6.QtWidgets import QWidget", False),
    ("import shiboken6", False),
    ("from src.ui.views.data_management import DataManagementPage", False),
    ("from src.infrastructure.preferences import QSettingsUiPreferences", False),
    ("from src.domain.effect_size_preference import EffectSizePreference", False),
    ("from src.ui.policy.scale import ZOOM_LADDER", True),
    ("from src.domain.ui_preferences import AppRestarter", True),
    ("from typing import Optional", True),
    ("from collections.abc import Mapping", True),
    ("import logging", True),
    ("from logging import getLogger", True),
    ("from logging import FileHandler", False),
    ("import logging.handlers", False),
    ("import os", False),
    ("import json", False),
    ("import pathlib", False),
    ("import subprocess", False),
    ("import importlib", False),
    ("import ctypes", False),
    ("import sys", False),
    ("from types import FunctionType", False),
])
def test_viewmodel_allowlist_has_teeth(tmp_path, snippet, allowed):
    targets = [target for _, target in imported_modules(_probe(tmp_path, snippet))]
    assert all(target in LAYERS[NEW_VIEWMODELS[0]] for target in targets) is allowed


@pytest.mark.parametrize("snippet, allowed", [
    ("from dataclasses import dataclass\nfrom enum import Enum", True),
    ("from types import MappingProxyType", True),
    ("from src.ui.policy.tokens import Dim", True),
    ("import logging", False),
    ("import os", False),
    ("from PySide6.QtCore import QObject", False),
])
def test_pure_allowlist_has_teeth(tmp_path, snippet, allowed):
    targets = [target for _, target in imported_modules(_probe(tmp_path, snippet))]
    assert all(target in LAYERS["src/ui/policy/scale.py"] for target in targets) is allowed


def dynamic_code(path: Path) -> list[str]:
    """Uses of :data:`DYNAMIC_NAMES`, of dunder attributes other than
    ``__init__``/``__name__``, and of ``logging`` beyond ``getLogger``."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES:
            found.append(f"{node.lineno}: {node.id}")
        elif isinstance(node, ast.Attribute):
            dunder = node.attr.startswith("__") and node.attr.endswith("__")
            if node.attr in DYNAMIC_NAMES or (dunder and node.attr not in ALLOWED_DUNDERS):
                found.append(f"{node.lineno}: .{node.attr}")
            elif (isinstance(node.value, ast.Name) and node.value.id == "logging"
                  and node.attr != "getLogger"):
                found.append(f"{node.lineno}: logging.{node.attr}")
    return found


@pytest.mark.parametrize("relative_path", PURE_CODE)
def test_no_files_dynamic_code_or_reflection(relative_path):
    found = dynamic_code(PROJECT_ROOT / relative_path)
    assert not found, f"{relative_path}: " + ", ".join(found)


@pytest.mark.parametrize("snippet, flagged", [
    ("open('/tmp/x', 'w')", True),
    ("exec('x = 1')", True),
    ("eval('1')", True),
    ("compile('1', 'x', 'eval')", True),
    ("__import__('os')", True),
    ("importlib.import_module('os')", True),
    ("getattr(self, 'store')", True),
    ("globals()['x'] = 1", True),
    ("__builtins__['open']", True),
    ("f.__globals__", True),
    ("type(x).__subclasses__()", True),
    ("logging.FileHandler('/tmp/x')", True),
    ("logging.basicConfig(filename='/tmp/x')", True),
    ("path.open('w')", True),
    ("logger = logging.getLogger(__name__)", False),
    ("super().__init__(parent)", False),
    ("self.state_changed.emit(state)", False),
])
def test_dynamic_code_check_has_teeth(tmp_path, snippet, flagged):
    assert bool(dynamic_code(_probe(tmp_path, snippet))) is flagged


@pytest.mark.parametrize("relative_path", NEW_VIEWMODELS)
def test_new_viewmodel_is_one_direct_qobject_subclass(relative_path):
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    assert [(c.name.endswith("ViewModel"), [ast.unparse(b) for b in c.bases]) for c in classes] == [
        (True, ["QObject"])]


# ------------------------------------------------------------------ poisoned imports

@pytest.mark.qt_subprocess
def test_new_viewmodels_load_by_path_and_run_with_qt_gui_blocked(tmp_path):
    out = run_child(_EXERCISE_VIEWMODELS, "gui", sandbox=tmp_path)
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stderr[-3000:]


@pytest.mark.qt_subprocess
def test_pure_modules_import_with_all_qt_blocked(tmp_path):
    out = run_child(_IMPORT_PURE, "all", sandbox=tmp_path)
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stderr[-3000:]


@pytest.mark.qt_subprocess
@pytest.mark.parametrize("blocker, source, blocked", [
    ("gui", "from PySide6 import QtGui\n", "PySide6.QtGui"),
    ("gui", "import PySide6.QtWidgets\n", "PySide6.QtWidgets"),
    ("all", "from PySide6.QtCore import QObject\n", "PySide6"),
    # A scope no store uses: if the stub ever failed, construction alone writes nothing.
    ("gui", "from PySide6.QtCore import QSettings\nQSettings('blocker-probe', 'never-written')\n",
     "PySide6.QtCore.QSettings"),
    ("gui", "from PySide6 import QtCore\nQtCore.QSettings.Format\n", "PySide6.QtCore.QSettings"),
    ("gui", "from PySide6.QtCore import QProcess\nQProcess.startDetached('/usr/bin/true', [])\n",
     "PySide6.QtCore.QProcess"),
])
def test_poison_harness_negative_controls(tmp_path, blocker, source, blocked):
    probe = _probe(tmp_path, source, "probe_viewmodel.py")
    code = _BLOCKER + (
        "spec = importlib.util.spec_from_file_location('probe', sys.argv[3])\n"
        "spec.loader.exec_module(importlib.util.module_from_spec(spec))\n")
    out = run_child(code, blocker, str(probe), sandbox=tmp_path / "sandbox")
    assert out.returncode != 0 and f"blocked: {blocked}" in out.stderr, out.stderr[-3000:]


@pytest.mark.qt_subprocess
def test_children_run_in_the_sandbox(tmp_path):
    """HOME, the data dir and the cwd of every child lie in its sandbox (the
    prologue checks it too, before anything else runs)."""
    code = _BLOCKER + "print(os.environ['HOME'], os.environ['BRAINSENSER_DATA_DIR'], os.getcwd())\n"
    out = run_child(code, "gui", sandbox=tmp_path)
    assert out.returncode == 0, out.stderr[-3000:]
    paths = out.stdout.split()
    assert len(paths) == 3 and all(
        Path(p).resolve().is_relative_to(tmp_path.resolve()) for p in paths), paths


@pytest.mark.qt_subprocess
def test_existing_viewmodels_keep_their_poisoned_load_status(tmp_path):
    files = sorted(p.relative_to(PROJECT_ROOT).as_posix()
                   for p in (PROJECT_ROOT / "src" / "ui" / "viewmodels").glob("*_viewmodel.py"))
    out = run_child(_LOAD_EACH, "gui", *files, sandbox=tmp_path)
    assert out.returncode == 0, out.stderr[-3000:]
    status = json.loads(out.stdout.strip().splitlines()[-1])
    assert set(POISONED_LOAD_FAILS) <= set(status), "a listed ViewModel file no longer exists"
    newly_failing = {name: error for name, error in status.items()
                     if error != "ok" and name not in POISONED_LOAD_FAILS}
    assert not newly_failing, f"ViewModels that now need Qt GUI modules: {newly_failing}"
    fixed = [name for name in POISONED_LOAD_FAILS if status[name] == "ok"]
    if fixed:
        warnings.warn(f"remove from POISONED_LOAD_FAILS (now QtCore-only): {fixed}", stacklevel=2)


# ------------------------------------------------------------------ adapters and settings scope

def test_only_the_composition_root_imports_the_adapters():
    violations = []
    for path in _project_sources():
        relative_path = _relative(path)
        if (relative_path in COMPOSITION_ROOT
                or relative_path.startswith("src/infrastructure/preferences/")
                or relative_path == "src/infrastructure/app_restart.py"):
            continue
        violations += [f"{relative_path}:{line}: imports {target}"
                       for line, target in imported_modules(path)
                       if any(target == m or target.startswith(m + ".") for m in ADAPTER_MODULES)]
    assert not violations, "\n".join(violations)


def qsettings_references(path: Path) -> list[str]:
    """Every mention of QSettings in code: imported (aliased too), named, as an
    attribute, or spelled out as a string."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and any(a.name == "QSettings" for a in node.names):
            found.append(f"{node.lineno}: imported")
        elif ((isinstance(node, ast.Name) and node.id == "QSettings")
              or (isinstance(node, ast.Attribute) and node.attr == "QSettings")
              or (isinstance(node, ast.Constant) and node.value == "QSettings")):
            found.append(f"{node.lineno}: {ast.unparse(node)}")
    return found


def test_qsettings_only_in_the_preference_stores():
    """QSettings(org, app) is the native store: only the two preference stores
    may use it (R6, R8); everything else goes through them."""
    violations = [f"{_relative(path)}:{reference}"
                  for path in _project_sources() if not _relative(path).startswith(QSETTINGS_HOMES)
                  for reference in qsettings_references(path)]
    assert not violations, "QSettings outside the preference stores:\n" + "\n".join(violations)


@pytest.mark.parametrize("snippet, flagged", [
    ("from PySide6.QtCore import QSettings\nQSettings('BrainSense', 'iEEG-App')", True),
    ("from PySide6.QtCore import QSettings as Store", True),
    ("from PySide6 import QtCore\nQtCore.QSettings('BrainSense', 'iEEG-App')", True),
    ("import PySide6.QtCore\nPySide6.QtCore.QSettings()", True),
    ("getattr(QtCore, 'QSettings')", True),
    ("from src.infrastructure.preferences import QSettingsUiPreferences", False),
    ('"""Saved with QSettings."""', False),
])
def test_qsettings_check_has_teeth(tmp_path, snippet, flagged):
    assert bool(qsettings_references(_probe(tmp_path, snippet))) is flagged


def test_no_bare_qsettings():
    """QSettings() takes QCoreApplication's names, which differ from the app's scope (R8)."""
    violations = []
    for path in _project_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and not node.args and not node.keywords
                    and ((isinstance(node.func, ast.Name) and node.func.id == "QSettings")
                         or (isinstance(node.func, ast.Attribute)
                             and node.func.attr == "QSettings"))):
                violations.append(f"{_relative(path)}:{node.lineno}")
    assert not violations, "bare QSettings():\n" + "\n".join(violations)


# ------------------------------------------------------------------ R5 and ViewModel placement

PLOT_MODULES = (
    "src/ui/widgets/responsive_figure.py",
    "src/ui/widgets/mpl_canvas.py",
    "src/ui/widgets/plot_fonts.py",
    "src/ui/views/snapshots_psd/components/dual_hemisphere_psd_widget.py",
    "src/ui/views/snapshots_5hz_band/components/dual_hemisphere_auc_widget.py",
    "src/ui/views/timeline_lfp_threshold/components/dual_hemisphere_violin_widget.py",
    "src/ui/views/timeline_peri_event/components/peri_event_plot.py",
    "src/ui/views/timeline_peri_event/components/matplotlib_canvas.py",
)
# R5: a plot's scale comes from its page (set_ui_scale), its export from EXPORT_CTX only.
PLOT_FORBIDDEN = ("src.ui.viewmodels", "src.ui.policy.scale", "src.infrastructure",
                  f"{QTCORE}.QSettings")

SHELL_VIEWMODELS = ("ShellViewModel", "UiScaleViewModel")
SHELL_VIEWMODEL_MODULES = ("src.ui.viewmodels.shell_viewmodel",
                           "src.ui.viewmodels.ui_scale_viewmodel")
# The shell's binding: the composition root, the bootstrap, the main window, its actions.
SHELL_VIEWMODEL_IMPORTERS = {"main.py", "src/ui/app_bootstrap.py", "src/ui/shell/shell_actions.py",
                             "src/infrastructure/container.py", "src/ui/viewmodels/__init__.py"}
# Pages and chrome get facts pushed (Density, ZoomState) and hold no shell ViewModel.
SHELL_VIEWMODEL_NAMES = frozenset({*SHELL_VIEWMODELS, "shell_viewmodel", "ui_scale_viewmodel",
                                   "shell_vm", "scale_vm"})
SHELL_VIEWMODEL_FREE = ("src/ui/views/", "src/ui/layouts/", "src/ui/components/", "src/ui/widgets/")
# These hold no ViewModel of any kind (plan §4.7: "no VM").
VIEWMODEL_FREE = ("src/ui/layouts/responsive_context.py", "src/ui/shell/screen_watcher.py")
VIEWMODEL_NAME = re.compile(r"viewmodel|(^|_)vm$", re.IGNORECASE)


def _forbidden(target: str, forbidden) -> bool:
    return any(target == f or target.startswith(f + ".") for f in forbidden)


def plot_violations(path: Path) -> list[str]:
    return [f"{line}: imports {target}" for line, target in imported_modules(path)
            if _forbidden(target, PLOT_FORBIDDEN)]


def shell_viewmodel_uses(path: Path) -> list[str]:
    """Imports of the shell ViewModels (classes or modules) and attribute access to the classes."""
    found = [f"{line}: imports {target}" for line, target in imported_modules(path)
             if target.rsplit(".", 1)[-1] in SHELL_VIEWMODELS
             or _forbidden(target, SHELL_VIEWMODEL_MODULES)]
    found += [f"{node.lineno}: .{node.attr}"
              for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
              if isinstance(node, ast.Attribute) and node.attr in SHELL_VIEWMODELS]
    return found


def shell_viewmodel_holders(path: Path) -> list[str]:
    return [f"{line}: {name}" for line, name in identifiers(path) if name in SHELL_VIEWMODEL_NAMES]


def viewmodel_holders(path: Path) -> list[str]:
    found = [f"{line}: imports {target}" for line, target in imported_modules(path)
             if _forbidden(target, ("src.ui.viewmodels",))]
    found += [f"{line}: {name}" for line, name in identifiers(path) if VIEWMODEL_NAME.search(name)]
    return found


@pytest.mark.parametrize("relative_path", PLOT_MODULES)
def test_plot_modules_import_no_viewmodel_scale_or_settings(relative_path):
    found = plot_violations(PROJECT_ROOT / relative_path)
    assert not found, f"{relative_path}: " + ", ".join(found)


def test_every_plot_widget_is_checked():
    """Each ResponsiveFigureWidget subclass lives in a module of PLOT_MODULES."""
    homes = set()
    for path in sorted((PROJECT_ROOT / "src" / "ui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.ClassDef)
               and any(ast.unparse(base).endswith("ResponsiveFigureWidget") for base in node.bases)
               for node in ast.walk(tree)):
            homes.add(_relative(path))
    assert homes and homes <= set(PLOT_MODULES), sorted(homes - set(PLOT_MODULES))


def test_only_the_shell_binding_imports_the_shell_viewmodels():
    violations = [f"{_relative(path)}:{use}"
                  for path in _project_sources()
                  if _relative(path) not in SHELL_VIEWMODEL_IMPORTERS
                  and _relative(path) not in NEW_VIEWMODELS
                  for use in shell_viewmodel_uses(path)]
    assert not violations, "\n".join(violations)


def test_pages_and_chrome_hold_no_shell_viewmodel():
    violations = [f"{_relative(path)}:{use}"
                  for path in _project_sources() if _relative(path).startswith(SHELL_VIEWMODEL_FREE)
                  for use in shell_viewmodel_holders(path)]
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("relative_path", VIEWMODEL_FREE)
def test_context_and_watcher_hold_no_viewmodel(relative_path):
    found = viewmodel_holders(PROJECT_ROOT / relative_path)
    assert not found, f"{relative_path}: " + ", ".join(found)


@pytest.mark.parametrize("check, snippet, flagged", [
    (plot_violations, "from src.ui.viewmodels import UiScaleViewModel", True),
    (plot_violations, "from src.ui.viewmodels.app_viewmodel import AppViewModel", True),
    (plot_violations, "from src.ui.policy.scale import ZOOM_LADDER", True),
    (plot_violations, "import src.infrastructure.preferences", True),
    (plot_violations, "from src.infrastructure.container import ApplicationContainer", True),
    (plot_violations, "from PySide6.QtCore import QSettings", True),
    (plot_violations, "from src.ui.policy.tokens import Dim", False),
    (shell_viewmodel_uses, "from src.ui.viewmodels import ShellViewModel", True),
    (shell_viewmodel_uses, "from src.ui.viewmodels.ui_scale_viewmodel import UiScaleViewModel",
     True),
    (shell_viewmodel_uses, "import src.ui.viewmodels.shell_viewmodel", True),
    (shell_viewmodel_uses, "import src.ui.viewmodels as vms\nvms.UiScaleViewModel", True),
    (shell_viewmodel_uses, "from src.ui.viewmodels import AppViewModel", False),
    (shell_viewmodel_holders, "self.ui_scale_viewmodel = window.ui_scale_viewmodel", True),
    (shell_viewmodel_holders, "def __init__(self, scale_vm):\n    pass", True),
    (shell_viewmodel_holders, "page.bind(shell_vm=x)", True),
    (shell_viewmodel_holders, "self._viewmodel = viewmodel", False),
    (viewmodel_holders, "self._viewmodel = viewmodel", True),
    (viewmodel_holders, "def __init__(self, window, vm):\n    pass", True),
    (viewmodel_holders, "from src.ui.viewmodels.app_viewmodel import AppViewModel", True),
    (viewmodel_holders, "self._window = window", False),
])
def test_placement_checks_have_teeth(tmp_path, check, snippet, flagged):
    assert bool(check(_probe(tmp_path, snippet))) is flagged
