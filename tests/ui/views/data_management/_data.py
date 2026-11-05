"""Synthetic Data page content for the layout tests (never patient data)."""

from datetime import datetime, timedelta
from pathlib import Path

from src.core.models import PatientStatistics, UploadedFile

METADATA = {
    "first_name": "Synthetic", "last_name": "Patient-01", "date_of_birth": "1970-01-01T00:00:00Z",
    "gender": "Unspecified", "device_patient_id": "SYN-0001",
    "diagnosis": "Synthetic diagnosis (no real data)", "neurostimulator": "Percept PC",
    "neurostimulator_model": "B35200", "serial_number": "SYN0000000X",
    "implant_date": "2024-01-15T09:00:00Z", "device_location": "Synthetic site",
    "battery_percentage": 87, "battery_life_months": 96, "last_session_date": "2025-06-01T12:00:00Z",
}


def make_statistics(count: int) -> PatientStatistics:
    """Every card shows ``count`` original and ``count`` deduplicated records."""
    now = datetime(2026, 1, 15, 9, 30)
    return PatientStatistics(
        patient_id="SYNTH_001", snapshots_original=count, snapshots_deduplicated=count,
        timeline_original=count, timeline_deduplicated=count,
        indefinite_streaming_original=count, indefinite_streaming_deduplicated=count,
        definite_streaming_original=count, definite_streaming_deduplicated=count,
        total_files_uploaded=12, total_duplicates_skipped=0, last_upload_date=now,
        last_calculated=now)


def make_upload(index: int, size_mb: float = 1.0) -> UploadedFile:
    """A synthetic upload with a timestamped report name and all four type badges."""
    when = datetime(2026, 1, 15, 9, 30) - timedelta(days=17 * index)
    return UploadedFile(
        file_id=index + 1, patient_id="SYNTH_001",
        file_name=f"Report_Json_Session_Report_{when.strftime('%Y%m%dT%H%M%S')}.json",
        file_path=Path(f"/synthetic/upload_{index}.json"), file_hash=f"{index:064x}",
        file_size_bytes=int(size_mb * 1024 * 1024),
        timeline_count=10, timeline_original_count=10, snapshot_count=5, snapshot_original_count=5,
        indefinite_streaming_count=1, indefinite_streaming_original_count=1,
        definite_streaming_count=1, definite_streaming_original_count=1,
        duplicates_skipped=0, outliers_detected=0, processing_time_seconds=1.0,
        extractor_version="1.0.0", processing_settings=None, errors_encountered=0,
        error_details=None, processed_at=when)


def populate(page, count: int = 48210, uploads: int = 12) -> None:
    """Show a synthetic patient on ``page`` through its ViewModel slots."""
    page._on_patient_selected(None)
    page._on_metadata_updated(METADATA)
    page._on_statistics_updated(make_statistics(count))
    page._on_upload_history_updated([make_upload(i) for i in range(uploads)])
