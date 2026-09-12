from __future__ import annotations

import pytest

from app.infrastructure.database.repositories.settings_repository import (
    SqliteSettingsRepository,
)


@pytest.fixture()
def repo(db) -> SqliteSettingsRepository:
    return SqliteSettingsRepository(db)


def test_get_missing_returns_none(repo):
    assert repo.get("nope") is None


def test_set_get_roundtrip(repo):
    repo.set("theme", "dark")
    setting = repo.get("theme")
    assert setting is not None
    assert setting.key == "theme"
    assert setting.value == "dark"


def test_set_upserts(repo):
    repo.set("counter", "1")
    repo.set("counter", "2")
    assert repo.get("counter").value == "2"  # type: ignore[union-attr]


def test_set_clears_value_to_none(repo):
    repo.set("flag", "true")
    repo.set("flag", None)
    setting = repo.get("flag")
    assert setting is not None
    assert setting.value is None


def test_get_int_with_set_value(repo):
    repo.set("n", "42")
    assert repo.get_int("n", default=0) == 42


def test_get_int_defaults_when_missing(repo):
    assert repo.get_int("missing", default=7) == 7


def test_get_int_defaults_on_invalid_value(repo):
    repo.set("bad", "not-a-number")
    assert repo.get_int("bad", default=3) == 3


def test_repository_is_persistent_across_instances(db):
    repo = SqliteSettingsRepository(db)
    repo.set("k", "v")
    fresh = SqliteSettingsRepository(db)
    assert fresh.get("k").value == "v"  # type: ignore[union-attr]