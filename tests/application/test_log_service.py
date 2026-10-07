"""LogService: writing, incremental reads, reset, export and file tailing."""

from __future__ import annotations

import time
from pathlib import Path

from antidetect.application.log_service import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    LogService,
)
from antidetect.infrastructure.database.repositories.log_repository import SqliteLogRepository


def _service(db) -> LogService:
    return LogService(SqliteLogRepository(db))


def test_level_shortcuts_persist(db):
    service = _service(db)
    service.info("app", "an info")
    service.warn("proxy", "a warning")
    service.error("chromium", "an error", extra={"pid": 9})

    entries = service.list_logs()
    assert [e.level for e in entries] == [LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR]
    assert entries[0].source == "app"
    assert entries[2].extra == {"pid": 9}


def test_list_logs_is_incremental(db):
    service = _service(db)
    service.info("app", "one")
    service.info("app", "two")
    after = service.list_logs()[1].id

    service.info("app", "three")
    fresh = service.list_logs(after_id=after)
    assert [e.message for e in fresh] == ["three"]


def test_reset_wipes_history_and_marks_session(db):
    service = _service(db)
    service.info("app", "before")
    assert service.count() == 1

    service.reset()
    entries = service.list_logs()
    assert len(entries) == 1
    assert entries[0].message == "Log session started"
    assert entries[0].extra is not None
    assert entries[0].extra.get("history_cleared") == 1


def test_clear_keeps_no_session_marker(db):
    service = _service(db)
    service.info("app", "before")
    cleared = service.clear()
    assert cleared == 1
    assert service.count() == 0


def test_export_writes_all_entries(db, tmp_path: Path):
    service = _service(db)
    service.info("app", "alpha")
    service.error("proxy", "beta", extra={"proxy": "h:1"})

    target = tmp_path / "logs" / "out.txt"
    written = service.export(target)

    assert written == 2
    text = target.read_text(encoding="utf-8")
    assert "alpha" in text
    assert "beta" in text
    assert "h:1" in text


def test_tail_file_streams_appended_lines(db, tmp_path: Path):
    service = _service(db)
    source_log = tmp_path / "browser.log"
    source_log.write_text("", encoding="utf-8")

    service.tail_file("chromium", source_log)

    with open(source_log, "a", encoding="utf-8") as fh:
        fh.write("[INFO:CONSOLE(5)] user clicked\n")
        fh.write("GPU process crashed\n")
    fh = None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        messages = [e.message for e in service.list_logs() if e.source == "chromium"]
        if len(messages) >= 2:
            break
        time.sleep(0.1)

    assert any("user clicked" in m for m in messages)
    assert any("GPU process crashed" in m for m in messages)


def test_tail_file_is_idempotent(db, tmp_path: Path):
    service = _service(db)
    source_log = tmp_path / "once.log"
    source_log.write_text("", encoding="utf-8")

    service.tail_file("chromium", source_log)
    service.tail_file("chromium", source_log)

    service.close()
    assert service._tailers == {}