from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    """Resolved, environment-driven paths used by the composition root.

    All runtime artifacts (database, Chromium data, logs) live under
    ``data_dir``, which can be redirected for testing via
    ``ANTIDETECT_DATA_DIR``.
    """

    data_dir: Path
    chromium_path: Path | None = None
    logs_dir: Path | None = None
    disable_stealth: bool = False
    proxy_workers: int = 20
    proxy_check_timeout: float = 8.0
    proxy_max_failures: int = 3
    proxy_dead_policy: str = "delete"
    proxy_stale_minutes: int = 60
    proxy_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "antidetect.db"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @classmethod
    def from_env(cls) -> "AppConfig":
        override = os.environ.get("ANTIDETECT_DATA_DIR")
        if override:
            data_dir = Path(override).expanduser()
        else:
            data_dir = cls._default_data_dir()

        chromium_env = os.environ.get("ANTIDETECT_CHROMIUM_PATH")
        chromium: Path | None = None
        if chromium_env:
            candidate = Path(chromium_env).expanduser()
            chromium = candidate if candidate.is_file() else None

        logs_dir = os.environ.get("ANTIDETECT_LOGS_DIR")
        return cls(
            data_dir=data_dir,
            chromium_path=chromium,
            logs_dir=Path(logs_dir).expanduser() if logs_dir else None,
            disable_stealth=os.environ.get("ANTIDETECT_DISABLE_STEALTH", "").strip().lower()
            in ("1", "true", "yes"),
            proxy_workers=_env_int("ANTIDETECT_PROXY_WORKERS", 20),
            proxy_check_timeout=_env_float("ANTIDETECT_PROXY_TIMEOUT", 8.0),
            proxy_max_failures=_env_int("ANTIDETECT_PROXY_MAX_FAILURES", 3),
            proxy_dead_policy=os.environ.get(
                "ANTIDETECT_PROXY_DEAD_POLICY", "delete"
            ),
            proxy_stale_minutes=_env_int("ANTIDETECT_PROXY_STALE_MINUTES", 60),
            proxy_sources=_env_json_list("ANTIDETECT_PROXY_SOURCES"),
        )

    @staticmethod
    def _default_data_dir() -> Path:
        """Resolve the default data dir on any OS.

        Precedence:
          1. ``ANTIDETECT_DATA_DIR`` (handled in ``from_env``, always wins);
          2. frozen bundle (PyInstaller): OS-native user data dir via
             ``platformdirs`` — NEVER the read-only bundle dir;
          3. repository-local ``data/`` when developing from a checkout
             (keeps dev workflows and existing tests stable);
          4. legacy ``~/.antidetect`` when it already exists (migration —
             never orphan a user's existing DB after upgrade);
          5. OS-native user data dir via ``platformdirs`` when available
             (%APPDATA%/~/Library/XDG);
          6. ``~/.antidetect`` fallback (platformdirs not installed).
        """
        if getattr(sys, "frozen", False):
            try:
                from platformdirs import user_data_dir as _user_data_dir

                return Path(_user_data_dir("Antidetect", "Antidetect"))
            except Exception:
                return Path.home() / ".antidetect"
        package_root = Path(__file__).resolve().parents[3]
        if (package_root / "pyproject.toml").is_file():
            return package_root / "data"
        legacy = Path.home() / ".antidetect"
        try:
            if legacy.is_dir() and any(legacy.iterdir()):
                return legacy
        except OSError:
            pass
        try:
            from platformdirs import user_data_dir as _user_data_dir

            return Path(_user_data_dir("Antidetect", "Antidetect"))
        except Exception:
            return legacy


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_json_list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return ()
    try:
        values = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if str(value).startswith(("http://", "https://")))