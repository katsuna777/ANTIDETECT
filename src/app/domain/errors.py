class AntiDetectError(Exception):
    """Base class for all application-level errors."""


class ProfileNotFoundError(AntiDetectError):
    def __init__(self, profile_id: int) -> None:
        super().__init__(f"Profile with id={profile_id} does not exist.")
        self.profile_id = profile_id


class ProfileAlreadyExistsError(AntiDetectError):
    def __init__(self, name: str) -> None:
        super().__init__(f"A profile named {name!r} already exists.")
        self.name = name


class ProfileAlreadyRunningError(AntiDetectError):
    def __init__(self, profile_id: int, pid: int | None = None) -> None:
        super().__init__(f"Profile with id={profile_id} is already running (pid={pid}).")
        self.profile_id = profile_id
        self.pid = pid


class ProfileNotRunningError(AntiDetectError):
    def __init__(self, profile_id: int) -> None:
        super().__init__(f"Profile with id={profile_id} is not running.")
        self.profile_id = profile_id


class ProfileConfigurationMissingError(AntiDetectError):
    def __init__(self, profile_id: int) -> None:
        super().__init__(
            f"Profile with id={profile_id} has no browser configuration assigned. "
            "Assign one with: app profile update <id> --configuration-id <cfg>"
        )
        self.profile_id = profile_id


class BrowserConfigurationNotFoundError(AntiDetectError):
    def __init__(self, configuration_id: int) -> None:
        super().__init__(f"Browser configuration with id={configuration_id} does not exist.")
        self.configuration_id = configuration_id


class BrowserConfigurationValidationError(AntiDetectError):
    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid browser configuration: {message}")
        self.message = message


class ChromiumNotFoundError(AntiDetectError):
    def __init__(self) -> None:
        super().__init__(
            "Could not locate a Chromium-based browser executable. "
            "Set ANTIDETECT_CHROMIUM_PATH or add one of the known install paths."
        )


class ChromiumError(AntiDetectError):
    pass


class StealthError(ChromiumError):
    """The browser launched but the fingerprint could not be injected.

    Raised fail-closed: a half-spoofed profile (UA flag without Client Hints
    / WebGL / webdriver overrides) is exactly what Google flags as
    "browser is not secure", so it must never be handed to the user silently.
    """


class ProxyNotFoundError(AntiDetectError):
    def __init__(self, proxy_id: int) -> None:
        super().__init__(f"Proxy with id={proxy_id} does not exist.")
        self.proxy_id = proxy_id


class ProxyNotUsableError(AntiDetectError):
    """An assigned proxy exists but cannot be used for browsing."""

    def __init__(self, proxy_id: int, detail: str) -> None:
        super().__init__(f"Proxy with id={proxy_id} is not usable: {detail}")
        self.proxy_id = proxy_id
        self.detail = detail


class ProxySourceError(AntiDetectError):
    def __init__(self, source_name: str, detail: str) -> None:
        super().__init__(f"Proxy source {source_name!r} failed: {detail}")
        self.source_name = source_name
        self.detail = detail


class CookieError(AntiDetectError):
    """Base class for cookie backup/restore failures."""


class CookieFileNotFoundError(CookieError):
    def __init__(self, profile_id: int, detail: str) -> None:
        super().__init__(f"Profile {profile_id} has no cookies: {detail}")
        self.profile_id = profile_id
        self.detail = detail


class CookieImportError(CookieError):
    pass