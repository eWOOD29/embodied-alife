from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx
from packaging.version import InvalidVersion, Version

from app.config import Settings
from app.updater.models import ReleaseAsset, ReleaseInfo, UpdateStatus
from app.updater.security import (
    UpdateValidationError,
    extract_update_archive,
    inspect_update_archive,
    parse_checksum,
    sha256_file,
)
from app.version import __version__

ShutdownCallback = Callable[[], None]


class UpdateError(RuntimeError):
    pass


class UpdateManager:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        project_root: Path | None = None,
        process_id: int | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.settings = settings
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.process_id = process_id or os.getpid()
        self.python_executable = python_executable or sys.executable
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.update_timeout_seconds),
            follow_redirects=True,
            headers=self._headers(),
        )
        self.status = UpdateStatus(
            current_version=__version__,
            enabled=settings.update_enabled,
            repository=settings.update_repository,
            channel=settings.update_channel,
        )
        self._release: ReleaseInfo | None = None
        self._periodic_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._load_persisted_status()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": f"embodied-alife/{__version__}",
        }
        if self.settings.update_github_token:
            headers["Authorization"] = f"Bearer {self.settings.update_github_token}"
        return headers

    @property
    def state_path(self) -> Path:
        return self.settings.runtime_dir / "update-state.json"

    @property
    def staging_root(self) -> Path:
        return self.settings.runtime_dir / "updates"

    def public_status(self) -> dict[str, Any]:
        result = self.status.to_dict()
        result["metadata"] = {
            key: value
            for key, value in self.status.metadata.items()
            if key in {"package_size", "checksum_available", "prerelease"}
        }
        result["configured"] = bool(self.settings.update_repository)
        result["asset_name"] = self.settings.update_asset_name
        result["automatic_checks"] = self.settings.update_check_on_startup
        return result

    async def start(self) -> None:
        if not self.settings.update_enabled:
            self.status.state = "disabled"
            return
        if self.settings.update_check_on_startup:
            self._periodic_task = asyncio.create_task(self._periodic_loop(), name="update-checker")

    async def stop(self) -> None:
        if self._periodic_task:
            self._periodic_task.cancel()
            try:
                await self._periodic_task
            except asyncio.CancelledError:
                pass
            self._periodic_task = None
        if self._owns_client:
            await self.client.aclose()

    async def _periodic_loop(self) -> None:
        await asyncio.sleep(max(0.0, self.settings.update_startup_delay_seconds))
        while True:
            try:
                await self.check()
            except Exception:
                pass
            await asyncio.sleep(max(3600.0, self.settings.update_check_interval_hours * 3600.0))

    async def check(self) -> dict[str, Any]:
        async with self._lock:
            if not self.settings.update_enabled:
                self.status.state = "disabled"
                self.status.error = None
                return self.public_status()
            repository = self.settings.update_repository.strip().strip("/")
            if repository.count("/") != 1:
                self._set_error("UPDATE_REPOSITORY must use owner/repository format")
                return self.public_status()
            self.status.state = "checking"
            self.status.error = None
            try:
                if self.settings.update_channel == "prerelease":
                    endpoint = f"https://api.github.com/repos/{repository}/releases?per_page=20"
                    response = await self.client.get(endpoint)
                    response.raise_for_status()
                    releases = [item for item in response.json() if not item.get("draft")]
                    if not releases:
                        raise UpdateError("No published GitHub release was found")
                    release = self._parse_release(releases[0])
                else:
                    endpoint = f"https://api.github.com/repos/{repository}/releases/latest"
                    response = await self.client.get(endpoint)
                    if response.status_code == 404:
                        raise UpdateError(
                            "No published GitHub release was found. Create a release or verify UPDATE_REPOSITORY."
                        )
                    response.raise_for_status()
                    release = self._parse_release(response.json())
                latest = Version(release.version)
                current = Version(__version__)
                available = latest > current
                self._release = release
                self.status.state = "available" if available else "current"
                self.status.update_available = available
                self.status.latest_version = release.version
                self.status.release_name = release.name
                self.status.release_url = release.html_url
                self.status.release_notes = release.notes[: self.settings.update_max_release_notes_chars]
                self.status.published_at = release.published_at
                self.status.checked_at = _now()
                self.status.can_install = available
                self.status.error = None
                self.status.metadata = {
                    "package_size": release.package_asset.size,
                    "checksum_available": release.checksum_asset is not None
                    or bool(release.package_asset.digest),
                    "prerelease": release.prerelease,
                }
                self._persist_status()
            except (httpx.HTTPError, InvalidVersion, KeyError, TypeError, ValueError, UpdateError) as exc:
                self._set_error(_friendly_error(exc))
            return self.public_status()

    def _parse_release(self, payload: dict[str, Any]) -> ReleaseInfo:
        if payload.get("draft"):
            raise UpdateError("The latest release is still a draft")
        prerelease = bool(payload.get("prerelease"))
        if prerelease and self.settings.update_channel != "prerelease":
            raise UpdateError("The latest release is a prerelease but UPDATE_CHANNEL is stable")
        tag_name = str(payload["tag_name"])
        version = tag_name.removeprefix("v")
        Version(version)
        assets = [self._parse_asset(item) for item in payload.get("assets", [])]
        package = next((item for item in assets if item.name == self.settings.update_asset_name), None)
        if package is None:
            raise UpdateError(
                f"Release {tag_name} does not contain {self.settings.update_asset_name}"
            )
        checksum_names = {
            f"{self.settings.update_asset_name}.sha256",
            f"{self.settings.update_asset_name}.sha256.txt",
        }
        checksum = next((item for item in assets if item.name in checksum_names), None)
        return ReleaseInfo(
            version=version,
            tag_name=tag_name,
            name=str(payload.get("name") or tag_name),
            notes=str(payload.get("body") or ""),
            html_url=str(payload.get("html_url") or ""),
            published_at=payload.get("published_at"),
            prerelease=prerelease,
            package_asset=package,
            checksum_asset=checksum,
        )

    @staticmethod
    def _parse_asset(payload: dict[str, Any]) -> ReleaseAsset:
        return ReleaseAsset(
            name=str(payload["name"]),
            api_url=str(payload["url"]),
            browser_download_url=str(payload.get("browser_download_url") or ""),
            size=int(payload.get("size") or 0),
            digest=str(payload["digest"]) if payload.get("digest") else None,
        )

    async def prepare_install(self, *, expected_version: str | None = None) -> dict[str, Any]:
        if not self.settings.update_enabled:
            raise UpdateError("automatic updates are disabled")
        if self._release is None or not self.status.update_available:
            await self.check()
        async with self._lock:
            release = self._release
            if release is None or not self.status.update_available:
                raise UpdateError("no newer release is available")
            if expected_version and expected_version != release.version:
                raise UpdateError("the selected release changed; check for updates again")
            self.status.state = "downloading"
            self.status.installing = True
            self.status.error = None
            version_dir = self.staging_root / release.version
            archive_path = version_dir / self.settings.update_asset_name
            extracted_path = version_dir / "staged"
            if version_dir.exists():
                shutil.rmtree(version_dir)
            version_dir.mkdir(parents=True, exist_ok=True)
            try:
                if release.package_asset.size > self.settings.update_max_download_bytes:
                    raise UpdateValidationError("release package exceeds the configured download size limit")
                await self._download_asset(release.package_asset, archive_path)
                expected_hash = await self._expected_hash(release)
                actual_hash = sha256_file(archive_path)
                if actual_hash != expected_hash:
                    raise UpdateValidationError("release package checksum verification failed")
                manifest = inspect_update_archive(
                    archive_path,
                    max_uncompressed_bytes=self.settings.update_max_extract_bytes,
                    expected_version=release.version,
                )
                extract_update_archive(archive_path, extracted_path)
                request = {
                    "schema_version": 1,
                    "version": release.version,
                    "project_root": str(self.project_root),
                    "staged_path": str(extracted_path),
                    "parent_pid": self.process_id,
                    "python_executable": self.python_executable,
                    "uv_executable": shutil.which("uv"),
                    "restart": self.settings.update_auto_restart,
                    "created_at": _now(),
                    "manifest": manifest,
                }
                request_path = version_dir / "install-request.json"
                request_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
                self.status.state = "ready"
                self.status.can_install = True
                self.status.metadata["staged_path"] = str(extracted_path)
                self.status.metadata["verified_sha256"] = actual_hash
                self._persist_status()
                return {
                    "ok": True,
                    "version": release.version,
                    "request_path": str(request_path),
                    "verified_sha256": actual_hash,
                }
            except Exception as exc:
                self.status.installing = False
                self._set_error(_friendly_error(exc))
                raise UpdateError(self.status.error or "update preparation failed") from exc

    async def install(
        self,
        *,
        expected_version: str | None = None,
        shutdown_callback: ShutdownCallback | None = None,
    ) -> dict[str, Any]:
        if shutdown_callback is None:
            raise UpdateError("the server cannot request a graceful shutdown")
        prepared = await self.prepare_install(expected_version=expected_version)
        request_path = Path(prepared["request_path"])
        command = [
            self.python_executable,
            str(self.project_root / "scripts" / "apply_update.py"),
            "--request",
            str(request_path),
        ]
        creationflags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        log_path = self.settings.runtime_dir / "update-worker.log"
        log_handle = log_path.open("a", encoding="utf-8")
        try:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=self.project_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    creationflags=creationflags,
                    start_new_session=start_new_session,
                )
            except OSError as exc:
                self.status.installing = False
                self._set_error(f"could not start the update worker: {exc}")
                raise UpdateError(self.status.error or "could not start the update worker") from exc
        finally:
            log_handle.close()
        self.status.state = "installing"
        self.status.installing = True
        self.status.can_install = False
        self.status.metadata["worker_pid"] = process.pid
        self._persist_status()
        asyncio.get_running_loop().call_later(0.75, shutdown_callback)
        return {
            "ok": True,
            "version": prepared["version"],
            "message": "Update verified and staged. The app will restart after installation.",
        }

    async def _download_asset(self, asset: ReleaseAsset, destination: Path) -> None:
        headers = {"Accept": "application/octet-stream"}
        async with self.client.stream("GET", asset.api_url, headers=headers) as response:
            response.raise_for_status()
            total = 0
            with destination.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.settings.update_max_download_bytes:
                        raise UpdateValidationError("release download exceeds the configured size limit")
                    output.write(chunk)
        if total == 0:
            raise UpdateValidationError("release package download was empty")

    async def _expected_hash(self, release: ReleaseInfo) -> str:
        digest = release.package_asset.digest or ""
        if digest.startswith("sha256:"):
            value = digest.removeprefix("sha256:").lower()
            if len(value) == 64:
                return value
        if release.checksum_asset is None:
            raise UpdateValidationError(
                "release has no GitHub SHA-256 digest and no checksum asset"
            )
        response = await self.client.get(
            release.checksum_asset.api_url,
            headers={"Accept": "application/octet-stream"},
        )
        response.raise_for_status()
        return parse_checksum(response.text, self.settings.update_asset_name)

    def _set_error(self, message: str) -> None:
        self.status.state = "error"
        self.status.error = message
        self.status.checked_at = _now()
        self.status.update_available = False
        self.status.can_install = False
        self.status.installing = False
        self._persist_status()

    def _load_persisted_status(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.status.last_installed_version = data.get("last_installed_version")
        self.status.last_install_result = data.get("last_install_result")

    def _persist_status(self) -> None:
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.status.to_dict(), indent=2), encoding="utf-8")
        temporary.replace(self.state_path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "GitHub update check timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"GitHub returned HTTP {exc.response.status_code}"
    return str(exc) or exc.__class__.__name__
