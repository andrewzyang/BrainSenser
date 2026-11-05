"""
Regression tests for the AnalysisPage Protocol.

The AnalysisPage Protocol (src/ui/protocols/analysis_page.py) defines
the structural contract every analysis page must satisfy:
    - load_patient(patient_id: str)
    - clear_view()
    - export_plot()
    - copy_table_to_clipboard()

main.py uses this contract to register and wire pages generically.
If a new page is added (e.g., when the empty ML page is populated) and
silently drifts from the contract, these tests fail before the page
reaches main.py wiring.

Tests use ``issubclass`` rather than ``isinstance`` because the latter
would require instantiating the views — which in turn requires booting
the DI container, a live QApplication, and every core service. The
Protocol only declares methods (not instance attributes), so
``issubclass`` is sufficient: ``@runtime_checkable`` walks the
Protocol's methods and checks each exists on the class.
"""

from PySide6.QtWidgets import QWidget

from src.ui.protocols.analysis_page import AnalysisPage
from src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view import Snapshots5HzBandView
from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView


EXPECTED_METHODS = frozenset({
    "load_patient",
    "clear_view",
    "export_plot",
    "copy_table_to_clipboard",
})


# ============================================================================
# Protocol surface
# ============================================================================


class TestProtocolSurface:
    """Sanity checks on the Protocol itself."""

    def test_protocol_declares_expected_methods(self):
        """Every method in the documented contract must exist on the Protocol."""
        protocol_members = set(AnalysisPage.__dict__.keys())
        missing = EXPECTED_METHODS - protocol_members
        assert not missing, (
            f"AnalysisPage protocol is missing required methods: {sorted(missing)}. "
            "Update src/ui/protocols/analysis_page.py to add them, or update "
            "EXPECTED_METHODS here if the contract has intentionally changed."
        )

    def test_protocol_is_runtime_checkable(self):
        """issubclass/isinstance must work — otherwise tests can't enforce it."""
        assert hasattr(AnalysisPage, "_is_runtime_protocol"), (
            "AnalysisPage must be decorated with @runtime_checkable, otherwise "
            "issubclass/isinstance checks will raise TypeError at runtime."
        )


# ============================================================================
# Concrete view conformance
# ============================================================================


class TestConcreteViewConformance:
    """Every concrete analysis page must satisfy the Protocol."""

    def test_snapshots_psd_view_conforms(self):
        for method in EXPECTED_METHODS:
            attr = getattr(SnapshotsPsdView, method, None)
            assert callable(attr), (
                f"SnapshotsPsdView is missing method {method!r} required by "
                "AnalysisPage protocol."
            )
        assert issubclass(SnapshotsPsdView, AnalysisPage)

    def test_snapshots_5hz_band_view_conforms(self):
        for method in EXPECTED_METHODS:
            attr = getattr(Snapshots5HzBandView, method, None)
            assert callable(attr), (
                f"Snapshots5HzBandView is missing method {method!r} required by "
                "AnalysisPage protocol."
            )
        assert issubclass(Snapshots5HzBandView, AnalysisPage)


# ============================================================================
# Negative case — Protocol must have teeth
# ============================================================================


class TestProtocolDiscriminates:
    """A bare QWidget must NOT conform — if it does, the Protocol is empty."""

    def test_bare_qwidget_does_not_conform(self):
        assert not issubclass(QWidget, AnalysisPage), (
            "A bare QWidget should not satisfy AnalysisPage — the Protocol "
            "has been gutted to the point it no longer enforces anything."
        )

    def test_empty_class_does_not_conform(self):
        class NotAPage:
            pass

        assert not issubclass(NotAPage, AnalysisPage)
