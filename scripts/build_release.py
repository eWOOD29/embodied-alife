from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSET = "embodied-alife-update.zip"
EXCLUDED_ROOTS = {".git", ".venv", "data", "dist"}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(data["project"]["version"])
    namespace: dict[str, str] = {}
    exec((ROOT / "app" / "version.py").read_text(encoding="utf-8"), namespace)
    if namespace.get("__version__") != version:
        raise SystemExit("pyproject.toml and app/version.py versions do not match")
    return version


def source_files() -> list[Path]:
    command = ["git", "ls-files", "--cached"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        candidates = [ROOT / line for line in result.stdout.splitlines() if line.strip()]
    else:
        candidates = list(ROOT.rglob("*"))
    files: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in EXCLUDED_ROOTS:
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in {".zip", ".bundle", ".db", ".pyc"}:
            continue
        if path.name in {"update-manifest.json", ".env"}:
            continue
        files.append(path)
    return sorted(set(files), key=lambda item: item.relative_to(ROOT).as_posix())


def build(output: Path) -> tuple[Path, Path]:
    version = project_version()
    files = source_files()
    managed_paths = [path.relative_to(ROOT).as_posix() for path in files]
    manifest = {
        "schema_version": 1,
        "app_id": "embodied-alife",
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "managed_paths": managed_paths,
        "preserved_roots": [".env", ".venv", "data", ".git"],
        "entrypoint": [".venv/Scripts/python.exe", "-m", "app.serve"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("update-manifest.json", json.dumps(manifest, indent=2) + "\n")
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_name(f"{output.name}.sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"built {output} ({len(files)} managed files, version {version})")
    print(f"sha256 {digest}")
    return output, checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a verified GitHub release update package")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / DEFAULT_ASSET)
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()
