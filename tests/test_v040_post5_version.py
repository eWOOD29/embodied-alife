from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from packaging.version import Version

from app.updater.manager import UpdateManager
from app.updater.security import ReleaseInfo
from app.version import __version__
from scripts.build_release import project_version


def _post5_package(path: Path) -> tuple[Path, str]:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "update-manifest.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "app_id": "embodied-alife",
                    "version": "0.4.0.post5",
                    "managed_paths": ["app/version.py"],
                    "preserved_roots": [".env", ".venv", "data", ".git"],
                    "entrypoint": [".venv/Scripts/python.exe", "-m", "app.serve"],
                }
            ),
        )
        archive.writestr("app/version.py", '__version__ = "0.4.0.post5"\n')
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_post5_orders_above_prior_post_releases_and_synchronized_package_version() -> None:
    assert Version("0.4.0.post5") > Version("0.4.0.post4") > Version("0.4.0.post3")
    assert __version__ == "0.4.0.post5"
    assert project_version() == "0.4.0.post5"


def test_updater_stages_post5_over_post4_without_fixed_post_ceiling(settings, monkeypatch) -> None:
    manager = UpdateManager(settings)
    manager.current_version = "0.4.0.post4"
    package, digest = _post5_package(settings.runtime_dir / "post5.zip")
    checksum = settings.runtime_dir / "post5.zip.sha256"
    checksum.write_text(f"{digest}  post5.zip\n", encoding="utf-8")
    release = ReleaseInfo(
        tag_name="v0.4.0.post5",
        version="0.4.0.post5",
        name="v0.4.0.post5",
        body="post5 remediation",
        html_url="https://github.com/eWOOD29/embodied-alife/releases/tag/v0.4.0.post5",
        published_at="2026-07-24T00:00:00Z",
        asset_url="https://example.invalid/post5.zip",
        checksum_url="https://example.invalid/post5.zip.sha256",
        asset_digest=None,
        commit_sha="a" * 40,
    )

    def fake_download(url: str, destination: Path, timeout: float = 90.0) -> Path:
        source = checksum if url.endswith("sha256") else package
        destination.write_bytes(source.read_bytes())
        return destination

    monkeypatch.setattr("app.updater.manager.download_file", fake_download)
    staged = manager._stage_update(release)
    assert staged.version == "0.4.0.post5"
    assert staged.tag_name == "v0.4.0.post5"
    assert staged.asset_sha256 == digest
    assert staged.manifest["version"] == "0.4.0.post5"


def test_release_workflow_derives_exact_tag_from_dynamic_package_version() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    installer = (root / "install-windows.ps1").read_text(encoding="utf-8")
    assert 'RELEASE_TAG=v${PACKAGE_VERSION}' in workflow
    assert "0.4.0.post4" not in workflow
    assert "0.4.0.post5" not in installer
    assert "post4" not in installer.lower()
