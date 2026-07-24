from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

from packaging.version import Version

EXPECTED_TAG = "v0.4.0.post4"
EXPECTED_VERSION = "0.4.0.post4"
EXPECTED_TAG_TARGET = "1b4204d6a8b0caea13d30a34a71f86d6fcc0216b"


def main(root_arg: str = "post4-audit") -> None:
    root = Path(root_arg)
    asset_dir = root / "assets"
    zip_path = asset_dir / "embodied-alife-update.zip"
    checksum_path = asset_dir / "embodied-alife-update.zip.sha256"
    release = json.loads((root / "release.json").read_text(encoding="utf-8"))
    latest = json.loads((root / "latest-release.json").read_text(encoding="utf-8"))
    tag_target = (root / "tag-target.txt").read_text(encoding="utf-8").strip()

    assert release["tag_name"] == EXPECTED_TAG
    assert release["draft"] is False
    assert release["prerelease"] is False
    assert latest["id"] == release["id"]
    assert tag_target == EXPECTED_TAG_TARGET
    assert Version(EXPECTED_VERSION) > Version("0.4.0.post3")

    actual_digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_parts = checksum_path.read_text(encoding="utf-8").strip().split()
    assert checksum_parts == [actual_digest, "embodied-alife-update.zip"]

    assets = {item["name"]: item for item in release["assets"]}
    expected_assets = {"embodied-alife-update.zip", "embodied-alife-update.zip.sha256"}
    assert set(assets) == expected_assets
    assert assets["embodied-alife-update.zip"]["size"] == zip_path.stat().st_size
    assert assets["embodied-alife-update.zip.sha256"]["size"] == checksum_path.stat().st_size

    suspicious_patterns = {
        "credential_shape": re.compile(r"(?i)(?:api[_-]?key|bearer|password|token)\s*[:=]\s*[^\s]{8,}"),
        "windows_absolute_path": re.compile(r"(?i)[A-Z]:\\(?:[^\s\\]+\\)+[^\s\\]*"),
        "unix_private_path": re.compile(r"/(?:home|Users)/[^\s]+"),
        "drive_url": re.compile(r"https?://(?:docs|drive)\.google\.com/\S+", re.I),
        "tailnet_hostname": re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b", re.I),
    }
    exact_private_tokens = [
        "Ethan Assistant System",
        "Post4 Remediation Implementation Report",
        "Third Remediation Implementation Report",
        "Post3 A12 and Cleanup Completion Report",
        "Post3 Independent Review",
        "1OjBiXqLsPfBI0sNAc4XfDRXMeWQ98BrGwNAmAhBMyjE",
        "16QGPMy2DcYGlYUue-Gc-EA7Gf_ChLQhP8Oy0Cyy2QSI",
        "1hqHvtnSEtPKfuQuMpB3VVIa6WW0RZn4-xZcMuSlEnSw",
        "ethan-pc.tailce5cf1.ts.net",
    ]
    forbidden_entry_fragments = [
        "post4-apply",
        "post4-final.patch",
        "post4-trigger",
        "post4-patch.part",
        "post4_release_audit",
        "test-output",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    ]

    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert len(names) == len(set(names))
        assert "update-manifest.json" in names
        for name in names:
            path = PurePosixPath(name)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert "\\" not in name
            lowered = name.lower()
            assert not any(fragment in lowered for fragment in forbidden_entry_fragments)
            assert not lowered.endswith((".db", ".sqlite", ".sqlite3", ".pyc", ".log"))

        manifest = json.loads(archive.read("update-manifest.json"))
        assert manifest["schema_version"] == 1
        assert manifest["app_id"] == "embodied-alife"
        assert manifest["version"] == EXPECTED_VERSION
        assert manifest["preserved_roots"] == [".env", ".venv", "data", ".git"]
        assert manifest["entrypoint"] == [".venv/Scripts/python.exe", "-m", "app.serve"]
        managed = manifest["managed_paths"]
        assert len(managed) == len(set(managed))
        assert set(names) == set(managed) | {"update-manifest.json"}

        required_post4_paths = {
            "app/serialization.py",
            "app/simulation/actions.py",
            "app/simulation/engine.py",
            "app/simulation/perception.py",
            "app/simulation/scheduler.py",
            "app/storage/database.py",
            "tests/test_v040_post4_remediation.py",
            "CHANGELOG.md",
            "docs/ARCHITECTURE.md",
        }
        assert required_post4_paths <= set(names)

        version_py = archive.read("app/version.py").decode("utf-8")
        pyproject = archive.read("pyproject.toml").decode("utf-8")
        build_info = archive.read("app/build_info.py").decode("utf-8")
        engine = archive.read("app/simulation/engine.py").decode("utf-8")
        perception = archive.read("app/simulation/perception.py").decode("utf-8")
        actions = archive.read("app/simulation/actions.py").decode("utf-8")
        assert '__version__ = "0.4.0.post4"' in version_py
        assert 'version = "0.4.0.post4"' in pyproject
        assert EXPECTED_TAG_TARGET in build_info
        assert "project_recent_view_result" in engine and "view_result" in engine
        assert "ari_record_origin_is_safe" in actions
        assert "math.hypot(resource.x - agent.x" not in perception
        assert "relative_direction(resource.x - agent.x" not in perception
        assert "world.shelters.get((round(agent.x), round(agent.y)))" not in perception

        structured_hits: dict[str, list[str]] = {key: [] for key in suspicious_patterns}
        readable_count = 0
        for name in names:
            raw = archive.read(name)
            if len(raw) > 2_000_000:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            readable_count += 1
            assert not any(token in text for token in exact_private_tokens)
            for label, pattern in suspicious_patterns.items():
                if pattern.search(text):
                    structured_hits[label].append(name)

        allowed_fixture_prefixes = ("tests/",)
        allowed_pattern_sources = {"app/simulation/actions.py"}
        unexpected_hits = {
            label: [
                name
                for name in members
                if not name.startswith(allowed_fixture_prefixes) and name not in allowed_pattern_sources
            ]
            for label, members in structured_hits.items()
        }
        assert not any(unexpected_hits.values()), unexpected_hits

    report = {
        "status": "PASS",
        "release_id": release["id"],
        "release_name": release["name"],
        "tag": release["tag_name"],
        "tag_target": tag_target,
        "draft": release["draft"],
        "prerelease": release["prerelease"],
        "published_at": release["published_at"],
        "created_at": release["created_at"],
        "asset_metadata": [
            {
                "id": item["id"],
                "name": item["name"],
                "size": item["size"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "digest": item.get("digest"),
            }
            for item in release["assets"]
        ],
        "sha256": actual_digest,
        "archive_entry_count": len(names),
        "managed_path_count": len(managed),
        "readable_member_count": readable_count,
        "structured_fixture_hits": structured_hits,
        "latest_release_id": latest["id"],
        "updater_ordering": "0.4.0.post4 > 0.4.0.post3",
        "manifest": manifest,
        "archive_members": names,
    }
    (root / "audit-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"manifest", "archive_members"}}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "post4-audit")
