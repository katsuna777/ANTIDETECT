"""SQLite log repository: persistence, incremental reads and clearing."""

from __future__ import annotations

from app.domain.models.log_entry import LogEntry
from app.infrastructure.database.repositories.log_repository import SqliteLogRepository
from app.application.log_service import utcnow


def _entry(**changes) -> LogEntry:
    values = dict(id=0, ts=utcnow(), level="INFO", source="app", message="hello world")
    values.update(changes)
    return LogEntry(**values)


def test_insert_and_read_back(db):
    repo = SqliteLogRepository(db)
    entry_id = repo.insert(_entry(message="first"))

    rows = repo.all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == entry_id
    assert row.message == "first"
    assert row.level == "INFO"
    assert row.source == "app"


def test_insert_many_batches(db):
    repo = SqliteLogRepository(db)
    inserted = repo.insert_many([_entry(message=f"line {i}") for i in range(5)])
    assert inserted == 5
    assert repo.count() == 5
    assert [e.message for e in repo.all()] == [f"line {i}" for i in range(5)]


def test_list_after_returns_only_new_rows(db):
    repo = SqliteLogRepository(db)
    repo.insert_many([_entry() for _ in range(4)])
    latest = repo.latest_id()

    repo.insert(_entry(message="fresh"))
    new = repo.list_after(after_id=latest)
    assert len(new) == 1
    assert new[0].message == "fresh"


def test_latest_id_and_count_track_state(db):
    repo = SqliteLogRepository(db)
    assert repo.latest_id() == 0
    assert repo.count() == 0

    repo.insert_many([_entry() for _ in range(3)])
    assert repo.latest_id() == 3
    assert repo.count() == 3


def test_clear_removes_every_row(db):
    repo = SqliteLogRepository(db)
    repo.insert_many([_entry() for _ in range(4)])
    cleared = repo.clear()
    assert cleared == 4
    assert repo.count() == 0
    assert repo.latest_id() == 0


def test_extra_round_trips_as_json(db):
    repo = SqliteLogRepository(db)
    repo.insert(_entry(extra={"pid": 123, "profile": "/tmp/p1"}))
    (row,) = repo.all()
    assert row.extra == {"pid": 123, "profile": "/tmp/p1"}