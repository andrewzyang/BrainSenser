"""
AnalysisPage protocol.

Every analysis page in the app (Timeline + Snapshots, Snapshots PSD,
Snapshots 5 Hz Band, and any future page) must satisfy this structural
contract. main.py uses it to register pages generically instead of
duplicating wiring blocks per page, and tests assert that every
concrete view conforms.

Why a Protocol (not a base class)
---------------------------------
PySide6 does NOT support multiple inheritance from two QObject-based
classes. Every page already inherits from QWidget, so a concrete
``BaseAnalysisPage(QWidget)`` would force a diamond-or-swap refactor
to introduce. A `typing.Protocol` sidesteps that entirely: pages
conform structurally just by having the right method names, with no
inheritance change required.

Contract surface
----------------
Methods (declared below and checked at runtime):
    load_patient(patient_id: str) -> None
        Load data for a patient into the page.
    clear_view() -> None
        Reset the view and clear any loaded patient data.
    export_plot() -> None
        Export the current plots/results to a file (user-driven; the
        page is responsible for its own file dialog and error
        reporting).
    copy_table_to_clipboard() -> None
        Copy the current statistics table to the clipboard.

Attributes (documented but NOT in the Protocol body):
    viewmodel: QObject
        The page's underlying viewmodel. Must expose an
        ``error_occurred: Signal(str)`` signal that the page's own
        ``_on_error`` slot handles (MainWindow does NOT route these,
        see tests/unit/test_main_error_routing.py).
    export_state_changed: Signal(bool)
        Class-level Qt Signal emitted when the page's export readiness
        changes. MainWindow connects it to its toolbar router.

These attributes are documented rather than declared in the Protocol
body because (a) Qt ``Signal`` descriptors are class-level attributes
that don't satisfy Protocol hasattr-style checks cleanly, and (b)
``viewmodel`` is an instance attribute set in ``__init__`` which
``issubclass(cls, Protocol)`` cannot see.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class AnalysisPage(Protocol):
    """Structural contract every analysis page must satisfy."""

    def load_patient(self, patient_id: str) -> None:
        """Load data for a patient into the page."""
        ...

    def clear_view(self) -> None:
        """Reset the view and clear any loaded patient data."""
        ...

    def export_plot(self) -> None:
        """Export the current plots/results to a file."""
        ...

    def copy_table_to_clipboard(self) -> None:
        """Copy the current statistics table to the clipboard."""
        ...
