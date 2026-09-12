from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import AppConfig


def test_env_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "custom"))
    config = AppConfig.from_env()
    assert config.data_dir == tmp_path / "custom"
    assert config.database_path == tmp_path / "custom" / "antidetect.db"
    assert config.profiles_dir == tmp_path / "custom" / "profiles"


def test_defaults_to_repo_data_dir_in_checkout(monkeypatch):
    monkeypatch.delenv("ANTIDETECT_DATA_DIR", raising=False)
    import app.config.settings as settings_module

    # Repo layout: src/app/config/settings.py -> repo root is parents[3].
    repo_root = Path(settings_module.__file__).resolve().parents[3]
    assert (repo_root / "pyproject.toml").is_file()
    config = AppConfig.from_env()
    assert config.data_dir == repo_root / "data"


def test_home_fallback_when_installed_outside_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTIDETECT_DATA_DIR", raising=False)
    import app.config.settings as settings_module

    fake_pkg = tmp_path / "site-packages" / "app"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(settings_module, "__file__", str(fake_pkg / "settings.py"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Hide platformdirs so the test asserts the pure fallback; the
    # platformdirs branch is covered by test_platformdirs_default below.
    import sys

    monkeypatch.setitem(sys.modules, "platformdirs", None)
    config = AppConfig.from_env()
    assert config.data_dir == tmp_path / "home" / ".antidetect"


def test_legacy_data_dir_is_reused(monkeypatch, tmp_path):
    """An existing ~/.antidetect with content is never orphaned by upgrade."""
    monkeypatch.delenv("ANTIDETECT_DATA_DIR", raising=False)
    import app.config.settings as settings_module

    fake_pkg = tmp_path / "site-packages" / "app"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(settings_module, "__file__", str(fake_pkg / "settings.py"))
    home = tmp_path / "home"
    legacy = home / ".antidetect"
    legacy.mkdir(parents=True)
    (legacy / "antidetect.db").touch()
    monkeypatch.setenv("HOME", str(home))
    config = AppConfig.from_env()
    assert config.data_dir == legacy


def test_platformdirs_default(monkeypatch, tmp_path):
    """Fresh installs use the OS-native data dir when platformdirs exists."""
    platformdirs = pytest.importorskip("platformdirs")
    monkeypatch.delenv("ANTIDETECT_DATA_DIR", raising=False)
    import app.config.settings as settings_module

    fake_pkg = tmp_path / "site-packages" / "app"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(settings_module, "__file__", str(fake_pkg / "settings.py"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    config = AppConfig.from_env()
    assert config.data_dir == Path(platformdirs.user_data_dir("Antidetect", "Antidetect"))


def test_chromium_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.touch()
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(fake))
    config = AppConfig.from_env()
    assert config.chromium_path == fake


def test_chromium_env_ignores_missing_file(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(tmp_path / "gone"))
    config = AppConfig.from_env()
    assert config.chromium_path is None


def test_logs_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTIDETECT_LOGS_DIR", str(tmp_path / "logs"))
    config = AppConfig.from_env()
    assert config.logs_dir == tmp_path / "logs"