from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
TEXT_SUFFIXES = {".md", ".py", ".ps1", ".bat", ".toml", ".yml", ".yaml", ".json", ".txt", ".example"}
IGNORED_ROOTS = {".git", ".venv", "data", "dist", "__pycache__"}

# These exact markers were found in early internal documentation and must never
# reappear elsewhere in the current public tree. Generic environment-variable
# examples are allowed. This file is excluded because it defines the markers.
FORBIDDEN_MARKERS = {
    "".join(("c:\\users\\", "ethan")),
    "".join(("/c/users/", "ethan")),
    "".join(("ethan", "-pc")),
    "".join(("tail", "ce5cf1")),
    "".join(("docs/project_", "handoff.md")),
    "".join(("docs/new_session_", "prompt.md")),
}


def _public_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.resolve() == THIS_FILE:
            continue
        if any(part in IGNORED_ROOTS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"README", "LICENSE"}:
            files.append(path)
    return files


def test_public_tree_contains_no_known_private_machine_markers() -> None:
    findings: list[str] = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                findings.append(f"{path.relative_to(ROOT)} contains {marker!r}")
    assert findings == []


def test_runtime_and_diagnostic_artifacts_are_not_tracked() -> None:
    forbidden_tracked_roots = [ROOT / "data" / "runtime", ROOT / "data" / "agent_memory", ROOT / "logs"]
    findings: list[str] = []
    for root in forbidden_tracked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.name != ".gitkeep":
                findings.append(str(path.relative_to(ROOT)))
    assert findings == []
