from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from packaging.version import Version

import app.updater.manager as updater_manager
from app.updater.manager import UpdateManager


def _package(version: str) -> bytes:
    managed = ["app/main.py", "app/version.py", "pyproject.toml", "scripts/apply_update.py"]
    manifest = {
        "schema_version": 1,
        "app_id": "embodied-alife",
        "version": version,
        "managed_paths": managed,
        "preserved_roots": [".env", ".venv", "data", ".git"],
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest))
        archive.writestr("app/main.py", "print('post3')\n")
        archive.writestr("app/version.py", f'__version__ = "{version}"\n')
        archive.writestr("pyproject.toml", f'[project]\nname="embodied-alife"\nversion="{version}"\n')
        archive.writestr("scripts/apply_update.py", "print('worker')\n")
    return stream.getvalue()


def _release(package: bytes, version: str) -> dict:
    return {
        "tag_name": f"v{version}",
        "name": f"Embodied Artificial Life v{version}",
        "body": "post3 compatibility",
        "html_url": f"https://github.com/test/project/releases/tag/v{version}",
        "published_at": "2026-07-23T00:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "embodied-alife-update.zip", "url": "https://api.github.com/repos/test/project/releases/assets/1", "browser_download_url": "https://example.invalid/package", "size": len(package), "digest": None},
            {"name": "embodied-alife-update.zip.sha256", "url": "https://api.github.com/repos/test/project/releases/assets/2", "browser_download_url": "https://example.invalid/checksum", "size": 100, "digest": None},
        ],
    }


def test_post3_pep440_and_tag_parser_order_after_every_prior_v040_release(settings) -> None:
    assert Version("0.4.0.post3") > Version("0.4.0.post2") > Version("0.4.0.post1") > Version("0.4.0")
    manager = UpdateManager(settings, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    package = _package("0.4.0.post3")
    parsed = manager._parse_release(_release(package, "0.4.0.post3"))
    assert parsed.tag_name == "v0.4.0.post3"
    assert parsed.version == "0.4.0.post3"


@pytest.mark.asyncio
async def test_post3_latest_release_and_verified_staging_accept_post3_over_post2(settings, tmp_path: Path, monkeypatch) -> None:
    version = "0.4.0.post3"
    package = _package(version)
    digest = hashlib.sha256(package).hexdigest()
    payload = _release(package, version)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=payload)
        if request.url.path.endswith("/assets/1"):
            return httpx.Response(200, content=package)
        if request.url.path.endswith("/assets/2"):
            return httpx.Response(200, text=f"{digest}  embodied-alife-update.zip\n")
        return httpx.Response(404)

    monkeypatch.setattr(updater_manager, "__version__", "0.4.0.post2")
    settings.update_repository = "test/project"
    settings.update_enabled = True
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    manager = UpdateManager(settings, client=client, project_root=tmp_path / "project")
    status = await manager.check()
    assert status["update_available"] is True
    assert status["latest_version"] == version
    prepared = await manager.prepare_install(expected_version=version)
    assert prepared["verified_sha256"] == digest
    request = json.loads(Path(prepared["request_path"]).read_text(encoding="utf-8"))
    assert request["manifest"]["app_id"] == "embodied-alife"
    assert request["manifest"]["version"] == version
    assert request["manifest"]["managed_paths"] == ["app/main.py", "app/version.py", "pyproject.toml", "scripts/apply_update.py"]
    await client.aclose()
