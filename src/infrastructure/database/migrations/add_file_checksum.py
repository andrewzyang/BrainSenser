"""
Migration: Add file_checksum column to streaming_recordings table

Created: 2025-10-08
"""

import sqlite3
from pathlib import Path


def migrate_up(db_path: Path) -> None:
    """Add file_checksum column to streaming_recordings table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(streaming_recordings)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'file_checksum' not in columns:
            # Add column (NULL allowed for existing records)
            cursor.execute("""
                ALTER TABLE streaming_recordings
                ADD COLUMN file_checksum TEXT
            """)

            # Create index for fast checksum lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_streaming_recordings_checksum
                ON streaming_recordings(file_checksum)
            """)

            conn.commit()
            print(f"✓ Added file_checksum column to {db_path}")
        else:
            print(f"  Column file_checksum already exists in {db_path}")

    except Exception as e:
        conn.rollback()
        raise Exception(f"Migration failed for {db_path}: {e}")
    finally:
        conn.close()


def migrate_down(db_path: Path) -> None:
    """Remove file_checksum column (SQLite doesn't support DROP COLUMN easily)."""
    # Note: SQLite doesn't support DROP COLUMN directly
    # Would require table recreation, which is risky
    # Better to leave column empty if rollback needed
    print("Rollback not implemented - column will remain but can be ignored")


def backfill_checksums(db_path: Path, patient_id: str) -> None:
    """Compute and store checksums for existing recordings."""
    import sqlite3
    from pathlib import Path
    from src.core.services.streaming_file_loader import StreamingFileLoader
    from src.core.path_resolver import PathResolver

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all recordings without checksums
    cursor.execute("""
        SELECT id, file_path
        FROM streaming_recordings
        WHERE file_checksum IS NULL
    """)

    recordings = cursor.fetchall()
    loader = StreamingFileLoader()
    resolver = PathResolver()
    patient_dir = resolver.get_patient_directory(patient_id)

    updated_count = 0
    error_count = 0

    for rec_id, file_path in recordings:
        try:
            # Resolve file path
            if Path(file_path).is_absolute():
                full_path = Path(file_path)
            else:
                full_path = patient_dir / file_path

            if not full_path.exists():
                print(f"  ⚠ File not found: {rec_id} -> {full_path}")
                error_count += 1
                continue

            # Compute checksum
            checksum = loader.compute_file_checksum(full_path)

            # Update database
            cursor.execute("""
                UPDATE streaming_recordings
                SET file_checksum = ?
                WHERE id = ?
            """, (checksum, rec_id))

            updated_count += 1

        except Exception as e:
            print(f"  ⚠ Error computing checksum for {rec_id}: {e}")
            error_count += 1

    conn.commit()
    conn.close()

    print(f"✓ Backfilled checksums: {updated_count} updated, {error_count} errors")


if __name__ == "__main__":
    """Run migration on all patient databases."""
    from src.core.path_resolver import PathResolver

    resolver = PathResolver()
    base_dir = resolver.base_dir
    patients_dir = base_dir / "patients"

    if not patients_dir.exists():
        print("No patients directory found")
        exit(1)

    # Migrate all patient databases
    for patient_dir in patients_dir.iterdir():
        if not patient_dir.is_dir():
            continue

        db_path = patient_dir / "brainsense_data.db"
        if not db_path.exists():
            continue

        print(f"\nMigrating {patient_dir.name}...")
        migrate_up(db_path)

        # Backfill checksums
        print(f"Backfilling checksums for {patient_dir.name}...")
        backfill_checksums(db_path, patient_dir.name)

    print("\n✓ Migration complete")
