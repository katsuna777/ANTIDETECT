from pathlib import Path


class ProfilePathResolver:
    """Deterministic mapping from profile id to its persistent Chromium directory.

    The path is purely a function of the profile id and the profiles root,
    which keeps data directories stable across DB re-inserts and restarts.
    """

    def __init__(self, profiles_root: Path) -> None:
        self.profiles_root = profiles_root

    def resolve(self, profile_id: int) -> Path:
        return self.profiles_root / f"profile_{profile_id:03d}"

    def ensure_root(self) -> None:
        self.profiles_root.mkdir(parents=True, exist_ok=True)