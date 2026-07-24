from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from packaging.version import Version

from app.updater.manager import UpdateManager
from app.version import __version__
from scripts.build_release import project_version


def _post5_package(path: Path) -> tuple[Path, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    managed_paths = ["app/main.py", "app/version.py", "pyproject.toml", "scripts/apply_update.py"]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "update-manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": "embodied-alife",
                    "version": "0.4.0.post5",
                    "managed_paths": managed_paths,
                    "preserved_roots": [".env", ".venv", "data", ".git"],
                    "entrypoint": [".venv/Scripts/python.exe", "-m", "app.serve"],
                }
            ),
        )
        archive.writestr("app/main.py", "# synthetic updater fixture\n")
        archive.writestr("app/version.py", '__version__ = "0.4.0.post5"\n')
        archive.writestr("pyproject.toml", '[project]\nname = "embodied-alife"\nversion = "0.4.0.post5"\n')
        archive.writestr("scripts/apply_update.py", "# synthetic updater fixture\n")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_post5_orders_above_prior_post_releases_and_synchronized_package_version() -> None:
    assert Version("0.4.0.post5") > Version("0.4.0.post4") > Version("0.4.0.post3")
    assert __version__ == "0.4.0.post5"
    assert project_version() == "0.4.0.post5"


@pytest.mark.asyncio
async def test_updater_stages_post5_over_post4_without_fixed_post_ceiling(settings, monkeypatch) -> None:
    package, digest = _post5_package(settings.runtime_dir / "embodied-alife-update.zip")
    release = {
        "tag_name": "v0.4.0.post5",
        "name": "v0.4.0.post5",
        "body": "post5 remediation",
        "html_url": "https://github.com/eWOOD29/embodied-alife/releases/tag/v0.4.0.post5",
        "published_at": "2026-07-24T00:00:00Z",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "embodied-alife-update.zip",
                "url": "https://api.github.com/repos/test/project/releases/assets/1",
                "browser_download_url": "https://example.invalid/embodied-alife-update.zip",
                "size": len(package.read_bytes()),
                "digest": None,
            },
            {
                "name": "embodied-alife-update.zip.sha256",
                "url": "https://api.github.com/repos/test/project/releases/assets/2",
                "browser_download_url": "https://example.invalid/embodied-alife-update.zip.sha256",
                "size": 92,
                "digest": None,
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json=release)
        if request.url.path.endswith("/assets/1"):
            return httpx.Response(200, content=package.read_bytes())
        if request.url.path.endswith("/assets/2"):
            return httpx.Response(200, text=f"{digest}  embodied-alife-update.zip\n")
        return httpx.Response(404)

    monkeypatch.setattr("app.updater.manager.__version__", "0.4.0.post4")
    settings.update_repository = "test/project"
    settings.update_enabled = True
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    manager = UpdateManager(settings, client=client, project_root=settings.runtime_dir / "install")
    try:
        status = await manager.check()
        assert status["update_available"] is True
        assert status["latest_version"] == "0.4.0.post5"
        prepared = await manager.prepare_install(expected_version="0.4.0.post5")
        assert prepared["verified_sha256"] == digest
        request = json.loads(Path(prepared["request_path"]).read_text(encoding="utf-8"))
        assert request["manifest"]["version"] == "0.4.0.post5"
        assert Path(request["staged_path"], "app", "version.py").is_file()
    finally:
        await client.aclose()


def test_release_workflow_derives_exact_tag_from_dynamic_package_version() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    installer = (root / "install-windows.ps1").read_text(encoding="utf-8")
    assert 'RELEASE_TAG=v${PACKAGE_VERSION}' in workflow
    assert "0.4.0.post4" not in workflow
    assert "0.4.0.post5" not in installer
    assert "post4" not in installer.lower()
