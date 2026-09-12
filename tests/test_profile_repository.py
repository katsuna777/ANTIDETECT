from __future__ import annotations

from datetime import datetime, timezone

from app.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_deleting_all_profiles_restarts_ids(profile_repo: SqliteProfileRepository) -> None:
    first = profile_repo.create("a", "/tmp/a", 1, _now())
    second = profile_repo.create("b", "/tmp/b", 1, _now())
    assert second.id == first.id + 1

    profile_repo.delete(second.id)
    profile_repo.delete(first.id)

    third = profile_repo.create("c", "/tmp/c", 1, _now())
    assert third.id == 1


def test_remaining_profile_keeps_its_id(profile_repo: SqliteProfileRepository) -> None:
    first = profile_repo.create("a", "/tmp/a", 1, _now())
    second = profile_repo.create("b", "/tmp/b", 1, _now())

    profile_repo.delete(first.id)

    third = profile_repo.create("c", "/tmp/c", 1, _now())
    assert third.id != first.id
    assert third.id == second.id + 1
    assert profile_repo.get(second.id) is not None