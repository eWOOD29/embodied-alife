from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.updater.manager import UpdateError, UpdateManager
from app.updater.security import UpdateValidationError, inspect_update_archive, parse_checksum
from app.version import __version__
from scripts.apply_update import apply_update


def _update_zip(version: str = "0.3.0", *, unsafe_name: str | None = None) -> bytes:
    managed = ["app/main.py", "pyproject.toml", "scripts/apply_update.py"]
    manifest = {
        "schema_version": 1,
        "app_id": "embodied-alife",
        "version": version,
        "managed_paths": managed,
        "preserved_roots": [".env", ".venv", "data", ".git"],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest))
        archive.writestr("app/main.py", "print('new')\n")
        archive.writestr("pyproject.toml", f'[project]\nversion = "{version}"\n')
        archive.writestr("scripts/apply_update.py", "print('worker')\n")
        if unsafe_name:
            archive.writestr(unsafe_name, "unsafe")
    return output.getvalue()


def _release_payload(package: bytes, version: str = "0.3.0") -> dict:
    return {
        "tag_name": f"v{version}",
        "name": f"Release {version}",
        "body": "Useful release notes",
        "html_url": "https://github.com/test/project/releases/tag/v0.3.0",
        "published_at": "2026-07-22T12:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "embodied-alife-update.zip",
                "url": "https://api.github.com/repos/test/project/releases/assets/1",
                "browser_download_url": "https://github.com/test/project/releases/download/v0.3.0/embodied-alife-update.zip",
                "size": len(package),
                "digest": None,
            },
            {
                "name": "embodied-alife-update.zip.sha256",
                "url": "https://api.github.com/repos/test/project/releases/assets/2",
                "browser_download_url": "https://github.com/test/project/releases/download/v0.3.0/embodied-alife-update.zip.sha256",
                "size": 100,
                "digest": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_update_check_and_verified_staging(settings, tmp_path: Path) -> None:
    package = _update_zip()
    digest = hashlib.sha256(package).hexdigest()
    release = _release_payload(package)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=release)
        if request.url.path.endswith("/assets/1"):
            return httpx.Response(200, content=package)
        if request.url.path.endswith("/assets/2"):
            return httpx.Response(
                200,
                text=f"{digest}  embodied-alife-update.zip\n",
            )
        return httpx.Response(404)

    settings.update_repository = "test/project"
    settings.update_enabled = True
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    manager = UpdateManager(settings, client=client, project_root=tmp_path / "project")

    status = await manager.check()
    assert status["update_available"] is True
    assert status["latest_version"] == "0.3.0"
    assert status["release_notes"] == "Useful release notes"

    prepared = await manager.prepare_install(expected_version="0.3.0")
    assert prepared["verified_sha256"] == digest
    request = json.loads(Path(prepared["request_path"]).read_text(encoding="utf-8"))
    assert request["manifest"]["version"] == "0.3.0"
    assert Path(request["staged_path"], "app", "main.py").is_file()
    await client.aclose()


@pytest.mark.asyncio
async def test_update_check_reports_missing_release(settings) -> None:
    settings.update_repository = "test/project"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    manager = UpdateManager(settings, client=client)
    status = await manager.check()
    assert status["state"] == "error"
    assert "No published GitHub release" in status["error"]
    await client.aclose()


@pytest.mark.asyncio
async def test_install_requires_graceful_shutdown_callback(settings) -> None:
    manager = UpdateManager(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    with pytest.raises(UpdateError, match="graceful shutdown"):
        await manager.install(shutdown_callback=None)
    await manager.client.aclose()


def test_archive_validation_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    archive.write_bytes(_update_zip(unsafe_name="../escape.txt"))
    with pytest.raises(UpdateValidationError, match="unsafe archive path"):
        inspect_update_archive(archive, max_uncompressed_bytes=1_000_000)


def test_checksum_parser_rejects_wrong_filename() -> None:
    with pytest.raises(UpdateValidationError, match="filename"):
        parse_checksum("a" * 64 + "  other.zip", "embodied-alife-update.zip")


def test_apply_update_preserves_local_state_and_removes_obsolete_files(tmp_path: Path) -> None:
    root = tmp_path / "install"
    staged = tmp_path / "staged"
    (root / "app").mkdir(parents=True)
    (root / "data" / "runtime").mkdir(parents=True)
    (staged / "app").mkdir(parents=True)
    (root / ".env").write_text("SECRET=local\n", encoding="utf-8")
    (root / "data" / "runtime" / "world.db").write_text("world", encoding="utf-8")
    (root / "app" / "old.py").write_text("old", encoding="utf-8")
    (staged / "app" / "new.py").write_text("new", encoding="utf-8")
    (root / "data" / "runtime" / "installed-update-manifest.json").write_text(
        json.dumps({"managed_paths": ["app/old.py"]}),
        encoding="utf-8",
    )
    manifest = {"version": "0.3.0", "managed_paths": ["app/new.py"]}

    backup = apply_update(
        project_root=root,
        staged_path=staged,
        manifest=manifest,
        python_executable="python",
        uv_executable=None,
        run_dependency_sync=False,
    )

    assert not (root / "app" / "old.py").exists()
    assert (root / "app" / "new.py").read_text(encoding="utf-8") == "new"
    assert (root / ".env").read_text(encoding="utf-8") == "SECRET=local\n"
    assert (root / "data" / "runtime" / "world.db").read_text(encoding="utf-8") == "world"
    assert (backup / "app" / "old.py").is_file()


def test_apply_update_rolls_back_partial_copy(tmp_path: Path) -> None:
    root = tmp_path / "install"
    staged = tmp_path / "staged"
    (root / "app").mkdir(parents=True)
    (root / "data" / "runtime").mkdir(parents=True)
    (staged / "app").mkdir(parents=True)
    (root / "app" / "existing.py").write_text("original", encoding="utf-8")
    (staged / "app" / "existing.py").write_text("replacement", encoding="utf-8")
    manifest = {
        "version": "0.3.0",
        "managed_paths": ["app/existing.py", "app/missing.py"],
    }

    with pytest.raises(Exception, match="missing"):
        apply_update(
            project_root=root,
            staged_path=staged,
            manifest=manifest,
            python_executable="python",
            uv_executable=None,
            run_dependency_sync=False,
        )
    assert (root / "app" / "existing.py").read_text(encoding="utf-8") == "original"
    assert not (root / "app" / "missing.py").exists()


def test_apply_update_rejects_tampered_manifest_path(tmp_path: Path) -> None:
    root = tmp_path / "install"
    staged = tmp_path / "staged"
    (root / "data" / "runtime").mkdir(parents=True)
    staged.mkdir(parents=True)
    with pytest.raises(Exception, match="unsafe managed path"):
        apply_update(
            project_root=root,
            staged_path=staged,
            manifest={"version": "0.3.0", "managed_paths": ["../escape.py"]},
            python_executable="python",
            uv_executable=None,
            run_dependency_sync=False,
        )


class FakeUpdater:
    def __init__(self) -> None:
        self.status = type("Status", (), {"state": "current"})()
        self.installed = False

    def public_status(self) -> dict:
        return {
            "current_version": __version__,
            "enabled": True,
            "state": "available",
            "update_available": True,
            "latest_version": "0.3.0",
        }

    async def check(self) -> dict:
        return self.public_status()

    async def stop(self) -> None:
        return None

    async def install(self, *, expected_version: str | None, shutdown_callback) -> dict:
        self.installed = True
        assert expected_version == "0.3.0"
        assert shutdown_callback is not None
        return {"ok": True, "version": expected_version}


class NoopShutdown:
    def __call__(self) -> None:
        pass


def test_update_api_requires_confirmation_header(engine) -> None:
    updater = FakeUpdater()
    app = create_app(
        engine.settings,
        engine=engine,
        updater=updater,
        start_background=False,
        shutdown_callback=NoopShutdown(),
    )
    with TestClient(app) as client:
        status = client.get("/api/update/status")
        assert status.json()["latest_version"] == "0.3.0"
        forbidden = client.post("/api/update/install", json={"version": "0.3.0"})
        assert forbidden.status_code == 403
        accepted = client.post(
            "/api/update/install",
            json={"version": "0.3.0"},
            headers={"X-Embodied-Alife-Update": "confirm"},
        )
        assert accepted.status_code == 200
        assert updater.installed is True
        assert client.get("/health").json()["version"] == __version__