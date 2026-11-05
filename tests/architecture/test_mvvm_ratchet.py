"""
Exact-set ratchets behind the three MVVM architecture checks that already fail,
and two more View rules with their own records.

test_core_has_no_qt_imports, test_core_services_are_pure_python and
test_views_dont_import_services_directly (test_mvvm_architecture.py) fail on a
clean tree and are listed in tests/known_failures.txt, where a new violation
would hide among the old ones. Each is backed here by its recorded violations,
rescanned with the same rules (line numbers dropped): a new violation fails; a
recorded one that disappeared passes with a warning so the record can shrink.

The last scans only src/ui/views; OTHER_VIEWS_IMPORT_SERVICES holds the other
View packages to the same rule (none has a violation). VM_LAMBDA_CONNECTIONS
records the lambdas and partials wired to ViewModels (plan R7).
"""

import ast
import re
import warnings
from collections import Counter
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# test_core_has_no_qt_imports: (file, Qt name anywhere in its text).
CORE_QT_TEXT = [
    # A comment ("pulls PySide6") in the vendored threshold engine, not an import.
    ("src/core/analysis/threshold/bulletproof_threshold.py", "PySide6"),
]

# test_core_services_are_pure_python: (file, Qt type name anywhere in its text).
CORE_SERVICES_QT_TYPES = [
    # "Signal" inside the name SignalIntegrityCleaner.
    ("src/core/services/streaming_service.py", "Signal"),
]

# test_views_dont_import_services_directly: (view file, core service module),
# one entry per import statement (9 statements, 6 distinct pairs).
VIEWS_IMPORT_SERVICES = [
    ("src/ui/views/snapshots_5hz_band/components/dual_hemisphere_auc_widget.py",
     "src.core.services.snapshot_ml_analysis_service"),
    ("src/ui/views/snapshots_5hz_band/components/grouping_panel.py",
     "src.core.services.snapshot_ml_analysis_service"),
    ("src/ui/views/timeline_lfp_threshold/components/dual_hemisphere_violin_widget.py",
     "src.core.services.timeline_threshold_ml_service"),
    ("src/ui/views/timeline_lfp_threshold/components/dual_hemisphere_violin_widget.py",
     "src.core.services.timeline_threshold_ml_service"),
    ("src/ui/views/timeline_lfp_threshold/components/grouping_panel.py",
     "src.core.services.timeline_threshold_ml_service"),
    ("src/ui/views/timeline_lfp_threshold/components/grouping_panel.py",
     "src.core.services.timeline_threshold_ml_service"),
    ("src/ui/views/timeline_peri_event/components/peri_event_plot.py",
     "src.core.services.timeline_peri_event_service"),
    ("src/ui/views/timeline_peri_event/components/peri_event_plot.py",
     "src.core.services.timeline_peri_event_service"),
    ("src/ui/views/timeline_peri_event/components/statistics_table_widget.py",
     "src.core.services.timeline_peri_event_service"),
]

# The View packages besides src/ui/views, under the same rule (plain imports,
# imported names and __init__ files included): (file, imported target).
OTHER_VIEW_PACKAGES = ("src/ui/components", "src/ui/shell", "src/ui/layouts", "src/ui/widgets",
                       "src/ui/protocols", "src/ui/utils", "src/ui/export")
OTHER_VIEWS_IMPORT_SERVICES = []

# R7: ViewModels outlive windows (tests build several windows on one container's
# ViewModels). Their signals reach bound methods of View objects, and View
# signals reach their slots directly; a lambda or partial keeps whatever it
# captured alive and can't be told apart on disconnect. (file, "signal ->
# lambda|partial"), one entry per connect() whose signal or callable involves a
# ViewModel.
VM_LAMBDA_CONNECTIONS = [
    # MainWindow._connect_signals, kept as it is (plan R11)
    ("main.py", "self.app_viewmodel.patient_selected -> lambda"),
    ("main.py", "self.app_viewmodel.patient_selected -> lambda"),
    # main(): the end of the splash queues the main window
    ("main.py", "splash_vm.closed -> lambda"),
]
VIEWMODEL_NAME = re.compile(r"viewmodel|(^|_)vm$", re.IGNORECASE)


def _sources(directory, *, skip_init):
    """(path relative to the project root, text) of every .py file, as scanned there."""
    for py_file in sorted((PROJECT_ROOT / directory).rglob("*.py")):
        if "__pycache__" in str(py_file) or (skip_init and py_file.stem == "__init__"):
            continue
        yield py_file.relative_to(PROJECT_ROOT).as_posix(), py_file.read_text(encoding="utf-8")


def core_qt_text():
    qt_modules = ["PySide6", "PyQt6", "PyQt5", "PySide2", "QtCore", "QtWidgets", "QtGui"]
    return [
        (path, name)
        for path, content in _sources("src/core", skip_init=False)
        for name in qt_modules
        if name in content
    ]


def core_services_qt_types():
    qt_types = ["QObject", "Signal", "Slot", "QWidget", "QVariant"]
    return [
        (path, name)
        for path, content in _sources("src/core/services", skip_init=True)
        for name in qt_types
        if name in content
    ]


def views_import_services():
    imports = []
    for path, content in _sources("src/ui/views", skip_init=True):
        for node in ast.walk(ast.parse(content)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "service" in node.module.lower()
                and "core" in node.module.lower()
            ):
                imports.append((path, node.module))
    # The original exempts anything whose report mentions "factory" (DI wiring).
    return [
        (path, module)
        for path, module in imports
        if "factory" not in f"{path} {module}".lower()
    ]


def _python_files(root, directories):
    for directory in directories:
        for py_file in sorted((root / directory).rglob("*.py")):
            if "__pycache__" not in py_file.parts:
                yield py_file.relative_to(root).as_posix(), py_file


def other_views_import_services(root=PROJECT_ROOT):
    """views_import_services' rule over OTHER_VIEW_PACKAGES, on every import target."""
    found = []
    for path, py_file in _python_files(root, OTHER_VIEW_PACKAGES):
        for node in ast.walk(ast.parse(py_file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [f"{node.module or ''}.{alias.name}" for alias in node.names]
            else:
                continue
            found += [(path, target) for target in targets
                      if "service" in target.lower() and "core" in target.lower()
                      and "factory" not in f"{path} {target}".lower()]
    return found


def _mentions_viewmodel(node):
    return any(VIEWMODEL_NAME.search(n.id if isinstance(n, ast.Name) else n.attr)
               for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute)))


def _deferred_callable(node):
    """The kind of deferred callable ``node`` builds ("lambda", "partial"), or None."""
    if isinstance(node, ast.Lambda):
        return "lambda"
    if isinstance(node, ast.Call) and ast.unparse(node.func) in ("partial", "functools.partial"):
        return "partial"
    return None


def vm_lambda_connections(root=PROJECT_ROOT):
    """(file, "signal -> lambda|partial") of each connect() in main.py and src/ui
    that hands a lambda or partial to a ViewModel signal, or wraps a ViewModel in one."""
    files = [("main.py", root / "main.py")] if (root / "main.py").exists() else []
    found = []
    for path, py_file in files + list(_python_files(root, ("src/ui",))):
        for node in ast.walk(ast.parse(py_file.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"):
                continue
            for slot in node.args[:1] + [k.value for k in node.keywords if k.arg == "slot"]:
                kind = _deferred_callable(slot)
                if kind and (_mentions_viewmodel(node.func.value) or _mentions_viewmodel(slot)):
                    found.append((path, f"{ast.unparse(node.func.value)} -> {kind}"))
    return found


def _check_ratchet(actual, recorded, recorded_name):
    actual, recorded = Counter(actual), Counter(recorded)
    new = actual - recorded
    assert not new, (
        f"New MVVM violation(s) not recorded in {recorded_name} (fix them):\n"
        + "\n".join(f"  {path}: {token}" for path, token in sorted(new.elements()))
    )
    gone = recorded - actual
    if gone:
        warnings.warn(
            f"ratchet can be tightened: remove from {recorded_name}: "
            + "; ".join(f"{path}: {token}" for path, token in sorted(gone.elements())),
            stacklevel=2,
        )


def test_core_qt_text_ratchet():
    _check_ratchet(core_qt_text(), CORE_QT_TEXT, "CORE_QT_TEXT")


def test_core_services_qt_types_ratchet():
    _check_ratchet(core_services_qt_types(), CORE_SERVICES_QT_TYPES, "CORE_SERVICES_QT_TYPES")


def test_views_import_services_ratchet():
    _check_ratchet(views_import_services(), VIEWS_IMPORT_SERVICES, "VIEWS_IMPORT_SERVICES")


def test_other_views_import_services_ratchet():
    _check_ratchet(other_views_import_services(), OTHER_VIEWS_IMPORT_SERVICES,
                   "OTHER_VIEWS_IMPORT_SERVICES")


def test_viewmodel_lambda_connections_ratchet():
    _check_ratchet(vm_lambda_connections(), VM_LAMBDA_CONNECTIONS, "VM_LAMBDA_CONNECTIONS")


# ------------------------------------------------------------- the new checks bite

def _tree(tmp_path, files):
    for relative_path, source in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return tmp_path


@pytest.mark.parametrize("relative_path, source, found", [
    ("src/ui/components/panel.py", "from src.core.services.patient_service import PatientService",
     [("src/ui/components/panel.py", "src.core.services.patient_service.PatientService")]),
    ("src/ui/shell/actions.py", "import src.core.services.statistics_service",
     [("src/ui/shell/actions.py", "src.core.services.statistics_service")]),
    ("src/ui/widgets/__init__.py", "from src.core import services",
     [("src/ui/widgets/__init__.py", "src.core.services")]),
    ("src/ui/export/router.py", "from src.core.models import Patient", []),
    ("src/ui/components/factory.py", "from src.core.services import PatientService", []),
    ("src/ui/views/page.py", "from src.core.services import PatientService", []),  # legacy rule's
])
def test_other_views_check_has_teeth(tmp_path, relative_path, source, found):
    assert other_views_import_services(_tree(tmp_path, {relative_path: source})) == found


@pytest.mark.parametrize("source, found", [
    ("self.vm.state_changed.connect(lambda state: self.show(state))",
     ["self.vm.state_changed -> lambda"]),
    ("self.button.clicked.connect(lambda: self._viewmodel.zoom_in())",
     ["self.button.clicked -> lambda"]),
    ("self.button.clicked.connect(partial(self.scale_vm.select, 1))",
     ["self.button.clicked -> partial"]),
    ("vm.changed.connect(slot=functools.partial(print, 1))", ["vm.changed -> partial"]),
    ("self.vm.state_changed.connect(self.show)", []),
    ("self.button.clicked.connect(self.vm.zoom_in)", []),
    ("self.button.clicked.connect(lambda: self._add_to_group(1))", []),
])
def test_lambda_check_has_teeth(tmp_path, source, found):
    root = _tree(tmp_path, {"src/ui/views/page.py": source})
    assert vm_lambda_connections(root) == [("src/ui/views/page.py", f) for f in found]


def test_a_new_entry_fails_the_ratchet():
    with pytest.raises(AssertionError, match="New MVVM violation"):
        _check_ratchet([("src/ui/views/page.py", "vm.changed -> lambda")], [], "RECORD")
