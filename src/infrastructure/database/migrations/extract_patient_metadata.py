"""
Migration: Extract patient metadata from existing uploads

This migration extracts metadata from the most recent uploaded JSON file
for each patient and stores it in the patient_registry.metadata column.

This is a one-time migration to populate metadata for existing patients
who have uploads but no metadata yet.

Created: 2025-10-09
"""

import json
import sqlite3
from pathlib import Path
from typing import Optional


def extract_metadata_from_json(json_data: dict) -> dict:
    """
    Extract metadata fields from BrainSense JSON structure.

    Args:
        json_data: Parsed JSON data from BrainSense file

    Returns:
        dict: Extracted metadata fields
    """
    metadata = {}

    # Extract Patient Information (use "Final" state)
    try:
        patient_info = json_data.get("PatientInformation", {}).get("Final", {})
        if patient_info:
            if first_name := patient_info.get("PatientFirstName"):
                metadata["first_name"] = first_name
            if last_name := patient_info.get("PatientLastName"):
                metadata["last_name"] = last_name
            if dob := patient_info.get("PatientDateOfBirth"):
                metadata["date_of_birth"] = dob
            if gender := patient_info.get("PatientGender"):
                metadata["gender"] = clean_gender(gender)
            if device_patient_id := patient_info.get("PatientId"):
                metadata["device_patient_id"] = device_patient_id
            if diagnosis := patient_info.get("Diagnosis"):
                metadata["diagnosis"] = clean_diagnosis(diagnosis)
    except Exception as e:
        print(f"    Warning: Failed to extract patient info: {e}")

    # Extract Device Information (use "Final" state)
    try:
        device_info = json_data.get("DeviceInformation", {}).get("Final", {})
        if device_info:
            if neurostimulator := device_info.get("Neurostimulator"):
                metadata["neurostimulator"] = neurostimulator
            if model := device_info.get("NeurostimulatorModel"):
                metadata["neurostimulator_model"] = model
            if serial := device_info.get("NeurostimulatorSerialNumber"):
                metadata["serial_number"] = serial
            if implant_date := device_info.get("ImplantDate"):
                metadata["implant_date"] = implant_date
            if location := device_info.get("NeurostimulatorLocation"):
                metadata["device_location"] = clean_location(location)
    except Exception as e:
        print(f"    Warning: Failed to extract device info: {e}")

    # Extract Battery Information
    try:
        battery_info = json_data.get("BatteryInformation", {})
        if battery_info:
            if battery_pct := battery_info.get("BatteryPercentage"):
                metadata["battery_percentage"] = battery_pct
            if battery_life := battery_info.get("EstimatedBatteryLifeMonths"):
                metadata["battery_life_months"] = battery_life
    except Exception as e:
        print(f"    Warning: Failed to extract battery info: {e}")

    # Extract Session Information
    try:
        if session_date := json_data.get("SessionDate"):
            metadata["last_session_date"] = session_date
        if programmer_version := json_data.get("ProgrammerVersion"):
            metadata["programmer_version"] = programmer_version
    except Exception as e:
        print(f"    Warning: Failed to extract session info: {e}")

    return metadata


def clean_gender(gender: str) -> str:
    """Clean gender field by removing enum prefix."""
    if not gender:
        return ""
    if gender.startswith("PatientGenderDef."):
        gender = gender.replace("PatientGenderDef.", "")
    return gender.replace("_", " ").title()


def clean_diagnosis(diagnosis: str) -> str:
    """Clean diagnosis field by removing enum prefix."""
    if not diagnosis:
        return ""
    if diagnosis.startswith("DiagnosisTypeDef."):
        diagnosis = diagnosis.replace("DiagnosisTypeDef.", "")
    return diagnosis.replace("_", " ").title()


def clean_location(location: str) -> str:
    """Clean device location field by removing enum prefix."""
    if not location:
        return ""
    if location.startswith("InsLocation."):
        location = location.replace("InsLocation.", "")
    return location.replace("_", " ").title()


def get_most_recent_upload(patient_dir: Path) -> Optional[Path]:
    """
    Find the most recent JSON upload for a patient.

    Args:
        patient_dir: Patient directory path

    Returns:
        Path to most recent JSON file, or None if not found
    """
    raw_uploads_dir = patient_dir / "raw_uploads"

    if not raw_uploads_dir.exists():
        return None

    # Find all JSON files
    json_files = list(raw_uploads_dir.glob("*.json"))

    if not json_files:
        return None

    # Sort by modification time (most recent last)
    json_files.sort(key=lambda p: p.stat().st_mtime)

    return json_files[-1]


def migrate_patient_metadata(patient_id: str, patient_dir: Path, app_db_path: Path) -> bool:
    """
    Extract and store metadata for a single patient.

    Args:
        patient_id: Patient identifier
        patient_dir: Patient directory path
        app_db_path: Path to app_metadata.db

    Returns:
        bool: True if metadata was extracted and stored, False otherwise
    """
    # Check if patient already has metadata
    conn = sqlite3.connect(app_db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT metadata_json FROM patient_registry WHERE patient_id = ?
    """, (patient_id,))

    result = cursor.fetchone()

    if not result:
        print(f"  ⚠ Patient not found in registry: {patient_id}")
        conn.close()
        return False

    existing_metadata_json = result[0]

    # If patient already has metadata, skip (unless it's empty/null)
    if existing_metadata_json:
        try:
            existing_metadata = json.loads(existing_metadata_json)
            if existing_metadata and len(existing_metadata) > 0:
                print(f"  ⊘ Patient already has metadata: {patient_id}")
                conn.close()
                return False
        except json.JSONDecodeError:
            pass  # Invalid JSON, proceed to extract

    # Find most recent upload
    most_recent_json = get_most_recent_upload(patient_dir)

    if not most_recent_json:
        print(f"  ⊘ No uploads found: {patient_id}")
        conn.close()
        return False

    # Read and parse JSON
    try:
        with open(most_recent_json, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except Exception as e:
        print(f"  ✗ Failed to read JSON: {patient_id} ({e})")
        conn.close()
        return False

    # Extract metadata
    metadata = extract_metadata_from_json(json_data)

    if not metadata:
        print(f"  ⊘ No metadata extracted: {patient_id}")
        conn.close()
        return False

    # Store metadata in patient_registry
    try:
        cursor.execute("""
            UPDATE patient_registry
            SET metadata_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
        """, (json.dumps(metadata), patient_id))

        conn.commit()

        # Print summary
        patient_name = f"{metadata.get('first_name', '')} {metadata.get('last_name', '')}".strip()
        device_model = f"{metadata.get('neurostimulator', '')} {metadata.get('neurostimulator_model', '')}".strip()

        print(f"  ✓ {patient_id}: {patient_name or 'No name'} | {device_model or 'No device'}")

        return True

    except Exception as e:
        conn.rollback()
        print(f"  ✗ Failed to update metadata: {patient_id} ({e})")
        return False

    finally:
        conn.close()


def run_migration():
    """Run metadata extraction migration on all patients."""
    from src.core.path_resolver import PathResolver

    resolver = PathResolver()
    base_dir = resolver.base_dir
    patients_dir = base_dir / "patients"
    app_db_path = base_dir / "app_metadata.db"

    if not patients_dir.exists():
        print("✗ No patients directory found")
        return

    if not app_db_path.exists():
        print("✗ No app_metadata.db found")
        return

    print("=" * 70)
    print("Extracting Patient Metadata from Existing Uploads")
    print("=" * 70)
    print()

    # Get all patient directories
    patient_dirs = [d for d in patients_dir.iterdir() if d.is_dir()]

    if not patient_dirs:
        print("No patient directories found")
        return

    print(f"Found {len(patient_dirs)} patient(s)\n")

    # Process each patient
    success_count = 0
    skip_count = 0
    error_count = 0

    for patient_dir in patient_dirs:
        patient_id = patient_dir.name
        print(f"Processing {patient_id}...")

        result = migrate_patient_metadata(patient_id, patient_dir, app_db_path)

        if result:
            success_count += 1
        else:
            skip_count += 1

    # Print summary
    print()
    print("=" * 70)
    print("Migration Complete")
    print("=" * 70)
    print(f"✓ Successfully extracted metadata: {success_count}")
    print(f"⊘ Skipped (already has metadata or no uploads): {skip_count}")
    print(f"✗ Errors: {error_count}")
    print()


if __name__ == "__main__":
    run_migration()
