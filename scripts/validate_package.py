from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "WINDOWS_SETUP.md",
    "docs/ARCHITECTURE.md",
    "docs/TROUBLESHOOTING.md",
    "docs/SOAK_TEST.md",
    "pyproject.toml",
    ".env.example",
    "appdock.json",
    "start.sh",
    "start-embodied-alife.bat",
    "app/main.py",
    "app/serve.py",
    "app/version.py",
    "app/updater/manager.py",
    "app/updater/security.py",
    "app/simulation/scheduler.py",
    "app/web/templates/index.html",
    "app/web/static/app.js",
    "tests/test_api.py",
    "scripts/enable-tailscale-access.ps1",
    "scripts/disable-tailscale-access.ps1",
    "scripts/apply_update.py",
    "scripts/build_release.py",
    "install-windows.ps1",
    ".github/workflows/release.yml",
    "tests/test_updater.py",
]
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
SOURCE_ONLY_FORBIDDEN_PARTS = {".venv"}
API_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Embodied Artificial Life package tree.")
    parser.add_argument(
        "--installed",
        action="store_true",
        help="Validate an installed tree where .venv, caches, and runtime data are expected.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    installed = args.installed or (ROOT / ".venv").is_dir()

    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    empty = [path for path in REQUIRED if (ROOT / path).is_file() and (ROOT / path).stat().st_size == 0]
    if missing or empty:
        raise SystemExit(f"missing={missing}, empty={empty}")

    manifest = json.loads((ROOT / "appdock.json").read_text(encoding="utf-8"))
    if manifest.get("arguments") != ["-m", "app.serve"]:
        raise SystemExit("appdock.json must launch app.serve so .env HOST and PORT are honored")

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if "HOST=0.0.0.0" not in env_example:
        raise SystemExit(".env.example must default HOST to 0.0.0.0")
    if "UPDATE_REPOSITORY=eWOOD29/embodied-alife" not in env_example:
        raise SystemExit(".env.example must configure the GitHub release repository")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version_file = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    project_match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    app_match = re.search(r'^__version__ = "([^"]+)"$', version_file, re.MULTILINE)
    if not project_match or not app_match or project_match.group(1) != app_match.group(1):
        raise SystemExit("package version declarations do not match")

    forbidden_parts: set[str] = set()
    if not installed:
        forbidden_parts.update(CACHE_PARTS)
        forbidden_parts.update(SOURCE_ONLY_FORBIDDEN_PARTS)

    forbidden = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if any(part in forbidden_parts for part in path.parts)
    ]
    generated = []
    if not installed:
        generated = [
            str(path.relative_to(ROOT))
            for path in (ROOT / "data" / "runtime").glob("*")
            if path.is_file() and path.name != ".gitkeep"
        ]

    secrets = []
    scan_excluded_parts = CACHE_PARTS | {".venv", ".git"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in scan_excluded_parts for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".zip", ".db"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if API_KEY_PATTERN.search(text) and path.name != "validate_package.py":
            secrets.append(str(path.relative_to(ROOT)))

    if forbidden or generated or secrets:
        raise SystemExit(f"forbidden={forbidden}, generated={generated}, possible_secrets={secrets}")

    mode = "installed" if installed else "source"
    print(f"package validation passed ({mode} mode): {len(REQUIRED)} required files present")


if __name__ == "__main__":
    main()
