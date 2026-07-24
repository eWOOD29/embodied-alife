from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import unquote

TEXT_SUFFIXES = {".md", ".py", ".ps1", ".bat", ".toml", ".yml", ".yaml", ".json", ".txt", ".example"}
IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
MAX_DECODE_ROUNDS = 4
MAX_VALUES = 200_000

WINDOWS_USER_HOME = re.compile(r"(?i)(?:^|[^a-z0-9])(?:file:/{2,3})?[a-z]:[\\/]+users[\\/]+[^\\/\s\"']+[\\/]")
POSIX_USER_HOME = re.compile(r"(?i)(?:^|[^a-z0-9])(?:file:/{2,3})?/(?:home|users)/[^/\s\"']+/")
TAILNET_HOST = re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net\b")
DRIVE_URL = re.compile(r"(?i)https?://(?:docs|drive)\.google\.com/")
CREDENTIAL = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~-]{12,}|(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*[\"']?[a-z0-9._~+/=-]{12,})"
)
URI_ENCODED_USER_HOME = re.compile(r"(?i)(?:%5c|%2f)users(?:%5c|%2f)[^%\s]+(?:%5c|%2f)")


def _decoded_forms(value: str) -> list[str]:
    forms: list[str] = []
    queue = deque([value])
    seen: set[str] = set()
    while queue and len(forms) < 32:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        forms.append(current)
        candidates = [unquote(current)]
        try:
            decoded = json.loads(current)
        except (TypeError, ValueError, OverflowError):
            decoded = None
        if isinstance(decoded, str):
            candidates.append(decoded)
        candidates.extend((
            current.replace("\\\\", "\\"),
            current.replace("\\", "/"),
            current.replace("/", "\\"),
        ))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate not in seen and len(candidate) <= 1_000_000:
                queue.append(candidate)
    return forms


def string_findings(value: str, *, context: str) -> list[str]:
    findings: list[str] = []
    for decoded in _decoded_forms(value):
        normalized = decoded.strip()
        for label, pattern in (
            ("windows user-home path", WINDOWS_USER_HOME),
            ("posix user-home path", POSIX_USER_HOME),
            ("Tailnet hostname", TAILNET_HOST),
            ("Google Drive URL", DRIVE_URL),
            ("credential-like value", CREDENTIAL),
            ("URI-encoded user-home path", URI_ENCODED_USER_HOME),
        ):
            if pattern.search(normalized):
                findings.append(f"{context}: {label}")
    return sorted(set(findings))


def _walk_values(value: Any, *, context: str) -> Iterable[tuple[str, str]]:
    queue: deque[tuple[str, Any]] = deque([(context, value)])
    seen: set[int] = set()
    visited = 0
    while queue and visited < MAX_VALUES:
        item_context, current = queue.popleft()
        visited += 1
        if isinstance(current, str):
            yield item_context, current
            continue
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            for index, (key, item) in enumerate(current.items()):
                if index >= 10_000:
                    break
                key_text = key if isinstance(key, str) else "<non-string-key>"
                queue.append((f"{item_context}.{key_text[:160]}", item))
            continue
        if isinstance(current, (list, tuple)):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            for index, item in enumerate(current[:10_000]):
                queue.append((f"{item_context}[{index}]", item))


def structured_findings(value: Any, *, context: str) -> list[str]:
    findings: list[str] = []
    for item_context, text in _walk_values(value, context=context):
        findings.extend(string_findings(text, context=item_context))
    return sorted(set(findings))


def scan_file(path: Path, *, root: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [f"{relative}: unreadable text file"]
    findings = string_findings(text, context=relative)
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(text)
        except (TypeError, ValueError, OverflowError):
            findings.append(f"{relative}: malformed JSON")
        else:
            findings.extend(structured_findings(value, context=relative))
    return sorted(set(findings))


def scan_tree(root: Path, *, include_runtime: bool = False) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in IGNORED_PARTS for part in relative_parts):
            continue
        if not include_runtime and relative_parts and relative_parts[0] == "data":
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"README", "LICENSE"}:
            continue
        findings.extend(scan_file(path, root=root))
    return sorted(set(findings))


def validate_appdock(value: Any) -> list[str]:
    findings = structured_findings(value, context="appdock.json")
    if not isinstance(value, dict):
        return findings + ["appdock.json: root must be a JSON object"]
    if value.get("projectDirectory") != ".":
        findings.append("appdock.json.projectDirectory: must be project-relative '.'")
    if value.get("workingDirectoryPolicy") != "projectDirectory":
        findings.append("appdock.json.workingDirectoryPolicy: must use projectDirectory")
    if value.get("command") != ".venv\\Scripts\\python.exe":
        findings.append("appdock.json.command: must use the project-local interpreter")
    if value.get("arguments") != ["-m", "app.serve"]:
        findings.append("appdock.json.arguments: must launch app.serve")
    return sorted(set(findings))
