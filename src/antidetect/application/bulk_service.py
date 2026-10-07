"""Creating many profiles at once: numbered names, one proxy each, the same settings for all.

Every profile still gets a fingerprint of its own (profiles never share one), only the settings
the user chose once - system, workspace, tags, start page, protection switches - are common.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from antidetect.application.fingerprint import privacy
from antidetect.application.fingerprint.data import PLATFORMS
from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.errors import ProfileAlreadyExistsError

if TYPE_CHECKING:
    from antidetect.application.profile_service import ProfileService
    from antidetect.application.proxy_service import ProxyService

MAX_COUNT = 200
NUMBER_MARK = "{n}"


@dataclass(frozen=True)
class BulkRequest:
    #: "Shop" gives "Shop 1", "Shop 2", ...; "Shop #{n} (EU)" puts the number where you say.
    name: str
    count: int
    platform: str | None = None
    #: Proxies already in the list, then those pasted as text (one per line): the first profile gets
    #: the first proxy and so on. A proxy is never shared; profiles left without one get none.
    proxy_ids: tuple[int, ...] = ()
    proxy_text: str = ""
    proxy_protocol: str = "HTTP"
    workspace_id: int | None = None
    tags: tuple[str, ...] = ()
    geo_auto: bool = True
    start_url: str | None = None
    privacy_settings: dict | None = None


@dataclass
class BulkResult:
    profile_ids: list[int] = field(default_factory=list)
    with_proxy: int = 0
    without_proxy: int = 0
    invalid_proxies: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)       # "name: reason" for what could not be created

    @property
    def created(self) -> int:
        return len(self.profile_ids)


def numbered_names(template: str, count: int, taken: set[str]) -> list[str]:
    """``count`` free names from ``template``: numbers start at 1 and skip names already in use."""
    base = " ".join((template or "").split())
    if not base:
        raise ValueError("The name must not be empty.")
    pattern = base if NUMBER_MARK in base else f"{base} {NUMBER_MARK}"
    used = {name.casefold() for name in taken}
    names: list[str] = []
    number = 0
    while len(names) < count:
        number += 1
        candidate = pattern.replace(NUMBER_MARK, str(number))
        if candidate.casefold() not in used:
            names.append(candidate)
            used.add(candidate.casefold())
    return names


class BulkService:
    def __init__(self, profiles: "ProfileService", proxies: "ProxyService") -> None:
        self._profiles = profiles
        self._proxies = proxies

    def validate(self, request: BulkRequest) -> None:
        if not isinstance(request.count, int) or not 1 <= request.count <= MAX_COUNT:
            raise ValueError(f"The number of profiles must be between 1 and {MAX_COUNT}.")
        if not " ".join((request.name or "").split()):
            raise ValueError("The name must not be empty.")
        if request.platform is not None and request.platform not in PLATFORMS:
            raise ValueError(f"Unknown platform {request.platform!r}; expected one of {PLATFORMS}")
        privacy.validate(request.privacy_settings)

    def create(
        self, request: BulkRequest, on_progress: Callable[[int, int], None] | None = None
    ) -> BulkResult:
        """Create the profiles, one after another (database work only: no network is touched).

        A profile that cannot be created is reported in ``failed`` and the rest carry on, so one
        bad row never throws away the ones before it.
        """
        self.validate(request)
        result = BulkResult()
        proxy_ids = self._proxy_ids(request, result)
        taken = {p.name for p in self._profiles.list_profiles()}
        names = numbered_names(request.name, request.count, taken)
        for index, name in enumerate(names):
            proxy_id = proxy_ids[index] if index < len(proxy_ids) else None
            try:
                profile = self._profiles.create_profile(
                    name,
                    proxy_id=proxy_id,
                    # A proxy's country is known only once it has been checked; the caller aligns
                    # the geo afterwards, in one pass for all (see ``settle``).
                    auto_config=False,
                    platform=request.platform,
                    tags=list(request.tags),
                    geo_auto=request.geo_auto,
                    start_url=request.start_url,
                    workspace_id=request.workspace_id,
                    privacy_settings=privacy.minimal(request.privacy_settings) or None,
                )
            except ProfileAlreadyExistsError:
                result.failed.append(f"{name}: a profile with this name already exists")
            except Exception as exc:                          # keep going: report, do not abort the batch
                result.failed.append(f"{name}: {exc}")
            else:
                result.profile_ids.append(profile.id)
                if proxy_id is None:
                    result.without_proxy += 1
                else:
                    result.with_proxy += 1
            if on_progress is not None:
                on_progress(index + 1, len(names))
        return result

    def settle(
        self, profile_ids: list[int], on_progress: Callable[[int, int], None] | None = None
    ) -> int:
        """The slow half: check the proxies that were never measured (all at once), then match each
        profile's language and time zone to where it now connects from. Returns how many were aligned."""
        profiles = [self._profiles.get_profile(pid) for pid in profile_ids]
        wanted = sorted({p.proxy_id for p in profiles if p.proxy_id is not None})
        if wanted:
            fresh = [row.proxy.id for row in self._proxies.list_proxies(ids=wanted) if row.checked_at is None]
            if fresh:
                try:
                    self._proxies.check_all(ids=fresh)
                except Exception:                             # a proxy that fails to check just has no country yet
                    pass
        aligned = 0
        for index, profile in enumerate(profiles):
            if profile.geo_auto:
                try:
                    self._profiles.sync_geo(profile.id)
                    aligned += 1
                except Exception:
                    pass
            if on_progress is not None:
                on_progress(index + 1, len(profiles))
        return aligned

    def _proxy_ids(self, request: BulkRequest, result: BulkResult) -> list[int]:
        ids = list(request.proxy_ids)
        if (request.proxy_text or "").strip():
            try:
                protocol = ProxyProtocol[(request.proxy_protocol or "HTTP").upper()]
            except KeyError:
                protocol = ProxyProtocol.HTTP
            summary = self._proxies.import_text(request.proxy_text, protocol)
            result.invalid_proxies = list(summary.invalid)
            ids += list(summary.ids)
        return list(dict.fromkeys(ids))                       # a proxy listed twice is still one proxy
