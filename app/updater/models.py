from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ReleaseAsset:
    name: str
    api_url: str
    browser_download_url: str
    size: int
    digest: str | None = None


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    notes: str
    html_url: str
    published_at: str | None
    prerelease: bool
    package_asset: ReleaseAsset
    checksum_asset: ReleaseAsset | None = None


@dataclass(slots=True)
class UpdateStatus:
    current_version: str
    enabled: bool
    repository: str
    channel: str
    state: str = "idle"
    update_available: bool = False
    latest_version: str | None = None
    release_name: str | None = None
    release_url: str | None = None
    release_notes: str | None = None
    published_at: str | None = None
    checked_at: str | None = None
    error: str | None = None
    can_install: bool = False
    installing: bool = False
    last_installed_version: str | None = None
    last_install_result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
