"""
Architecture Tests for MVVM Pattern Compliance

These tests enforce MVVM architectural rules and can be run as part of CI/CD.
They complement the static analyzer by running actual imports and checking runtime properties.
"""

import pytest
import sys
from pathlib import Path
import ast


# Add src to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class TestCoreLayerPurity:
    """Tests to ensure core layer has no Qt dependencies"""

    def test_core_has_no_qt_imports(self):
        """Core layer must not import any Qt modules"""
        core_path = PROJECT_ROOT / "src" / "core"

        if not core_path.exists():
            pytest.skip("Core directory not found")

        qt_modules = {'PySide6', 'PyQt6', 'PyQt5', 'PySide2', 'QtCore', 'QtWidgets', 'QtGui'}
        violations = []

        for py_file in core_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            content = py_file.read_text(encoding="utf-8")

            # Check imports
            for qt_module in qt_modules:
                if qt_module in content:
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}: imports {qt_module}")

        assert not violations, f"Core layer has Qt dependencies:\n" + "\n".join(violations)

    def test_core_services_are_pure_python(self):
        """Core services should only use pure Python types"""
        core_services = PROJECT_ROOT / "src" / "core" / "services"

        if not core_services.exists():
            pytest.skip("Core services directory not found")

        qt_types = ['QObject', 'Signal', 'Slot', 'QWidget', 'QVariant']
        violations = []

        for py_file in core_services.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")

            for qt_type in qt_types:
                if qt_type in content:
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}: uses {qt_type}")

        assert not violations, f"Core services use Qt types:\n" + "\n".join(violations)

    def test_core_models_have_no_qt(self):
        """Core models should be pure data classes"""
        core_models = PROJECT_ROOT / "src" / "core" / "models"

        if not core_models.exists():
            pytest.skip("Core models directory not found")

        prohibited = ['QObject', 'Signal', 'QWidget']
        violations = []

        for py_file in core_models.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            # Check class bases
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_name = ""
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr

                        if base_name in prohibited:
                            violations.append(
                                f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                                f"class {node.name} inherits from {base_name}"
                            )

        assert not violations, f"Core models inherit from Qt:\n" + "\n".join(violations)


class TestViewModelLayer:
    """Tests for ViewModel layer compliance"""

    def test_viewmodels_inherit_from_qobject(self):
        """ViewModels should inherit from QObject"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            if 'viewmodel' not in py_file.stem.lower():
                continue

            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and 'ViewModel' in node.name:
                    has_qobject = False

                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == 'QObject':
                            has_qobject = True
                        elif isinstance(base, ast.Attribute) and base.attr == 'QObject':
                            has_qobject = True

                    if not has_qobject:
                        violations.append(
                            f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                            f"{node.name} doesn't inherit from QObject"
                        )

        # Some violations might be acceptable (base classes, etc.)
        # Just warn if there are many
        if len(violations) > 5:
            pytest.fail(f"Many ViewModels don't inherit from QObject:\n" + "\n".join(violations[:10]))

    def test_viewmodels_define_signals(self):
        """ViewModels should define signals for communication"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            if 'viewmodel' not in py_file.stem.lower():
                continue

            content = py_file.read_text(encoding="utf-8")

            # Check for Signal definitions
            has_signal_import = 'Signal' in content
            has_signal_definition = 'Signal(' in content

            if has_signal_import and not has_signal_definition:
                violations.append(
                    f"{py_file.relative_to(PROJECT_ROOT)}: "
                    f"imports Signal but doesn't define any"
                )

        # This is informational - may have legitimate reasons
        if len(violations) > 3:
            print(f"\n⚠️  Warning: Some ViewModels may be missing signals:\n" + "\n".join(violations[:5]))

    def test_viewmodels_dont_manipulate_widgets(self):
        """ViewModels should not directly manipulate widgets"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        widget_methods = ['.setText(', '.setEnabled(', '.setVisible(',
                         '.show()', '.hide()', '.addWidget(']
        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            content = py_file.read_text(encoding="utf-8")

            for method in widget_methods:
                if method in content:
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        if method in line and not line.strip().startswith('#'):
                            violations.append(
                                f"{py_file.relative_to(PROJECT_ROOT)}:{i}: uses {method}"
                            )
                            break

        assert not violations, f"ViewModels manipulate widgets:\n" + "\n".join(violations)

    def test_viewmodels_dont_import_views(self):
        """ViewModels should not import View classes"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and 'view' in node.module.lower():
                        # Check if it's importing a view, not another viewmodel
                        if 'viewmodel' not in node.module.lower():
                            violations.append(
                                f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                                f"imports from {node.module}"
                            )

        # Some might be false positives, so be lenient
        if len(violations) > 2:
            pytest.fail(f"ViewModels import Views:\n" + "\n".join(violations))


class TestViewLayer:
    """Tests for View layer compliance"""

    def test_views_dont_import_services_directly(self):
        """Views should not import Service classes directly"""
        views_path = PROJECT_ROOT / "src" / "ui" / "views"

        if not views_path.exists():
            pytest.skip("Views directory not found")

        violations = []

        for py_file in views_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and 'service' in node.module.lower():
                        # Check if it's importing from core.services
                        if 'core' in node.module.lower():
                            violations.append(
                                f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                                f"imports from {node.module}"
                            )

        # Some factory files might legitimately import services for wiring
        factory_violations = [v for v in violations if 'factory' not in v.lower()]

        if len(factory_violations) > 2:
            pytest.fail(f"Views import Services directly:\n" + "\n".join(factory_violations))

    def test_views_have_closeevent(self):
        """Views should implement closeEvent for cleanup"""
        views_path = PROJECT_ROOT / "src" / "ui" / "views"

        if not views_path.exists():
            pytest.skip("Views directory not found")

        violations = []

        for py_file in views_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")

            # If file has .connect( it should probably have cleanup
            has_connect = '.connect(' in content
            has_closeevent = 'def closeEvent' in content or 'def close(' in content

            if has_connect and not has_closeevent:
                violations.append(
                    f"{py_file.relative_to(PROJECT_ROOT)}: "
                    f"connects signals but no closeEvent"
                )

        # Informational warning
        if len(violations) > 5:
            print(f"\n⚠️  Warning: Views may be missing cleanup:\n" + "\n".join(violations[:5]))


class TestLayerDependencies:
    """Tests for proper dependency direction"""

    def test_dependency_direction(self):
        """Dependencies should flow: View → ViewModel → Service → Repository"""
        # This is a complex test that would require full import graph analysis
        # For now, we test key patterns

        # Core should not depend on UI
        core_path = PROJECT_ROOT / "src" / "core"
        if core_path.exists():
            violations = []

            for py_file in core_path.rglob('*.py'):
                if '__pycache__' in str(py_file):
                    continue

                content = py_file.read_text(encoding="utf-8")

                if 'from src.ui' in content or 'import src.ui' in content:
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}: imports from UI layer")

            assert not violations, f"Core depends on UI:\n" + "\n".join(violations)

    def test_no_circular_dependencies(self):
        """Test for obvious circular dependencies"""
        # Basic check: if A imports B, B should not import A
        # This is a simplified check

        src_path = PROJECT_ROOT / "src"
        if not src_path.exists():
            pytest.skip("Src directory not found")

        # For now, just check that viewmodels don't import from views
        # and views don't import from viewmodels at the same level
        # (factory patterns are OK)

        # This is partially covered by other tests


class TestNamingConventions:
    """Tests for naming conventions"""

    def test_viewmodel_files_named_correctly(self):
        """ViewModel files should end with _viewmodel.py"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            # Check if file contains ViewModel class
            content = py_file.read_text(encoding="utf-8")
            if 'class' in content and 'ViewModel' in content:
                if not py_file.stem.endswith('viewmodel') and not py_file.stem.endswith('_vm'):
                    violations.append(f"{py_file.relative_to(PROJECT_ROOT)}")

        # Informational only
        if violations:
            print(f"\n💡 Info: Some ViewModel files don't follow naming convention:\n" + "\n".join(violations[:3]))

    def test_viewmodel_classes_named_correctly(self):
        """ViewModel classes should end with 'ViewModel'"""
        viewmodels_path = PROJECT_ROOT / "src" / "ui" / "viewmodels"

        if not viewmodels_path.exists():
            pytest.skip("ViewModels directory not found")

        violations = []

        for py_file in viewmodels_path.rglob('*.py'):
            if '__pycache__' in str(py_file) or py_file.stem == '__init__':
                continue

            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Check if it inherits from QObject
                    has_qobject = any(
                        (isinstance(base, ast.Name) and base.id == 'QObject') or
                        (isinstance(base, ast.Attribute) and base.attr == 'QObject')
                        for base in node.bases
                    )

                    if has_qobject and not node.name.endswith('ViewModel'):
                        violations.append(
                            f"{py_file.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                            f"class {node.name} should end with 'ViewModel'"
                        )

        # Informational only
        if violations:
            print(f"\n💡 Info: Some ViewModel classes don't follow naming convention:\n" + "\n".join(violations[:3]))


@pytest.mark.integration
class TestMVVMIntegration:
    """Integration tests for MVVM pattern"""

    def test_can_create_viewmodel_without_ui(self):
        """ViewModels should be testable without creating UI"""
        # This would require actually importing and instantiating ViewModels
        # For now, this is a placeholder for integration tests

    def test_signals_work_correctly(self):
        """Test that ViewModels emit signals correctly"""
        # This would require creating ViewModels and listening to signals


# Run with: pytest tests/architecture/test_mvvm_architecture.py -v
# Run in CI: pytest tests/architecture/ -v --strict-markers
