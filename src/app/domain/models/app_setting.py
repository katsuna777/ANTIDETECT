from typing import Optional


class AppSetting:
    """A single key/value row from the settings table."""

    __slots__ = ("key", "value")

    def __init__(self, key: str, value: Optional[str]) -> None:
        self.key = key
        self.value = value

    def __repr__(self) -> str:
        return f"AppSetting(key={self.key!r}, value={self.value!r})"