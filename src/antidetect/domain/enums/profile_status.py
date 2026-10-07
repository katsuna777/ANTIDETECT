from enum import Enum


class ProfileStatus(str, Enum):
    """Lifecycle status of a browser profile as stored in the database."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"

    @classmethod
    def from_string(cls, value: str) -> "ProfileStatus":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"Unknown profile status: {value!r}") from exc