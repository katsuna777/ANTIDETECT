from __future__ import annotations

import pytest

from app.infrastructure.database.repositories.browser_configuration_repository import (
    SqliteBrowserConfigurationRepository,
)


@pytest.fixture()
def repo(db) -> SqliteBrowserConfigurationRepository:
    return SqliteBrowserConfigurationRepository(db)


def test_default_configuration_is_seeded(repo):
    default = repo.get_default()
    assert default is not None
    assert default.id == 1
    assert default.name == "default"
    assert default.user_agent is None


def test_create_roundtrip(repo):
    config = repo.create(
        "chrome-mac",
        user_agent="Mozilla/5.0 (Macintosh)",
        language="en-US",
        timezone="America/New_York",
    )
    assert config.id is not None
    assert config.id != 1
    loaded = repo.get(config.id)
    assert loaded.name == "chrome-mac"
    assert loaded.user_agent == "Mozilla/5.0 (Macintosh)"
    assert loaded.language == "en-US"
    assert loaded.timezone == "America/New_York"
    assert loaded.created_at is not None


def test_create_with_minimal_fields(repo):
    config = repo.create(name="minimal")
    assert config.user_agent is None
    assert config.language is None
    assert config.timezone is None


def test_create_rejects_duplicate_name(repo):
    repo.create("dup")
    with pytest.raises(Exception):
        repo.create("dup")


def test_get_missing_returns_none(repo):
    assert repo.get(9999) is None


def test_find_by_name(repo):
    repo.create("named")
    assert repo.find_by_name("named").name == "named"
    assert repo.find_by_name("absent") is None


def test_list_contains_seeded_and_created(repo):
    repo.create("extra")
    names = [c.name for c in repo.list()]
    assert names == ["default", "extra"]


def test_get_default_returns_lowest_id(repo):
    default = repo.get_default()
    assert default.id == 1


def test_deleting_all_configs_restarts_ids(repo):
    repo.delete(1)
    created = repo.create("fresh")
    assert created.id == 1
    assert repo.delete(created.id) is True
    assert repo.create("fresher").id == 1