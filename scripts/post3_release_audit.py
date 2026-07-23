from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path("post3-audit")
ZIP_NAME = "embodied-alife-update.zip"
CHECKSUM_NAME = ZIP_NAME + ".sha256"
EXPECTED_TAG = "v0.4.0.post3"
EXPECTED_TARGET = "a27f86c6576bb960428e65f7d6d56c227a40c489"

release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
latest = json.loads((ROOT / "latest.json").read_text(encoding="utf-8"))
zpath = ROOT / ZIP_NAME
cpath = ROOT / CHECKSUM_NAME
checksum_text = cpath.read_text(encoding="utf-8")
match = re.fullmatch(r"([0-9a-fA-F]{64})  embodied-alife-update\.zip\n?", checksum_text)
declared = match.group(1).lower() if match else None
computed = hashlib.sha256(zpath.read_bytes()).hexdigest()
assets = {asset["name"]: asset for asset in release.get("assets", [])}
latest_assets = {asset["name"]: asset for asset in latest.get("assets", [])}
zip_asset = assets.get(ZIP_NAME)
checksum_asset = assets.get(CHECKSUM_NAME)
github_digest = (zip_asset or {}).get("digest")
github_hex = github_digest.split(":", 1)[1].lower() if isinstance(github_digest, str) and github_digest.startswith("sha256:") else None
tag_target = subprocess.check_output(["git", "rev-list", "-n", "1", EXPECTED_TAG], text=True).strip()

forbidden_name_terms = (
    "post3-final-test-output", "post3-preedit-audit", "release-audit", "validation-output", "test-output",
    "applicator", "remote-edit", "trigger", "branch-cleanup", "__pycache__", ".pytest_cache", ".ruff_cache",
)
forbidden_exts = (".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".log")
forbidden_content = (
    "c:\\users\\", "/home/runner/", "/users/ethan/", "docs.google.com/document/d/",
    "ethan assistant system", "tailce5cf1", "private project-lead", "project-lead ruling",
    "post3-final-test-output", "post3-preedit-audit", "github_pat_", "ghp_",
)
expected_roots = {
    ".github", "app", "scripts", "tests", "CHANGELOG.md", "LICENSE", "README.md",
    "install-windows.ps1", "pyproject.toml", "update-manifest.json",
}

with zipfile.ZipFile(zpath) as archive:
    names = archive.namelist()
    corrupt = archive.testzip()
    duplicates = sorted({name for name in names if names.count(name) > 1})
    unsafe_paths: list[str] = []
    unexpected_roots: list[str] = []
    forbidden_names: list[str] = []
    readable_members: list[str] = []
    forbidden_content_hits: list[dict[str, str]] = []
    for name in names:
        path = PurePosixPath(name)
        if name.startswith("/") or "\\" in name or ".." in path.parts or (path.parts and re.fullmatch(r"[A-Za-z]:", path.parts[0])):
            unsafe_paths.append(name)
        root_name = path.parts[0] if path.parts else ""
        if root_name not in expected_roots:
            unexpected_roots.append(name)
        lower_name = name.lower()
        if any(term in lower_name for term in forbidden_name_terms) or lower_name.endswith(forbidden_exts) or lower_name == ".env":
            forbidden_names.append(name)
        info = archive.getinfo(name)
        if name.endswith("/") or info.file_size > 3_000_000:
            continue
        try:
            text = archive.read(name).decode("utf-8")
        except Exception:
            continue
        readable_members.append(name)
        lower_text = text.lower()
        for marker in forbidden_content:
            if marker.lower() in lower_text:
                forbidden_content_hits.append({"member": name, "marker": marker})

    manifest = json.loads(archive.read("update-manifest.json"))
    app_version = archive.read("app/version.py").decode("utf-8")
    pyproject = archive.read("pyproject.toml").decode("utf-8")
    changelog = archive.read("CHANGELOG.md").decode("utf-8")
    perception = archive.read("app/simulation/perception.py").decode("utf-8")
    actions = archive.read("app/simulation/actions.py").decode("utf-8")
    post3_tests = sorted(name for name in names if name.startswith("tests/test_v040_post3"))

packaged_files = sorted(name for name in names if not name.endswith("/") and name != "update-manifest.json")
managed_paths = sorted(manifest.get("managed_paths", []))
freshness = {
    "app_version_post3": "0.4.0.post3" in app_version,
    "pyproject_post3": bool(re.search(r'version\s*=\s*["\']0\.4\.0\.post3["\']', pyproject)),
    "changelog_post3": "0.4.0.post3" in changelog,
    "normalized_satiety": "100.0 - hunger_deficit" in perception and "100.0 - agent.hunger" not in perception,
    "raw_task_to_dict_absent": "task.to_dict() for task" not in actions,
    "raw_note_to_dict_absent": "note.to_dict() for note" not in actions,
    "task_projection": "def _ari_task_projection" in actions,
    "note_projection": "def _ari_note_projection" in actions,
    "map_cell_64": "ARI_MAP_CELL_LIMIT = 64" in actions,
    "map_marker_32": "ARI_MAP_MARKER_LIMIT = 32" in actions,
    "task_32": "ARI_TASK_LIMIT = 32" in actions,
    "note_24": "ARI_NOTE_LIMIT = 24" in actions,
    "marker_projection": "def _ari_marker_projection" in actions,
    "post3_tests": post3_tests,
}

result = {
    "tag_target": tag_target,
    "release": release,
    "latest": latest,
    "zip_asset": zip_asset,
    "checksum_asset": checksum_asset,
    "zip_size_downloaded": zpath.stat().st_size,
    "checksum_size_downloaded": cpath.stat().st_size,
    "checksum_contents": checksum_text,
    "checksum_line_count": len(checksum_text.splitlines()),
    "checksum_strict_syntax": bool(match),
    "declared_sha256": declared,
    "computed_sha256": computed,
    "github_digest": github_digest,
    "declared_matches_computed": declared == computed,
    "github_matches_computed": github_hex in (None, computed),
    "integrity_pass": corrupt is None,
    "corrupt_member": corrupt,
    "member_count": len(names),
    "members": names,
    "duplicate_members": duplicates,
    "unsafe_paths": unsafe_paths,
    "unexpected_root_members": unexpected_roots,
    "manifest_count": names.count("update-manifest.json"),
    "manifest": manifest,
    "packaged_files": packaged_files,
    "managed_paths": managed_paths,
    "managed_paths_match": managed_paths == packaged_files,
    "missing_managed_paths": sorted(set(managed_paths) - set(packaged_files)),
    "unmanaged_packaged_files": sorted(set(packaged_files) - set(managed_paths)),
    "readable_member_count": len(readable_members),
    "forbidden_names": forbidden_names,
    "forbidden_content_hits": forbidden_content_hits,
    "freshness": freshness,
    "latest_asset_ids": {name: asset.get("id") for name, asset in latest_assets.items()},
}
checks = [
    tag_target == EXPECTED_TARGET,
    release.get("tag_name") == EXPECTED_TAG,
    not release.get("draft"),
    not release.get("prerelease"),
    bool(zip_asset),
    bool(checksum_asset),
    latest.get("tag_name") == EXPECTED_TAG,
    bool(match),
    declared == computed,
    github_hex in (None, computed),
    corrupt is None,
    not duplicates,
    not unsafe_paths,
    not unexpected_roots,
    names.count("update-manifest.json") == 1,
    manifest.get("schema_version") == 1,
    manifest.get("app_id") == "embodied-alife",
    manifest.get("version") == "0.4.0.post3",
    manifest.get("preserved_roots") == [".env", ".venv", "data", ".git"],
    managed_paths == packaged_files,
    not forbidden_names,
    not forbidden_content_hits,
    all(value if not isinstance(value, list) else bool(value) for value in freshness.values()),
    (zip_asset or {}).get("id") == (latest_assets.get(ZIP_NAME) or {}).get("id"),
    (checksum_asset or {}).get("id") == (latest_assets.get(CHECKSUM_NAME) or {}).get("id"),
]
result["verdict"] = "PASS" if all(checks) else "FAIL"
Path("post3-release-audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
Path("post3-release-members.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
if result["verdict"] != "PASS":
    raise SystemExit("published release audit failed")
