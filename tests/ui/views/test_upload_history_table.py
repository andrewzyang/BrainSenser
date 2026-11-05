"""
Tests for UploadHistoryTable widget.

Tests table population, sorting, selection, and user interactions.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from src.ui.views.data_management.components.upload_history_table import UploadHistoryTable
from src.core.models import UploadedFile


def _get_type_badges(table_widget, row: int) -> list[str]:
    """Extract badge texts from the Type column for the given row."""
    widget = table_widget.cellWidget(row, UploadHistoryTable.COL_TYPE)
    if not widget:
        return []

    layout = widget.layout()
    badges: list[str] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if not item:
            continue
        child = item.widget()
        if child and hasattr(child, "text"):
            badges.append(child.text())
    return badges


@pytest.fixture
def upload_history_table(qtbot):
    """Create UploadHistoryTable for testing."""
    table = UploadHistoryTable()
    qtbot.addWidget(table)
    return table


@pytest.fixture
def sample_uploads():
    """Create sample UploadedFile objects for testing."""
    from pathlib import Path
    return [
        UploadedFile(
            file_id=1,
            patient_id="PATIENT001",
            file_name="recording_001.json",
            file_path=Path("/path/to/recording_001.json"),
            file_hash="abc123",
            file_size_bytes=1024000,  # 1 MB
            timeline_count=100,
            timeline_original_count=110,  # 10 duplicates
            snapshot_count=50,
            snapshot_original_count=55,  # 5 duplicates
            indefinite_streaming_count=0,
            indefinite_streaming_original_count=0,
            definite_streaming_count=0,
            definite_streaming_original_count=0,
            duplicates_skipped=15,
            outliers_detected=0,
            processing_time_seconds=1.5,
            extractor_version="1.0.0",
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime(2025, 1, 15, 10, 30)
        ),
        UploadedFile(
            file_id=2,
            patient_id="PATIENT001",
            file_name="recording_002.json",
            file_path=Path("/path/to/recording_002.json"),
            file_hash="def456",
            file_size_bytes=2048000,  # 2 MB
            timeline_count=200,
            timeline_original_count=220,  # 20 duplicates
            snapshot_count=100,
            snapshot_original_count=110,  # 10 duplicates
            indefinite_streaming_count=10,
            indefinite_streaming_original_count=12,
            definite_streaming_count=4,
            definite_streaming_original_count=5,
            duplicates_skipped=30,
            outliers_detected=0,
            processing_time_seconds=2.5,
            extractor_version="1.0.0",
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime(2025, 1, 20, 14, 45)
        ),
        UploadedFile(
            file_id=3,
            patient_id="PATIENT001",
            file_name="recording_003.json",
            file_path=Path("/path/to/recording_003.json"),
            file_hash="ghi789",
            file_size_bytes=512000,  # 0.5 MB
            timeline_count=50,
            timeline_original_count=50,  # 0 duplicates
            snapshot_count=25,
            snapshot_original_count=25,  # 0 duplicates
            indefinite_streaming_count=0,
            indefinite_streaming_original_count=0,
            definite_streaming_count=0,
            definite_streaming_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=0.8,
            extractor_version="1.0.0",
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime(2025, 1, 10, 8, 15)
        )
    ]


# --- Initialization Tests ---

def test_table_initialization(upload_history_table):
    """Test table is initialized with correct structure."""
    table_widget = upload_history_table.table

    assert table_widget.columnCount() == 4
    assert table_widget.rowCount() == 0

    # Check headers
    headers = [
        table_widget.horizontalHeaderItem(i).text()
        for i in range(table_widget.columnCount())
    ]
    assert headers == [
        "Upload Date",
        "File Name",
        "Size",
        "Type"
    ]


def test_table_has_sorting_enabled(upload_history_table):
    """Test sorting is enabled."""
    assert upload_history_table.table.isSortingEnabled()


def test_table_has_alternating_row_colors(upload_history_table):
    """Test alternating row colors are enabled."""
    assert upload_history_table.table.alternatingRowColors()


def test_table_selection_behavior(upload_history_table):
    """Test table selection is configured for item-level multi-select."""
    table_widget = upload_history_table.table

    assert table_widget.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectItems
    assert table_widget.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


# --- Population Tests ---

def test_populate_uploads_empty_list(upload_history_table):
    """Test populating with empty list."""
    upload_history_table.populate_uploads([])
    table_widget = upload_history_table.table

    assert upload_history_table.get_upload_count() == 0
    # Empty state row is inserted with message
    assert table_widget.rowCount() == 1
    empty_item = table_widget.item(0, UploadHistoryTable.COL_DATE)
    assert empty_item is not None
    assert empty_item.text() == "No upload history available for this patient"


def test_populate_uploads_single_upload(upload_history_table, sample_uploads):
    """Test populating with a single upload."""
    upload_history_table.populate_uploads([sample_uploads[0]])
    table_widget = upload_history_table.table

    assert upload_history_table.get_upload_count() == 1
    assert table_widget.rowCount() == 1

    # Check cell values (file sorted by date descending, so recording_001 is first)
    assert table_widget.item(0, UploadHistoryTable.COL_FILENAME).text() == "recording_001.json"
    assert table_widget.item(0, UploadHistoryTable.COL_DATE).text() == "2025-01-15 10:30"
    assert table_widget.item(0, UploadHistoryTable.COL_SIZE).text() == "0.98 MB"
    # Type column should show Timeline and Snapshots badges
    assert _get_type_badges(table_widget, 0) == ["Snapshots", "Timeline"]


def test_populate_uploads_multiple_uploads(upload_history_table, sample_uploads):
    """Test populating with multiple uploads."""
    upload_history_table.populate_uploads(sample_uploads)

    assert upload_history_table.get_upload_count() == 3
    assert upload_history_table.table.rowCount() == 3


def test_populate_uploads_sorted_by_date_descending(upload_history_table, sample_uploads):
    """Test uploads are sorted by date (most recent first) after population."""
    upload_history_table.populate_uploads(sample_uploads)
    table_widget = upload_history_table.table

    # After sorting by date descending, should be: recording_002, recording_001, recording_003
    # Row 0 should be most recent (2025-01-20)
    assert table_widget.item(0, UploadHistoryTable.COL_FILENAME).text() == "recording_002.json"
    # Row 1 should be middle (2025-01-15)
    assert table_widget.item(1, UploadHistoryTable.COL_FILENAME).text() == "recording_001.json"
    # Row 2 should be oldest (2025-01-10)
    assert table_widget.item(2, UploadHistoryTable.COL_FILENAME).text() == "recording_003.json"


def test_populate_uploads_with_zero_duplicates(upload_history_table, sample_uploads):
    """Test display when duplicates_skipped is zero."""
    upload_history_table.populate_uploads([sample_uploads[2]])  # recording_003 has 0 duplicates
    table_widget = upload_history_table.table

    assert upload_history_table.get_all_uploads()[0].duplicates_skipped == 0
    assert _get_type_badges(table_widget, 0) == ["Snapshots", "Timeline"]


def test_populate_uploads_replaces_existing_data(upload_history_table, sample_uploads):
    """Test populating table replaces existing data."""
    # First populate with all uploads
    upload_history_table.populate_uploads(sample_uploads)
    assert upload_history_table.table.rowCount() == 3

    # Repopulate with just one upload
    upload_history_table.populate_uploads([sample_uploads[0]])
    assert upload_history_table.table.rowCount() == 1


# --- Selection Tests ---

def test_get_selected_upload_no_selection(upload_history_table, sample_uploads):
    """Test get_selected_upload returns None when no selection."""
    upload_history_table.populate_uploads(sample_uploads)

    selected = upload_history_table.get_selected_upload()
    assert selected is None


def test_get_selected_upload_with_selection(upload_history_table, sample_uploads, qtbot):
    """Test get_selected_upload returns correct upload when row selected."""
    upload_history_table.populate_uploads(sample_uploads)

    # Select first row (most recent upload after sorting)
    upload_history_table.table.selectRow(0)

    selected = upload_history_table.get_selected_upload()
    assert selected is not None
    assert selected.file_name == "recording_002.json"  # Most recent


def test_upload_selected_signal_emitted(upload_history_table, sample_uploads, qtbot):
    """Test upload_selected signal is emitted when row selected."""
    upload_history_table.populate_uploads(sample_uploads)

    with qtbot.waitSignal(upload_history_table.upload_selected, timeout=1000) as blocker:
        upload_history_table.table.selectRow(0)

    # Check signal was emitted with correct upload
    emitted_upload = blocker.args[0]
    assert emitted_upload.file_name == "recording_002.json"


# --- Clear Tests ---

def test_clear_table_removes_all_rows(upload_history_table, sample_uploads):
    """Test clear_table removes all rows."""
    upload_history_table.populate_uploads(sample_uploads)
    assert upload_history_table.table.rowCount() == 3

    upload_history_table.clear_table()
    assert upload_history_table.table.rowCount() == 0
    assert upload_history_table.get_upload_count() == 0


def test_clear_table_clears_uploads_list(upload_history_table, sample_uploads):
    """Test clear_table clears internal uploads list."""
    upload_history_table.populate_uploads(sample_uploads)
    assert len(upload_history_table.get_all_uploads()) == 3

    upload_history_table.clear_table()
    assert len(upload_history_table.get_all_uploads()) == 0


# --- Sorting Tests ---

def test_sort_by_filename(upload_history_table, sample_uploads):
    """Test sorting by filename column."""
    upload_history_table.populate_uploads(sample_uploads)

    # Sort by filename ascending
    upload_history_table.table.sortItems(UploadHistoryTable.COL_FILENAME, Qt.SortOrder.AscendingOrder)

    # Check order: recording_001, recording_002, recording_003
    assert upload_history_table.table.item(0, UploadHistoryTable.COL_FILENAME).text() == "recording_001.json"
    assert upload_history_table.table.item(1, UploadHistoryTable.COL_FILENAME).text() == "recording_002.json"
    assert upload_history_table.table.item(2, UploadHistoryTable.COL_FILENAME).text() == "recording_003.json"


def test_sort_by_size(upload_history_table, sample_uploads):
    """Test sorting by size column."""
    upload_history_table.populate_uploads(sample_uploads)

    # Sort by size ascending
    upload_history_table.table.sortItems(UploadHistoryTable.COL_SIZE, Qt.SortOrder.AscendingOrder)

    # Check order: recording_003 (0.5 MB), recording_001 (1 MB), recording_002 (2 MB)
    assert upload_history_table.table.item(0, UploadHistoryTable.COL_FILENAME).text() == "recording_003.json"
    assert upload_history_table.table.item(1, UploadHistoryTable.COL_FILENAME).text() == "recording_001.json"
    assert upload_history_table.table.item(2, UploadHistoryTable.COL_FILENAME).text() == "recording_002.json"


def test_sort_by_date(upload_history_table, sample_uploads):
    """Test sorting by date column."""
    upload_history_table.populate_uploads(sample_uploads)

    # Sort by date ascending (oldest first)
    upload_history_table.table.sortItems(UploadHistoryTable.COL_DATE, Qt.SortOrder.AscendingOrder)

    assert upload_history_table.table.item(0, UploadHistoryTable.COL_FILENAME).text() == "recording_003.json"
    assert upload_history_table.table.item(1, UploadHistoryTable.COL_FILENAME).text() == "recording_001.json"
    assert upload_history_table.table.item(2, UploadHistoryTable.COL_FILENAME).text() == "recording_002.json"


# --- Data Access Tests ---

def test_get_all_uploads_returns_copy(upload_history_table, sample_uploads):
    """Test get_all_uploads returns a copy of uploads list."""
    upload_history_table.populate_uploads(sample_uploads)

    uploads_copy = upload_history_table.get_all_uploads()
    assert uploads_copy == sample_uploads
    assert uploads_copy is not upload_history_table._uploads  # Different list object


def test_get_upload_count_matches_row_count(upload_history_table, sample_uploads):
    """Test get_upload_count matches actual row count."""
    upload_history_table.populate_uploads(sample_uploads)

    assert upload_history_table.get_upload_count() == len(sample_uploads)
    assert upload_history_table.get_upload_count() == upload_history_table.table.rowCount()


# --- Edge Cases ---

def test_populate_with_zero_counts(upload_history_table):
    """Test handling uploads with zero counts."""
    from pathlib import Path
    upload = UploadedFile(
        file_id=1,
        patient_id="PATIENT001",
        file_name="test.json",
        file_path=Path("/path/to/test.json"),
        file_hash="test123",
        file_size_bytes=1000,
        timeline_count=0,
        timeline_original_count=0,
        snapshot_count=0,
        snapshot_original_count=0,
        indefinite_streaming_count=0,
        indefinite_streaming_original_count=0,
        definite_streaming_count=0,
        definite_streaming_original_count=0,
        duplicates_skipped=0,
        outliers_detected=0,
        processing_time_seconds=0.5,
        extractor_version="1.0.0",
        processing_settings=None,
        errors_encountered=0,
        error_details=None,
        processed_at=datetime.now()
    )

    upload_history_table.populate_uploads([upload])

    # Type column should have no badges when all counts are zero
    assert _get_type_badges(upload_history_table.table, 0) == []


def test_file_size_formatting(upload_history_table):
    """Test file size is formatted to 2 decimal places."""
    from pathlib import Path
    upload = UploadedFile(
        file_id=1,
        patient_id="PATIENT001",
        file_name="test.json",
        file_path=Path("/path/to/test.json"),
        file_hash="test123",
        file_size_bytes=1536000,  # 1.5 MB
        timeline_count=10,
        timeline_original_count=10,
        snapshot_count=5,
        snapshot_original_count=5,
        indefinite_streaming_count=0,
        indefinite_streaming_original_count=0,
        definite_streaming_count=0,
        definite_streaming_original_count=0,
        duplicates_skipped=0,
        outliers_detected=0,
        processing_time_seconds=0.5,
        extractor_version="1.0.0",
        processing_settings=None,
        errors_encountered=0,
        error_details=None,
        processed_at=datetime.now()
    )

    upload_history_table.populate_uploads([upload])

    # 1536000 / (1024*1024) = 1.4648... ≈ 1.46
    assert upload_history_table.table.item(0, UploadHistoryTable.COL_SIZE).text() == "1.46 MB"


def test_date_formatting(upload_history_table):
    """Test date is formatted as YYYY-MM-DD HH:MM."""
    from pathlib import Path
    upload = UploadedFile(
        file_id=1,
        patient_id="PATIENT001",
        file_name="test.json",
        file_path=Path("/path/to/test.json"),
        file_hash="test123",
        file_size_bytes=1000,
        timeline_count=10,
        timeline_original_count=10,
        snapshot_count=5,
        snapshot_original_count=5,
        indefinite_streaming_count=0,
        indefinite_streaming_original_count=0,
        definite_streaming_count=0,
        definite_streaming_original_count=0,
        duplicates_skipped=0,
        outliers_detected=0,
        processing_time_seconds=0.5,
        extractor_version="1.0.0",
        processing_settings=None,
        errors_encountered=0,
        error_details=None,
        processed_at=datetime(2025, 3, 15, 9, 5)
    )

    upload_history_table.populate_uploads([upload])

    assert upload_history_table.table.item(0, UploadHistoryTable.COL_DATE).text() == "2025-03-15 09:05"
