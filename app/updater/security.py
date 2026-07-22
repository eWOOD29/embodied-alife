from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

APP_ID = "embodied-alife"
MANIFEST_NAME = "update-manifest.json"
MAX_FILE_COUNT = 5000


class UpdateValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum(text: str, expected_filename: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    parts = first.replace("*", " ").split()
    if not parts or len(parts[0]) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in parts[0]):
        raise UpdateValidationError("release checksum file is malformed")
    if len(parts) > 1 and Path(parts[-1]).name != expected_filename:
        raise UpdateValidationError("checksum filename does not match the package asset")
    return parts[0].lower()


def _safe_member_path(name: str) -> PurePosixPath:
    candidate = PurePosixPath(name)
    if candidate.is_absolute() or not candidate.parts:
        raise UpdateValidationError(f"unsafe archive path: {name}")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise UpdateValidationError(f"unsafe archive path: {name}")
    if ":" in candidate.parts[0] or "\\" in name:
        raise UpdateValidationError(f"unsafe archive path: {name}")
    return candidate


def inspect_update_archive(
    archive_path: Path,
    *,
    max_uncompressed_bytes: int,
    expected_version: str | None = None,
) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise UpdateValidationError("downloaded update is not a valid ZIP archive") from exc
    with archive:
        members = archive.infolist()
        if not members or len(members) > MAX_FILE_COUNT:
            raise UpdateValidationError("update archive has an invalid file count")
        total_size = 0
        names: set[str] = set()
        for member in members:
            safe = _safe_member_path(member.filename)
            normalized = safe.as_posix().rstrip("/")
            if normalized in names and not member.is_dir():
                raise UpdateValidationError(f"duplicate archive path: {normalized}")
            names.add(normalized)
            total_size += member.file_size
            if total_size > max_uncompressed_bytes:
                raise UpdateValidationError("update archive exceeds the uncompressed size limit")
            unix_mode = member.external_attr >> 16
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise UpdateValidationError(f"symbolic links are not allowed: {normalized}")
        required = {MANIFEST_NAME, "pyproject.toml", "app/main.py", "scripts/apply_update.py"}
        missing = sorted(required - names)
        if missing:
            raise UpdateValidationError(f"update archive is missing required files: {', '.join(missing)}")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateValidationError("update manifest is invalid") from exc
        validate_manifest(manifest, names, expected_version=expected_version)
        return manifest


def validate_manifest(
    manifest: dict[str, Any],
    archive_names: set[str],
    *,
    expected_version: str | None = None,
) -> None:
    if manifest.get("schema_version") != 1:
        raise UpdateValidationError("unsupported update manifest schema")
    if manifest.get("app_id") != APP_ID:
        raise UpdateValidationError("update package belongs to a different application")
    version = str(manifest.get("version", "")).strip()
    if not version:
        raise UpdateValidationError("update manifest has no version")
    if expected_version and version != expected_version:
        raise UpdateValidationError("release version and update manifest version do not match")
    paths = manifest.get("managed_paths")
    if not isinstance(paths, list) or not paths:
        raise UpdateValidationError("update manifest has no managed paths")
    normalized: set[str] = set()
    for raw in paths:
        if not isinstance(raw, str):
            raise UpdateValidationError("managed path entries must be strings")
        path = _safe_member_path(raw).as_posix()
        if path.startswith((".venv/", "data/", ".git/")) or path in {".env", ".venv", "data", ".git"}:
            raise UpdateValidationError(f"protected path may not be managed: {path}")
        if path == MANIFEST_NAME:
            raise UpdateValidationError("the update manifest cannot manage itself")
        if path not in archive_names:
            raise UpdateValidationError(f"managed file is missing from archive: {path}")
        normalized.add(path)
    if len(normalized) != len(paths):
        raise UpdateValidationError("managed path list contains duplicates")


def extract_update_archive(archive_path: Path, destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            safe = _safe_member_path(member.filename)
            target = destination.joinpath(*safe.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            with archive.open(member) as source, target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
    return json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
