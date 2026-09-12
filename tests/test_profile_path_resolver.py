from __future__ import annotations

from pathlib import Path

from app.application.profile_path_resolver import ProfilePathResolver


def test_resolve_uses_zero_padded_profile_id(tmp_path: Path):
    resolver = ProfilePathResolver(tmp_path / "profiles")
    assert resolver.resolve(1) == tmp_path / "profiles" / "profile_001"
    assert resolver.resolve(2) == tmp_path / "profiles" / "profile_002"
    assert resolver.resolve(100) == tmp_path / "profiles" / "profile_100"


def test_resolve_is_pure_function(tmp_path: Path):
    resolver = ProfilePathResolver(tmp_path / "profiles")
    assert resolver.resolve(7) == resolver.resolve(7)


def test_ensure_root_creates_directory(tmp_path: Path):
    resolver = ProfilePathResolver(tmp_path / "profiles")
    resolver.ensure_root()
    assert (tmp_path / "profiles").is_dir()
    resolver.ensure_root()  # idempotent


def test_results_under_profiles_root(tmp_path: Path):
    resolver = ProfilePathResolver(tmp_path / "data" / "profiles")
    assert resolver.resolve(3).is_relative_to(tmp_path / "data" / "profiles")