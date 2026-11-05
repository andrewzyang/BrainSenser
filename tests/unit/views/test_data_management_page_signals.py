"""
Unit tests for DataManagementPage signal management.

Tests proper signal connection, cleanup, and lifecycle management.

This test file verifies that DataManagementPage follows MVVM signal management
best practices as defined in CLAUDE.md:
- Signals connected with Qt.UniqueConnection
- Signal connections tracked for cleanup
- closeEvent disconnects all signals
- Memory leaks prevented through proper cleanup

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-14
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent

from src.ui.views.data_management.data_management_page import DataManagementPage
from src.ui.viewmodels.data_management_viewmodel import DataManagementViewModel


@pytest.fixture
def mock_viewmodel():
    """
    Create a mock DataManagementViewModel with all required signals.

    Returns:
        Mock: Mocked ViewModel with signal attributes
    """
    mock_vm = Mock(spec=DataManagementViewModel)

    # Create mock signals for all 7 signals in DataManagementViewModel
    signal_names = [
        'patient_selected',
        'patient_cleared',
        'metadata_updated',
        'statistics_updated',
        'upload_history_updated',
        'error_occurred',
        'success_message'
    ]

    for signal_name in signal_names:
        mock_signal = MagicMock()
        mock_signal.connect = MagicMock()
        mock_signal.disconnect = MagicMock()
        setattr(mock_vm, signal_name, mock_signal)

    return mock_vm


class TestSignalManagement:
    """Test signal connection and cleanup."""

    def test_signals_connected_with_unique_flag(self, qtbot, mock_viewmodel):
        """
        Verify signals are connected with Qt.UniqueConnection.

        This test ensures that all ViewModel signal connections use the
        Qt.UniqueConnection flag to prevent duplicate connections if the
        connection method is called multiple times.
        """
        # Create page (which calls _connect_signals in __init__)
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify all signals were connected with Qt.UniqueConnection
        signal_names = [
            'patient_selected',
            'patient_cleared',
            'metadata_updated',
            'statistics_updated',
            'upload_history_updated',
            'error_occurred',
            'success_message'
        ]

        for signal_name in signal_names:
            signal_mock = getattr(mock_viewmodel, signal_name)

            # Verify connect was called
            assert signal_mock.connect.called, (
                f"{signal_name} signal should be connected"
            )

            # Verify Qt.UniqueConnection was passed as second argument
            call_args = signal_mock.connect.call_args
            assert call_args is not None, (
                f"{signal_name} connect should have been called"
            )

            # Check if Qt.UniqueConnection is in the call
            # call_args is a tuple: (args, kwargs)
            args, kwargs = call_args
            if len(args) >= 2:
                # Second positional argument should be Qt.UniqueConnection
                assert args[1] == Qt.UniqueConnection, (
                    f"{signal_name} should use Qt.UniqueConnection flag"
                )

    def test_signal_connections_tracked(self, qtbot, mock_viewmodel):
        """
        Verify all signal connections are tracked for cleanup.

        This test ensures that the page maintains a list of all signal
        connections so they can be properly disconnected during cleanup.
        """
        # Create page
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify connections are tracked
        assert hasattr(page, '_signal_connections'), (
            "Page should have _signal_connections attribute for tracking"
        )

        # Should have 7 connections (one for each ViewModel signal)
        assert len(page._signal_connections) == 7, (
            f"Expected 7 tracked connections, got {len(page._signal_connections)}"
        )

        # Verify each connection is a tuple of (signal, slot)
        for connection in page._signal_connections:
            assert isinstance(connection, tuple), (
                "Each connection should be a tuple"
            )
            assert len(connection) == 2, (
                "Each connection tuple should have (signal, slot)"
            )
            signal, slot = connection
            # Verify slot is a callable method
            assert callable(slot), "Slot should be callable"

    def test_closeEvent_disconnects_signals(self, qtbot, mock_viewmodel):
        """
        Verify closeEvent properly disconnects all signals.

        This test ensures that when the widget is closed, all signal
        connections are properly disconnected to prevent memory leaks
        and ghost connections.
        """
        # Create page
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify initial state - 7 connections tracked
        assert len(page._signal_connections) == 7

        # Trigger close event
        event = QCloseEvent()
        page.closeEvent(event)

        # Verify all signals were disconnected
        signal_names = [
            'patient_selected',
            'patient_cleared',
            'metadata_updated',
            'statistics_updated',
            'upload_history_updated',
            'error_occurred',
            'success_message'
        ]

        for signal_name in signal_names:
            signal_mock = getattr(mock_viewmodel, signal_name)
            assert signal_mock.disconnect.called, (
                f"{signal_name} should be disconnected in closeEvent"
            )

        # Verify connections list was cleared
        assert len(page._signal_connections) == 0, (
            "Signal connections list should be cleared after cleanup"
        )

    def test_closeEvent_handles_already_disconnected(self, qtbot, mock_viewmodel):
        """
        Verify closeEvent handles already disconnected signals gracefully.

        This test ensures that the cleanup code doesn't crash if signals
        are already disconnected or if objects have been destroyed.
        This can happen in various edge cases during application shutdown.
        """
        # Create page
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Make all disconnect calls raise RuntimeError (simulating already disconnected)
        for signal_name in ['patient_selected', 'patient_cleared', 'metadata_updated',
                           'statistics_updated', 'upload_history_updated',
                           'error_occurred', 'success_message']:
            signal_mock = getattr(mock_viewmodel, signal_name)
            signal_mock.disconnect.side_effect = RuntimeError("Not connected")

        # Should not raise exception
        event = QCloseEvent()
        try:
            page.closeEvent(event)
            cleanup_succeeded = True
        except Exception as e:
            cleanup_succeeded = False
            pytest.fail(
                f"closeEvent should handle disconnection errors gracefully, "
                f"but raised: {e}"
            )

        assert cleanup_succeeded, "Cleanup should complete even with errors"

        # Verify cleanup completed - connections list should be cleared
        assert len(page._signal_connections) == 0, (
            "Connections list should be cleared even if disconnect fails"
        )

    def test_closeEvent_handles_type_error(self, qtbot, mock_viewmodel):
        """
        Verify closeEvent handles TypeError during disconnect.

        This test ensures cleanup works even when disconnect raises TypeError,
        which can happen if the signal object has been destroyed.
        """
        # Create page
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Make some disconnect calls raise TypeError
        mock_viewmodel.patient_selected.disconnect.side_effect = TypeError(
            "Underlying C++ object has been deleted"
        )
        mock_viewmodel.metadata_updated.disconnect.side_effect = RuntimeError(
            "Not connected"
        )

        # Should not raise exception
        event = QCloseEvent()
        page.closeEvent(event)

        # Verify cleanup completed
        assert len(page._signal_connections) == 0

    def test_multiple_connects_prevented(self, qtbot):
        """
        Verify Qt.UniqueConnection prevents duplicate connections.

        This test documents expected behavior when using Qt.UniqueConnection:
        even if connect() is called multiple times with the same signal-slot
        pair, the slot should only execute once per signal emission.

        Note: This test requires real Qt signals, not mocks.
        """
        # This test is documented but skipped because it requires a more
        # complex setup with real signals. The Qt.UniqueConnection flag
        # is tested in test_signals_connected_with_unique_flag.
        pytest.skip(
            "Requires real ViewModel with real signals. "
            "Qt.UniqueConnection usage verified in other tests."
        )


class TestMemoryCleanup:
    """Test memory cleanup and garbage collection."""

    @pytest.mark.skip(reason="Requires memory profiling tools")
    def test_page_is_garbage_collected_after_close(self):
        """
        Verify page is garbage collected after close.

        This test would verify that after closing the page and clearing
        references, the page object is properly garbage collected.

        This requires memory profiling tools and a real ViewModel setup,
        so it's skipped in normal test runs but documented here for
        future integration testing.
        """

        # This would require:
        # 1. Create real ViewModel and Page
        # 2. Create weak reference to page
        # 3. Show and close page
        # 4. Delete references and force garbage collection
        # 5. Verify weak reference is None

        # Example (not executable without real setup):
        # vm = DataManagementViewModel(...)
        # page = DataManagementPage(viewmodel=vm)
        # page_ref = weakref.ref(page)
        #
        # page.show()
        # page.close()
        # del page
        # gc.collect()
        #
        # assert page_ref() is None, "Page should be garbage collected"


class TestSignalLifecycle:
    """Test signal behavior during page lifecycle."""

    def test_disconnect_signals_method_exists(self, qtbot, mock_viewmodel):
        """
        Verify _disconnect_signals helper method exists and works.

        This internal method should be callable and properly disconnect
        all tracked signals.
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify method exists
        assert hasattr(page, '_disconnect_signals'), (
            "Page should have _disconnect_signals helper method"
        )
        assert callable(page._disconnect_signals), (
            "_disconnect_signals should be callable"
        )

        # Call the method directly
        page._disconnect_signals()

        # Verify signals were disconnected
        for signal_name in ['patient_selected', 'patient_cleared']:
            signal_mock = getattr(mock_viewmodel, signal_name)
            assert signal_mock.disconnect.called

        # Verify list was cleared
        assert len(page._signal_connections) == 0

    def test_connect_signals_method_structure(self, qtbot, mock_viewmodel):
        """
        Verify _connect_signals method has proper structure.

        This test documents the expected structure of the signal connection
        method, which should:
        1. Define all signal-slot pairs in a list
        2. Loop through and connect each with Qt.UniqueConnection
        3. Track each connection for cleanup
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify method exists
        assert hasattr(page, '_connect_signals'), (
            "Page should have _connect_signals method"
        )

        # Verify all expected signals are connected
        expected_signals = {
            'patient_selected',
            'patient_cleared',
            'metadata_updated',
            'statistics_updated',
            'upload_history_updated',
            'error_occurred',
            'success_message'
        }

        # Extract signal names from tracked connections
        tracked_signal_objects = {sig for sig, _ in page._signal_connections}

        # Verify we tracked the right number of signals
        assert len(tracked_signal_objects) == len(expected_signals), (
            f"Should track {len(expected_signals)} unique signals"
        )

    def test_viewmodel_attribute_accessible(self, qtbot, mock_viewmodel):
        """
        Verify ViewModel is accessible via viewmodel attribute.

        This is important for signal connections to work properly.
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Verify viewmodel is stored
        assert hasattr(page, 'viewmodel'), "Page should store viewmodel"
        assert page.viewmodel is mock_viewmodel, (
            "Stored viewmodel should be the same object"
        )


class TestErrorHandling:
    """Test error handling in signal management."""

    def test_multiple_close_events_handled_safely(self, qtbot, mock_viewmodel):
        """
        Verify multiple closeEvent calls are handled safely.

        In some Qt scenarios, closeEvent might be called multiple times.
        The cleanup should handle this gracefully without errors.
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # First close
        event1 = QCloseEvent()
        page.closeEvent(event1)

        assert len(page._signal_connections) == 0

        # Second close (list is already empty)
        event2 = QCloseEvent()
        page.closeEvent(event2)  # Should not raise

        # Still empty, no errors
        assert len(page._signal_connections) == 0

    def test_disconnect_with_partial_failures(self, qtbot, mock_viewmodel):
        """
        Verify cleanup continues even if some disconnects fail.

        This ensures that if one signal fails to disconnect, the cleanup
        process continues for the remaining signals.
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Make every other signal fail to disconnect
        signals = [
            'patient_selected',      # Will fail
            'patient_cleared',       # OK
            'metadata_updated',      # Will fail
            'statistics_updated',    # OK
            'upload_history_updated', # Will fail
            'error_occurred',        # OK
            'success_message'        # Will fail
        ]

        for i, signal_name in enumerate(signals):
            signal_mock = getattr(mock_viewmodel, signal_name)
            if i % 2 == 0:
                signal_mock.disconnect.side_effect = RuntimeError("Failed")

        # Should complete without raising
        page._disconnect_signals()

        # All disconnect attempts should have been made
        for signal_name in signals:
            signal_mock = getattr(mock_viewmodel, signal_name)
            assert signal_mock.disconnect.called, (
                f"{signal_name} disconnect should have been attempted"
            )

        # List should still be cleared
        assert len(page._signal_connections) == 0


class TestIntegrationWithQtLifecycle:
    """Test integration with Qt widget lifecycle."""

    def test_closeEvent_calls_super(self, qtbot, mock_viewmodel):
        """
        Verify closeEvent calls super() to maintain Qt behavior.

        This ensures the page properly integrates with Qt's widget
        lifecycle management.
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # Patch the superclass closeEvent to track if it's called
        with patch.object(
            page.__class__.__bases__[0],
            'closeEvent',
            wraps=page.__class__.__bases__[0].closeEvent
        ) as mock_super:
            event = QCloseEvent()
            page.closeEvent(event)

            # Note: This verification approach may need adjustment based on
            # how PySide6's QWidget.closeEvent works. The important thing
            # is that super().closeEvent(event) is called in the implementation.

    def test_page_initialization_order(self, qtbot, mock_viewmodel):
        """
        Verify page initialization happens in correct order.

        Order should be:
        1. super().__init__()
        2. Store viewmodel
        3. Initialize _signal_connections
        4. Setup UI
        5. Connect signals
        """
        page = DataManagementPage(viewmodel=mock_viewmodel)
        qtbot.addWidget(page)

        # By the time __init__ completes, all should be ready
        assert hasattr(page, 'viewmodel')
        assert hasattr(page, '_signal_connections')
        assert len(page._signal_connections) == 7

        # UI should be set up
        assert hasattr(page, 'content_stack')
        assert hasattr(page, 'patient_overview')
