from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from scripts.privacy_scan import scan_tree

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {".git", ".venv", "data", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}
TEMPORARY_PATHS = {
    ".github/workflows/post6-source-export.yml",
    ".github/workflows/post6-pr-export.yml",
    ".github/workflows/post7-exact-head-audit.yml",
    ".github/workflows/post8-exact-head-audit.yml",
}


def validate(archive_path: Path) -> dict[str, object]:
    archive_path = archive_path.resolve()
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_text = checksum_path.read_text(encoding="utf-8").strip()
    if checksum_text != f"{digest}  {archive_path.name}":
        raise SystemExit("archive checksum mismatch")

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "update-manifest.json" not in names:
            raise SystemExit("archive names are duplicated or manifest is missing")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or any(part in FORBIDDEN_PARTS for part in path.parts):
                raise SystemExit(f"unsafe archive path: {name}")
            if name in TEMPORARY_PATHS:
                raise SystemExit(f"temporary workflow present: {name}")
        manifest = json.loads(archive.read("update-manifest.json"))
        managed = manifest.get("managed_paths")
        if type(managed) is not list or any(type(item) is not str for item in managed):
            raise SystemExit("manifest managed_paths is invalid")
        archived_managed = sorted(name for name in names if name != "update-manifest.json")
        if sorted(managed) != archived_managed:
            raise SystemExit("manifest does not reconcile with archive members")
        expected_version = (ROOT / "app" / "version.py").read_text(encoding="utf-8").split('"')[1]
        if manifest.get("version") != expected_version:
            raise SystemExit("manifest version does not match runtime version")

        with tempfile.TemporaryDirectory(prefix="embodied-alife-candidate-") as temporary:
            destination = Path(temporary)
            archive.extractall(destination)
            findings = scan_tree(destination, include_runtime=True)
            if findings:
                raise SystemExit(f"archive privacy findings: {findings}")

    result = {
        "archive": str(archive_path),
        "sha256": digest,
        "version": manifest["version"],
        "managed_files": len(managed),
        "privacy_findings": 0,
        "temporary_paths": 0,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a local pre-publication candidate archive.")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    validate(args.archive)


if __name__ == "__main__":
    main()
