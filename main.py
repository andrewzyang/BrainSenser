"""
iEEG BrainSense Application - Main Entry Point

This is the main entry point for the iEEG BrainSense data management application.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import sys
import logging
from typing import TYPE_CHECKING, Optional
from PySide6.QtWidgets import QApplication, QMainWindow, QInputDialog, QMessageBox
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QGuiApplication

if TYPE_CHECKING:
    from src.infrastructure.container import ApplicationContainer
    from src.ui.app_bootstrap import Presentation
    from src.ui.policy.scale import ScreenMetrics
    from src.ui.viewmodels import ShellViewModel, UiScaleViewModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import application components
from src.infrastructure.database.schema import initialize_global_database
from src.ui.components import Sidebar, TopBar, FileOrDirectoryDialog
from src.ui.layouts import MainLayout
from src.ui.shell.screen_watcher import ScreenWatcher
from src.ui.shell.shell_actions import ShellActions
from src.ui.shell.window_placement import apply_initial_geometry, keep_window_floor, launch_screen
from src.ui.utils.screens import screen_of
from src.ui.export.toolbar_state_router import ToolbarExportStateRouter
from src.ui.views.data_management import DataManagementPage
from src.ui.views.snapshots_psd import SnapshotsPsdView
from src.ui.views.snapshots_psd.factory import create_snapshots_psd_view
from src.ui.views.snapshots_5hz_band.factory import create_snapshots_5hz_band_view
from src.ui.views.timeline_lfp_threshold import TimelineLfpThresholdView, create_timeline_lfp_threshold_view
from src.ui.views.timeline_peri_event import TimelinePeriEventView, create_timeline_peri_event_view
from src.ui.protocols import AnalysisPage


class MainWindow(QMainWindow):
    """Main application window."""

    # A window built without __init__ (as tests do) has no shell: it saves no
    # geometry and watches no display.
    shell_viewmodel: Optional["ShellViewModel"] = None
    ui_scale_viewmodel: Optional["UiScaleViewModel"] = None
    _screen_watcher: Optional[ScreenWatcher] = None

    def __init__(self, container: Optional["ApplicationContainer"] = None,
                 presentation: Optional["Presentation"] = None):
        super().__init__()

        self.setWindowTitle("BrainSenser")
        # Shrinks to 600×500 (D3), less on screens too small for that, re-applied
        # on every screen change; pages shorter than their minimum scroll.
        keep_window_floor(self)

        # Router keeps per-page toolbar enablement state
        self._toolbar_export_router = None

        # Optional pre-built presentation (main() shares its container with the
        # splash screen and picked the launch screen) or DI container. Without
        # a container a fresh one is built; without a presentation, one is
        # built from the container (its ViewModels are the container's singletons).
        self._injected_container = (presentation.container if presentation is not None
                                    else container)
        self._presentation = presentation

        # Initialize database and services
        self._initialize_services()

        # Create ViewModels
        self._initialize_viewmodels()

        # Create UI
        self._setup_ui()

        # Wire up signals
        self._connect_signals()
        self._connect_shell_signals()

        # main() places and shows the window (show_at_launch), then calls
        # _load_initial_data().

    def _initialize_services(self):
        """Initialize all services and dependencies using DI container."""
        from src.infrastructure.container import ApplicationContainer

        # Reuse an injected container when provided (e.g. from the startup
        # orchestration that also built the splash), otherwise construct one.
        self.container = self._injected_container or ApplicationContainer()

        logging.info("DI Container initialized")

        # Initialize global database (still needed for schema setup)
        path_resolver = self.container.path_resolver()
        db_adapter = self.container.db_adapter()

        success = initialize_global_database(db_adapter, path_resolver)
        if not success:
            raise RuntimeError("Failed to initialize global database")
        logging.info(f"Global database initialized: {path_resolver.get_global_db_path()}")

        # Store frequently used singletons for convenience
        self.path_resolver = path_resolver
        self.db_adapter = db_adapter

        # Store patient_service for backward compatibility (used in upload/delete dialogs)
        self.patient_service = self.container.patient_service()

        logging.info("All services initialized successfully via DI container")

    def _initialize_viewmodels(self):
        """Initialize ViewModels from DI container."""
        # Resolve all ViewModels from container (auto-injected with dependencies)
        self.app_viewmodel = self.container.app_viewmodel()
        self.data_management_viewmodel = self.container.data_management_viewmodel()

        # The shell and interface-size ViewModels come with the presentation
        if self._presentation is None:
            from src.ui.app_bootstrap import build_presentation
            self._presentation = build_presentation(self.container)
        self.shell_viewmodel = self._presentation.shell_viewmodel
        self.ui_scale_viewmodel = self._presentation.ui_scale_viewmodel

        logging.info("ViewModels initialized successfully via DI container")

    def _setup_ui(self):
        """Setup the user interface."""
        # Create UI components
        self.sidebar = Sidebar()
        self.top_bar = TopBar()

        # Create main layout (combines sidebar + top bar + content)
        self.main_layout = MainLayout(self.sidebar, self.top_bar)

        # Create pages
        self.data_management_page = DataManagementPage(
            viewmodel=self.data_management_viewmodel
        )

        # Create Snapshots PSD page using factory
        self.snapshots_psd_page = create_snapshots_psd_view(
            db_adapter=self.db_adapter,
            path_resolver=self.path_resolver
        )

        # Create Snapshots 5 Hz Band page using factory
        self.snapshots_5hz_band_page = create_snapshots_5hz_band_view(
            db_adapter=self.db_adapter,
            path_resolver=self.path_resolver
        )

        # Create Timeline LFP Threshold page using factory
        self.timeline_lfp_threshold_page = create_timeline_lfp_threshold_view(
            db_adapter=self.db_adapter,
            path_resolver=self.path_resolver,
            app_viewmodel=self.app_viewmodel,
        )

        # Create Timeline Peri-Event page using factory
        self.timeline_peri_event_page = create_timeline_peri_event_view(
            db_adapter=self.db_adapter,
            path_resolver=self.path_resolver,
            app_viewmodel=self.app_viewmodel,
        )

        # Single source of truth for the analysis pages that follow the
        # patient/data lifecycle (load on select/upload, clear on deselect).
        # Lifecycle wiring (_connect_signals) and upload refresh
        # (_on_data_uploaded) both iterate THIS list, so a new analysis page
        # is wired everywhere by adding it here once. Each entry satisfies the
        # AnalysisPage protocol (load_patient / clear_view).
        self._analysis_pages: list[AnalysisPage] = [
            self.snapshots_psd_page,
            self.snapshots_5hz_band_page,
            self.timeline_lfp_threshold_page,
            self.timeline_peri_event_page,
        ]

        # Add pages to main layout. Each scrolls vertically below its minimum; the
        # data page reflows by width, so its height follows its width.
        self.main_layout.add_page("data_management", self.data_management_page,
                                  height_for_width=True)
        self.main_layout.add_page("timeline_lfp_threshold", self.timeline_lfp_threshold_page)
        self.main_layout.add_page("timeline_peri_event", self.timeline_peri_event_page)
        self.main_layout.add_page("snapshots_canonical_bands", self.snapshots_psd_page)
        self.main_layout.add_page("snapshots_5hz_band", self.snapshots_5hz_band_page)

        # Set as central widget
        self.setCentralWidget(self.main_layout)

        # Switch to data management page by default
        self.main_layout.switch_page("data_management")

        # Initialize toolbar router now that the top bar exists
        self._toolbar_export_router = ToolbarExportStateRouter(
            self.top_bar.set_timeline_buttons_enabled
        )

        logging.info("UI initialized successfully")

    def _connect_signals(self):
        """Wire up signals between components."""
        # ========================================================================
        # AppViewModel → TopBar (update patient list + reflect current selection)
        # ========================================================================
        self.app_viewmodel.patients_loaded.connect(self.top_bar.update_patient_list)
        # Mirror the VM's current patient in the dropdown so an auto-selected
        # patient (e.g. just after Create) shows immediately and the action
        # buttons enable — without forcing the user to re-pick from the dropdown.
        self.app_viewmodel.patient_selected.connect(
            lambda patient: self.top_bar.set_selected_patient(patient.patient_id)
        )
        self.app_viewmodel.patient_cleared.connect(self.top_bar.clear_selection)

        # ========================================================================
        # TopBar → AppViewModel (patient selection and actions)
        # ========================================================================
        self.top_bar.patient_selected.connect(self.app_viewmodel.select_patient)
        self.top_bar.create_patient_clicked.connect(self._on_create_patient)
        self.top_bar.upload_clicked.connect(self._on_upload)
        self.top_bar.delete_patient_clicked.connect(self._on_delete_patient)

        # Timeline/Snapshots shared buttons (routed based on active page)
        self.top_bar.save_plot_clicked.connect(self._on_save_plot_clicked)
        self.top_bar.copy_table_clicked.connect(self._on_copy_table_clicked)
        self.main_layout.page_changed.connect(self._on_page_changed)

        # Snapshots PSD page export state changes
        self.snapshots_psd_page.export_state_changed.connect(
            self._on_snapshots_canonical_bands_export_state_changed
        )

        # Snapshots 5 Hz Band page export state changes
        self.snapshots_5hz_band_page.export_state_changed.connect(
            self._on_snapshots_5hz_band_export_state_changed
        )

        # Timeline LFP Threshold placeholder export state changes
        self.timeline_lfp_threshold_page.export_state_changed.connect(
            self._on_timeline_lfp_threshold_export_state_changed
        )

        # Timeline Peri-Event page export state changes
        self.timeline_peri_event_page.export_state_changed.connect(
            self._on_timeline_peri_event_export_state_changed
        )

        # ========================================================================
        # AppViewModel → DataManagementViewModel (patient selection)
        # ========================================================================
        self.app_viewmodel.patient_selected.connect(
            lambda patient: self.data_management_viewmodel.select_patient(patient.patient_id)
        )
        self.app_viewmodel.patient_cleared.connect(
            self.data_management_viewmodel.clear_patient_selection
        )

        # ========================================================================
        # AppViewModel → All Analysis Pages (patient selection lifecycle)
        # ========================================================================
        # One connection each, fanned out over self._analysis_pages so every
        # page is loaded/cleared identically. This keeps select, clear, and
        # upload-refresh in lockstep (the upload path drifting out of sync with
        # these was a real bug) and means a new page is wired by adding it to
        # _analysis_pages once.
        self.app_viewmodel.patient_selected.connect(self._load_patient_into_pages)
        self.app_viewmodel.patient_cleared.connect(self._clear_analysis_pages)

        # ========================================================================
        # DataManagementViewModel → All Pages (auto-refresh on upload)
        # ========================================================================
        self.data_management_viewmodel.data_uploaded.connect(self._on_data_uploaded)

        # Timeline, Snapshots PSD, and Snapshots 5 Hz Band viewmodel error signals are
        # handled by their own view-level _on_error slots (which also reset
        # progress indicators and export state). Do not connect them here or
        # users will see two stacked error dialogs for every failure.

        # ========================================================================
        # AppViewModel → Messages
        # ========================================================================
        self.app_viewmodel.error_occurred.connect(self._show_error)
        self.app_viewmodel.success_message.connect(self._show_success)

        # Apply initial state for the default page
        self._on_page_changed(self.main_layout.current_page or "")

        logging.info("Signals connected successfully")

    def _connect_shell_signals(self):
        """
        Wire the shell (sidebar, menus, banner, window title) to its ViewModels.

        Each state is read first, then followed (plan §4.7, R2); ViewModel
        signals reach only bound methods of View objects, as the ViewModels can
        outlive the window (R7). Kept out of _connect_signals, which tests run
        on bare windows. The display is followed from the first show (L9).
        """
        context = self.main_layout.responsive_context

        # Sidebar mode: ShellViewModel resolves it from the window's width
        # class, the View ▸ Sidebar preference and the footer toggle
        self.sidebar.set_mode(self.shell_viewmodel.sidebar_mode)
        self.shell_viewmodel.sidebar_mode_changed.connect(self.sidebar.set_mode)
        self.shell_viewmodel.set_width_class(context.width_class)
        context.window_class_changed.connect(self.shell_viewmodel.set_width_class)
        self.sidebar.toggle_requested.connect(self.shell_viewmodel.toggle_sidebar)

        # Interface-size and sidebar commands: the "Aa" menu, the macOS menu
        # bar, the restart banner
        self.shell_actions = ShellActions(self, self.ui_scale_viewmodel, self.shell_viewmodel,
                                          platform_name=QGuiApplication.platformName())
        self.sidebar.set_interface_action(self.shell_actions.interface_action)
        self.main_layout.add_banner(self.shell_actions.banner)

        # The title names the page, never the patient: it shows in task
        # switchers and screen-sharing pickers
        self._show_page_title(self.main_layout.current_page)
        self.main_layout.page_changed.connect(self._show_page_title)

        # Saved again when the app quits without closing the window first
        QApplication.instance().aboutToQuit.connect(self._remember_window_geometry)

    def show_at_launch(self):
        """
        Open the window on the launch screen (L8–L9).

        Where it was left, if Qt can restore that there; else maximised or
        centred as on first launch. The layout classes for that size are set
        before the first frame (showEvent, resizeEvent). The screen is looked
        up by name now: the one picked before the splash may be unplugged.
        """
        connected = [screen.name() for screen in QGuiApplication.screens()]
        screen = launch_screen(self._presentation.launch_screen_name)
        if apply_initial_geometry(self, screen, self.shell_viewmodel.saved_window_geometry(connected)):
            logging.info(f"Window geometry restored on {screen.name()!r}")
        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self._screen_watcher is None and self.ui_scale_viewmodel is not None:
            self._watch_display()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Shown but not painted yet, the window is still being placed (e.g.
        # maximised): classify this size now rather than on the next event-loop
        # pass, so the first frame already has its sidebar mode and densities.
        handle = self.windowHandle()
        if (self.ui_scale_viewmodel is not None and self.isVisible() and handle is not None
                and not handle.isExposed()):
            self.main_layout.responsive_context.reclassify_now()

    def _watch_display(self):
        """From the first show, when the native window exists, follow its
        display: read it, then connect."""
        self._screen_watcher = ScreenWatcher(self.windowHandle(), self)
        self._on_display_changed(self._screen_watcher.metrics)
        self._screen_watcher.display_changed.connect(self._on_display_changed)

    def _on_display_changed(self, metrics: "ScreenMetrics"):
        """
        Report the window's display and lay the window out for it.

        Args:
            metrics: The display, at the first show and after every change.
                The window floor follows display changes by itself
                (keep_window_floor).
        """
        self.ui_scale_viewmodel.set_current_display(metrics)
        context = self.main_layout.responsive_context
        context.set_scale(self.ui_scale_viewmodel.state.active_percent / 100)
        context.reclassify_now()

    def _show_page_title(self, page_name: str):
        """Name the page in the window title, e.g. "BrainSenser — Timeline: Peri-Event"."""
        title = self.sidebar.page_title(page_name or "")
        self.setWindowTitle(f"BrainSenser — {title}" if title else "BrainSenser")

    def _remember_window_geometry(self):
        """Hand the window's geometry to ShellViewModel to save (on close and on
        quit). Never raises: a failure must not stop the shutdown."""
        if self.shell_viewmodel is None:
            return
        try:
            self.shell_viewmodel.remember_window_geometry(bytes(self.saveGeometry()),
                                                          screen_of(self).name())
        except Exception:
            logging.error("Could not save the window geometry", exc_info=True)

    def _on_save_plot_clicked(self):
        """Route save plot requests to the active timeline or snapshots view."""
        current_page = self.main_layout.current_page
        if current_page == "timeline_lfp_threshold":
            self.timeline_lfp_threshold_page.export_plot()
        elif current_page == "timeline_peri_event":
            self.timeline_peri_event_page.export_plot()
        elif current_page == "snapshots_canonical_bands":
            self.snapshots_psd_page.export_plot()
        elif current_page == "snapshots_5hz_band":
            self.snapshots_5hz_band_page.export_plot()

    def _on_copy_table_clicked(self):
        """Route copy-table requests to the active timeline or snapshots view."""
        current_page = self.main_layout.current_page
        if current_page == "timeline_lfp_threshold":
            self.timeline_lfp_threshold_page.copy_table_to_clipboard()
        elif current_page == "timeline_peri_event":
            self.timeline_peri_event_page.copy_table_to_clipboard()
        elif current_page == "snapshots_canonical_bands":
            self.snapshots_psd_page.copy_table_to_clipboard()
        elif current_page == "snapshots_5hz_band":
            self.snapshots_5hz_band_page.copy_table_to_clipboard()

    def _on_timeline_lfp_threshold_export_state_changed(self, enabled: bool):
        """Store and apply timeline ML export availability."""
        if self._toolbar_export_router is not None:
            self._toolbar_export_router.update_page_state("timeline_lfp_threshold", enabled)

    def _on_timeline_peri_event_export_state_changed(self, enabled: bool):
        """Store and apply timeline peri-event export availability."""
        if self._toolbar_export_router is not None:
            self._toolbar_export_router.update_page_state("timeline_peri_event", enabled)

    def _on_snapshots_canonical_bands_export_state_changed(self, enabled: bool):
        """Store and apply snapshots canonical bands export availability."""
        if self._toolbar_export_router is not None:
            self._toolbar_export_router.update_page_state("snapshots_canonical_bands", enabled)

    def _on_snapshots_5hz_band_export_state_changed(self, enabled: bool):
        """Store and apply snapshots 5 Hz Band export availability."""
        if self._toolbar_export_router is not None:
            self._toolbar_export_router.update_page_state("snapshots_5hz_band", enabled)

    def _on_page_changed(self, page_name: str):
        """Sync toolbar state whenever the visible page changes."""
        if self._toolbar_export_router is not None:
            self._toolbar_export_router.on_page_changed(page_name)

    def _load_initial_data(self):
        """Load initial data on startup."""
        # Load patients
        self.app_viewmodel.load_patients()

    def _on_create_patient(self):
        """Handle Create Patient button click."""
        patient_name, ok = QInputDialog.getText(
            self,
            "Create Patient",
            "Enter patient name:"
        )

        if ok and patient_name:
            notes, ok2 = QInputDialog.getText(
                self,
                "Create Patient",
                "Enter notes (optional):"
            )

            # Create metadata dict with notes if provided
            metadata = {"notes": notes} if (ok2 and notes) else None

            self.app_viewmodel.create_patient(patient_name, metadata)

    def _on_delete_patient(self):
        """Handle Delete Patient… button click: confirm, then delete the patient."""
        if not self.app_viewmodel.current_patient:
            return

        current_patient = self.app_viewmodel.current_patient

        # Name what goes: the button sits above the upload table, so "delete"
        # alone could read as "delete the selected upload" (D14). Cancel is the
        # default and the Escape button.
        confirm = QMessageBox(
            QMessageBox.Icon.Warning,
            "Delete Patient",
            f"Delete “{current_patient.patient_name}”?",
            QMessageBox.StandardButton.Cancel,
            self,
        )
        confirm.setInformativeText(
            "This permanently removes the patient and everything imported for them: "
            "all uploads, all Timeline and Snapshot data, uploaded files and processing "
            "metadata. This cannot be undone."
        )
        delete_button = confirm.addButton("Delete Patient", QMessageBox.ButtonRole.DestructiveRole)
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        confirm.setEscapeButton(QMessageBox.StandardButton.Cancel)
        confirm.exec()
        confirmed = confirm.clickedButton() is delete_button
        confirm.deleteLater()

        if confirmed:
            self.app_viewmodel.delete_patient(current_patient.patient_id)

    def _on_upload(self):
        """Handle Upload button click (single JSON file or a whole directory)."""
        if not self.app_viewmodel.current_patient:
            return

        # Validate patient still exists before opening the picker
        # Edge case: patient could have been deleted while still showing as "selected"
        patient_id = self.app_viewmodel.current_patient.patient_id
        patient = self.patient_service.get_patient(patient_id)

        if not patient:
            self._show_error(
                f"Patient '{patient_id}' no longer exists.\n\n"
                "The patient may have been deleted. Please select a different patient."
            )
            self.app_viewmodel.clear_patient_selection()
            return

        # Open a single picker that accepts either a JSON file or a directory.
        # The View only hands the chosen Path to the ViewModel; the file-vs-directory
        # routing decision lives in DataManagementViewModel.upload_path().
        path = FileOrDirectoryDialog.get_file_or_directory(
            self,
            "Select a JSON file or a directory of JSON files"
        )

        if path is None:
            return  # User cancelled

        self.data_management_viewmodel.upload_path(path)

    def _load_patient_into_pages(self, patient):
        """
        Load the selected patient into every analysis page.

        Slot for AppViewModel.patient_selected (which delivers a Patient
        OBJECT). Fans the patient id out over self._analysis_pages so all
        pages load identically from one wiring point.

        Args:
            patient: The selected Patient (must expose ``patient_id``).
        """
        for page in self._analysis_pages:
            page.load_patient(patient.patient_id)

    def _clear_analysis_pages(self):
        """
        Clear every analysis page.

        Slot for AppViewModel.patient_cleared (no args). Resets each page in
        self._analysis_pages so all pages clear identically from one wiring
        point.
        """
        for page in self._analysis_pages:
            page.clear_view()

    def _on_data_uploaded(self, patient_id: str):
        """
        Handle data upload event - refresh all analysis pages for the patient.

        This ensures that when data is uploaded on the Data Management page,
        every analysis page (Timeline, Snapshots) automatically refreshes to
        show the new data with duplicates removed. Iterating
        self._analysis_pages keeps this in lockstep with the patient-selection
        wiring, so no page can be silently omitted from the refresh.

        Args:
            patient_id: Patient identifier for which data was uploaded
        """
        # Only refresh if the uploaded data is for the currently selected patient
        if not self.app_viewmodel.current_patient:
            return

        if self.app_viewmodel.current_patient.patient_id != patient_id:
            return

        logging.info(f"Auto-refreshing all pages after data upload for patient {patient_id}")

        for page in self._analysis_pages:
            page.load_patient(patient_id)

    def _show_error(self, message: str):
        """Show error message dialog (what doesn't fit goes under "Show Details…")."""
        from src.ui.components.dialog_fit import show_message
        show_message(self, QMessageBox.Icon.Critical, "Error", message)

    def _show_success(self, message: str):
        """Show success message dialog (what doesn't fit goes under "Show Details…")."""
        from src.ui.components.dialog_fit import show_message
        show_message(self, QMessageBox.Icon.Information, "Success", message)

    def closeEvent(self, event):
        """
        Clean shutdown: save the window geometry, wait for background
        workers and close child pages.

        Calls .close() on each page so their existing closeEvent handlers
        run (signal disconnection, memory cleanup). Waits briefly for any
        QThreadPool workers to finish to avoid crashing on exit.
        """
        logging.info("Application shutting down...")

        # Window geometry first: a slow or failing step below must not lose it
        self._remember_window_geometry()

        # Wait for background workers (bounded to 3s so we never hang on exit)
        try:
            pool = QThreadPool.globalInstance()
            active = pool.activeThreadCount()
            if active > 0:
                logging.info(f"Waiting for {active} background worker(s) to finish...")
                if not pool.waitForDone(3000):
                    logging.warning(
                        "Some workers did not finish within 3s; proceeding with shutdown"
                    )
        except Exception:
            logging.error("Error waiting for threadpool during shutdown", exc_info=True)

        # Close child pages so their own closeEvent handlers run
        for page_attr in (
            "data_management_page",
            "snapshots_psd_page",
            "snapshots_5hz_band_page",
            "timeline_lfp_threshold_page",
            "timeline_peri_event_page",
        ):
            page = getattr(self, page_attr, None)
            if page is not None:
                try:
                    page.close()
                except Exception:
                    logging.error(f"Error closing {page_attr}", exc_info=True)

        logging.info("Application shutdown complete")
        event.accept()
        super().closeEvent(event)


def _install_exception_handler():
    """
    Install a global exception hook that logs unhandled errors and surfaces
    them to the user when a QApplication is running.

    Without this, unhandled exceptions in slots or background code can crash
    the process silently on some platforms, leaving the user with no feedback.
    KeyboardInterrupt and SystemExit are allowed to propagate normally so
    Ctrl+C and sys.exit() still work. The dialog opens over the active window,
    with the traceback under "Show Details…" and, once the log file is
    configured, "Open Log Folder".
    """
    from src.infrastructure.logging_setup import active_log_file
    from src.ui.components.dialog_fit import show_unexpected_error

    def _handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        try:
            logging.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_tb),
            )
        except Exception:
            pass

        try:
            app = QApplication.instance()
            if app is not None:
                show_unexpected_error(app.activeWindow(), (exc_type, exc_value, exc_tb),
                                      active_log_file())
        except Exception:
            # A crashing crash-handler is the worst possible outcome. Swallow.
            pass

    sys.excepthook = _handle


def main():
    """Main application entry point."""
    # Log to a rotating file in the data dir too: the packaged app has no
    # console, and error dialogs point the user to this log.
    from src.infrastructure.logging_setup import configure_logging
    configure_logging()

    # Install global exception handler before anything else
    _install_exception_handler()

    # The DI container, built once here: lazy, it builds and reads nothing yet.
    # It is shared with L0 (its preferences store), the splash viewmodel and the
    # main window, keeping PathResolver/SQLiteAdapter singletons consistent.
    from src.infrastructure.container import ApplicationContainer
    container = ApplicationContainer()

    # L0: the interface size saved for the last-used display. Qt reads it once,
    # when the QApplication is constructed (QT_SCALE_FACTOR).
    from src.ui.app_bootstrap import compose_startup_environment
    compose_startup_environment(container.ui_preferences(), container.startup_environment())

    # Crisp fractional high-DPI scaling on Windows/Linux (125%/150% displays):
    # pass the real scale factor through instead of rounding it. Qt6 enables
    # high-DPI by default, so the old AA_EnableHighDpiScaling attribute is a
    # deprecated no-op and is intentionally not used. Harmless on macOS
    # (integer backing scale). Must be set before the QApplication is built.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create Qt application
    app = QApplication(sys.argv)

    # App-wide look (dialog icons, metadata, window icon, global stylesheet) and
    # the presentation objects come from the seam the UI test harness also uses.
    from src.ui.app_bootstrap import build_presentation, configure_application
    from src.ui.views.splash import SplashView
    from src.ui.views.splash.splash_view import motion_reduced

    configure_application(app)

    # The shell ViewModels and the launch screen. If that screen needs another
    # interface size than L0 composed (the last display was unplugged), this
    # relaunches the app once and returns only if that failed.
    presentation = build_presentation(container)

    splash_vm = container.splash_viewmodel()
    splash_view: Optional[SplashView] = None

    # Mutable holder so the nested callback can populate it without nonlocal
    # acrobatics; also gives us a single source of truth to guard against
    # double launches if both a terminal signal and a race condition fire.
    window_holder: dict = {"window": None}

    def _launch_main_window() -> None:
        if window_holder["window"] is not None:
            return
        try:
            window = MainWindow(presentation=presentation)
            window.show_at_launch()
            window_holder["window"] = window
        finally:
            # Also when construction fails: its error dialog must not open
            # behind the always-on-top splash.
            if splash_view is not None:
                splash_view.close()
        # Queued after show(), so a load error's dialog opens over the window.
        QTimer.singleShot(0, window._load_initial_data)
        logging.info("Application started")

    # Queued: the window is never built inside the splash's input handlers.
    splash_vm.closed.connect(lambda: QTimer.singleShot(0, _launch_main_window))

    if not motion_reduced() and splash_vm.prepare():
        # The screen the window was last on, else the one the user is working on
        splash_view = SplashView(splash_vm, launch_screen(presentation.launch_screen_name))
        splash_view.show()
        splash_view.raise_()
        splash_view.activateWindow()
        splash_vm.start_playback()
    else:
        # Reduce motion is on, or the asset is missing - skip splash entirely.
        _launch_main_window()

    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    # PyInstaller-frozen apps must call this BEFORE any worker process is
    # spawned: it lets a re-executed child bootstrap as a multiprocessing
    # worker instead of re-launching the whole GUI (which otherwise spawns a
    # storm of windows). No-op in dev and in the parent process.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
