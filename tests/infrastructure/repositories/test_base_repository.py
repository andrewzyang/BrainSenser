"""
Unit tests for BaseRepository.

Tests the abstract BaseRepository class including:
- Abstract method enforcement
- Generic type support
- Helper methods (_fetch_one, _fetch_all, _execute_query)
- Error handling
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil
from dataclasses import dataclass

from src.infrastructure.repositories.base_repository import BaseRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver


# Test model for concrete repository (avoid "Test" prefix for pytest)
@dataclass
class SimpleModel:
    """Simple test model for testing BaseRepository."""
    id: int
    name: str
    value: int


class ConcreteTestRepository(BaseRepository[SimpleModel]):
    """Concrete repository for testing BaseRepository."""

    def _map_row_to_model(self, row: sqlite3.Row) -> SimpleModel:
        """Map database row to SimpleModel."""
        return SimpleModel(
            id=row['id'],
            name=row['name'],
            value=row['value']
        )

    def get_by_id(self, test_id: int) -> SimpleModel:
        """Get test model by ID."""
        db_path = self.path_resolver.base_dir / "test.db"
        query = "SELECT * FROM test_table WHERE id = ?"

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_one(conn, query, (test_id,))

    def get_all(self) -> list[SimpleModel]:
        """Get all test models."""
        db_path = self.path_resolver.base_dir / "test.db"
        query = "SELECT * FROM test_table ORDER BY id"

        with self.adapter.get_connection(db_path) as conn:
            return self._fetch_all(conn, query)

    def create(self, name: str, value: int) -> int:
        """Create new test model."""
        db_path = self.path_resolver.base_dir / "test.db"
        query = "INSERT INTO test_table (name, value) VALUES (?, ?)"

        with self.adapter.transaction(db_path) as conn:
            return self._execute_query(conn, query, (name, value))


@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def path_resolver(temp_dir):
    """Create PathResolver with temporary base directory."""
    return PathResolver(base_dir=temp_dir)


@pytest.fixture
def adapter():
    """Create SQLiteAdapter instance."""
    return SQLiteAdapter()


@pytest.fixture
def test_db(path_resolver, adapter):
    """Create and initialize test database."""
    db_path = path_resolver.base_dir / "test.db"

    schema = """
    CREATE TABLE IF NOT EXISTS test_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        value INTEGER NOT NULL
    );
    """

    with adapter.transaction(db_path) as conn:
        conn.executescript(schema)

    return db_path


@pytest.fixture
def repository(adapter, path_resolver):
    """Create ConcreteTestRepository instance."""
    return ConcreteTestRepository(adapter, path_resolver)


class TestBaseRepositoryAbstract:
    """Test that BaseRepository enforces abstract methods."""

    def test_base_repository_cannot_be_instantiated(self, adapter, path_resolver):
        """Test that BaseRepository cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseRepository(adapter, path_resolver)

    def test_base_repository_requires_map_method(self, adapter, path_resolver):
        """Test that subclass without _map_row_to_model cannot be instantiated."""
        class IncompleteRepository(BaseRepository[SimpleModel]):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteRepository(adapter, path_resolver)


class TestBaseRepositoryInitialization:
    """Test BaseRepository initialization."""

    def test_repository_initialization(self, adapter, path_resolver):
        """Test that concrete repository can be initialized."""
        repo = ConcreteTestRepository(adapter, path_resolver)

        assert repo.adapter is adapter
        assert repo.path_resolver is path_resolver
        assert repo.logger is not None
        assert repo.logger.name == "ConcreteTestRepository"


class TestBaseRepositoryFetchOne:
    """Test _fetch_one helper method."""

    def test_fetch_one_returns_model(self, repository, test_db, adapter, path_resolver):
        """Test that _fetch_one returns model instance."""
        # Insert test data
        with adapter.transaction(test_db) as conn:
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test1', 100)")

        # Fetch with repository
        model = repository.get_by_id(1)

        assert model is not None
        assert isinstance(model, SimpleModel)
        assert model.id == 1
        assert model.name == "Test1"
        assert model.value == 100

    def test_fetch_one_returns_none_when_not_found(self, repository, test_db):
        """Test that _fetch_one returns None when record not found."""
        model = repository.get_by_id(999)

        assert model is None

    def test_fetch_one_with_parameters(self, repository, test_db, adapter):
        """Test that _fetch_one works with query parameters."""
        # Insert multiple records
        with adapter.transaction(test_db) as conn:
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test1', 100)")
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test2', 200)")

        # Fetch specific record
        model = repository.get_by_id(2)

        assert model is not None
        assert model.id == 2
        assert model.name == "Test2"


class TestBaseRepositoryFetchAll:
    """Test _fetch_all helper method."""

    def test_fetch_all_returns_list(self, repository, test_db, adapter):
        """Test that _fetch_all returns list of models."""
        # Insert test data
        with adapter.transaction(test_db) as conn:
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test1', 100)")
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test2', 200)")
            conn.execute("INSERT INTO test_table (name, value) VALUES ('Test3', 300)")

        # Fetch all
        models = repository.get_all()

        assert isinstance(models, list)
        assert len(models) == 3
        assert all(isinstance(m, SimpleModel) for m in models)
        assert models[0].name == "Test1"
        assert models[1].name == "Test2"
        assert models[2].name == "Test3"

    def test_fetch_all_returns_empty_list(self, repository, test_db):
        """Test that _fetch_all returns empty list when no records."""
        models = repository.get_all()

        assert isinstance(models, list)
        assert len(models) == 0

    def test_fetch_all_maintains_order(self, repository, test_db, adapter):
        """Test that _fetch_all maintains query order."""
        # Insert in specific order
        with adapter.transaction(test_db) as conn:
            conn.execute("INSERT INTO test_table (name, value) VALUES ('C', 3)")
            conn.execute("INSERT INTO test_table (name, value) VALUES ('A', 1)")
            conn.execute("INSERT INTO test_table (name, value) VALUES ('B', 2)")

        # Fetch all (ordered by id)
        models = repository.get_all()

        assert len(models) == 3
        assert models[0].name == "C"  # id=1
        assert models[1].name == "A"  # id=2
        assert models[2].name == "B"  # id=3


class TestBaseRepositoryExecuteQuery:
    """Test _execute_query helper method."""

    def test_execute_query_returns_row_count(self, repository, test_db):
        """Test that _execute_query returns affected row count."""
        row_count = repository.create("Test1", 100)

        assert row_count == 1

    def test_execute_query_inserts_data(self, repository, test_db):
        """Test that _execute_query actually inserts data."""
        repository.create("Test1", 100)

        # Verify data was inserted
        model = repository.get_by_id(1)
        assert model is not None
        assert model.name == "Test1"
        assert model.value == 100

    def test_execute_query_multiple_rows(self, repository, test_db, adapter):
        """Test _execute_query with multiple inserts."""
        repository.create("Test1", 100)
        repository.create("Test2", 200)
        repository.create("Test3", 300)

        models = repository.get_all()
        assert len(models) == 3


class TestBaseRepositoryErrorHandling:
    """Test error handling in BaseRepository."""

    def test_fetch_one_handles_db_error(self, repository, path_resolver):
        """Test that _fetch_one handles database errors."""
        # Try to query non-existent database
        nonexistent_db = path_resolver.base_dir / "nonexistent.db"
        query = "SELECT * FROM test_table WHERE id = ?"

        with pytest.raises(sqlite3.OperationalError):
            with repository.adapter.get_connection(nonexistent_db) as conn:
                repository._fetch_one(conn, query, (1,))

    def test_execute_query_handles_constraint_violation(self, repository, test_db, adapter, path_resolver):
        """Test that _execute_query handles constraint violations."""
        # Insert record
        repository.create("Test1", 100)

        # Try to insert duplicate ID (if we had UNIQUE constraint)
        # For this test, we'll use an invalid SQL statement
        db_path = path_resolver.base_dir / "test.db"

        with pytest.raises(sqlite3.OperationalError):
            with adapter.transaction(db_path) as conn:
                repository._execute_query(conn, "INSERT INTO nonexistent_table VALUES (1)", ())


class TestBaseRepositoryLogging:
    """Test logging in BaseRepository."""

    def test_base_repository_logs_fetch_one(self, repository, test_db, adapter, caplog):
        """Test that _fetch_one logs operations."""
        import logging

        with caplog.at_level(logging.DEBUG):
            model = repository.get_by_id(999)  # Non-existent

        assert any("No record found" in record.message for record in caplog.records)

    def test_base_repository_logs_fetch_all(self, repository, test_db, adapter, caplog):
        """Test that _fetch_all logs operations."""
        import logging

        # Insert some data
        repository.create("Test1", 100)

        with caplog.at_level(logging.DEBUG):
            repository.get_all()

        assert any("Fetched 1 records" in record.message for record in caplog.records)

    def test_base_repository_logs_execute_query(self, repository, test_db, caplog):
        """Test that _execute_query logs operations."""
        import logging

        with caplog.at_level(logging.DEBUG):
            repository.create("Test1", 100)

        assert any("Executed query affecting 1 rows" in record.message for record in caplog.records)
