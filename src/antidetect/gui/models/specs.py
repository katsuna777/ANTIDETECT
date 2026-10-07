"""What the profile dialog asks for, as a plain value object."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProfileSpec:
    name: str
    platform: str
    geo_auto: bool = True
    proxy_id: int | None = None
    proxy_text: str = ""            # a proxy typed/pasted in the dialog (wins over proxy_id)
    proxy_protocol: str = "HTTP"
    start_url: str = ""
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    workspace_id: int | None = None
    privacy: dict | None = None     # protection switches to store (None = leave as they are)
    # edit mode only
    regenerate: bool = False
    fingerprint: dict = field(default_factory=dict)   # BrowserConfiguration fields to change
