from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.llm.schemas import MemoryWrite

CATEGORY_DIRS = {
    "survival": "memories",
    "locations": "locations",
    "affordances": "memories",
    "environment": "memories",
    "entities": "entities",
    "projects": "projects",
    "beliefs": "beliefs",
    "reflections": "reflections",
    "daily": "daily",
}


@dataclass(slots=True)
class MemoryRecord:
    id: str
    category: str
    title: str
    content: str
    importance: float
    tags: list[str]
    created_at: str
    sim_time: float
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryValidationError(ValueError):
    pass


class MemoryVault:
    def __init__(self, root: Path, max_file_bytes: int = 16_384, max_writes_per_minute: int = 8) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_writes_per_minute = max_writes_per_minute
        self.write_times: deque[float] = deque()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        for folder in set(CATEGORY_DIRS.values()) | {
            "memories",
            "beliefs",
            "locations",
            "entities",
            "projects",
            "reflections",
            "daily",
            "quarantine",
        }:
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def clear(self) -> int:
        """Delete all active memory files while leaving quarantined history intact."""
        removed = 0
        quarantine = (self.root / "quarantine").resolve()
        for path in list(self.root.rglob("*.md")):
            resolved = path.resolve()
            if quarantine == resolved or quarantine in resolved.parents:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        self.write_times.clear()
        self._ensure_directories()
        return removed

    def quarantine_all(self, label: str) -> int:
        """Move active memories out of retrieval without destroying audit evidence."""
        safe_label = re.sub(r"[^a-zA-Z0-9._-]+", "-", label).strip("-") or "quarantine"
        destination = self.root / "quarantine" / safe_label
        destination.mkdir(parents=True, exist_ok=True)
        moved = 0
        quarantine_root = (self.root / "quarantine").resolve()
        for path in list(self.root.rglob("*.md")):
            resolved = path.resolve()
            if quarantine_root == resolved or quarantine_root in resolved.parents:
                continue
            relative = path.relative_to(self.root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = target.with_name(f"{target.stem}-{int(time.time() * 1000)}{target.suffix}")
            shutil.move(str(path), str(target))
            moved += 1
        self.write_times.clear()
        self._ensure_directories()
        return moved

    def validate(self, request: MemoryWrite) -> None:
        if request.category not in CATEGORY_DIRS:
            raise MemoryValidationError("category_not_allowed")
        if "\x00" in request.title or "\x00" in request.content:
            raise MemoryValidationError("null_byte")
        if any(token in request.title for token in ("/", "\\", "..")):
            raise MemoryValidationError("unsafe_title")
        lowered = request.content.lower()
        forbidden = ("<script", "javascript:", "file://", "data:text/html", "{%", "{{")
        if any(token in lowered for token in forbidden):
            raise MemoryValidationError("unsafe_markdown")
        encoded = request.content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise MemoryValidationError("memory_too_large")
        now = time.monotonic()
        while self.write_times and now - self.write_times[0] > 60:
            self.write_times.popleft()
        if len(self.write_times) >= self.max_writes_per_minute:
            raise MemoryValidationError("write_rate_exceeded")
        for record in self.list_records():
            if record.category == request.category:
                title_similarity = SequenceMatcher(None, record.title.lower(), request.title.lower()).ratio()
                content_similarity = SequenceMatcher(None, record.content.lower(), request.content.lower()).ratio()
                if title_similarity > 0.92 or content_similarity > 0.94:
                    raise MemoryValidationError("near_duplicate")

    def write(self, request: MemoryWrite, sim_time: float) -> MemoryRecord:
        self.validate(request)
        created_at = datetime.now(UTC).isoformat()
        slug = self._slugify(request.title)
        digest = hashlib.blake2b(f"{created_at}:{request.title}:{request.content}".encode(), digest_size=5).hexdigest()
        filename = f"{slug}-{digest}.md"
        folder = self.root / CATEGORY_DIRS[request.category]
        path = (folder / filename).resolve()
        if self.root not in path.parents:
            raise MemoryValidationError("path_escape")
        memory_id = digest
        tags = [tag for tag in request.tags if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", tag)]
        frontmatter = [
            "---",
            f"id: {memory_id}",
            f"category: {request.category}",
            f"importance: {request.importance:.3f}",
            f"created_at: {created_at}",
            f"sim_time: {sim_time:.3f}",
            "tags: [" + ", ".join(tags) + "]",
            "---",
            "",
            f"# {request.title}",
            "",
            request.content.strip(),
            "",
        ]
        text = "\n".join(frontmatter)
        if len(text.encode("utf-8")) > self.max_file_bytes:
            raise MemoryValidationError("memory_too_large")
        path.write_text(text, encoding="utf-8", newline="\n")
        self.write_times.append(time.monotonic())
        return MemoryRecord(
            id=memory_id,
            category=request.category,
            title=request.title,
            content=request.content.strip(),
            importance=request.importance,
            tags=tags,
            created_at=created_at,
            sim_time=sim_time,
            path=str(path.relative_to(self.root)).replace("\\", "/"),
        )

    def list_records(self, limit: int | None = None, scan_limit: int = 10000) -> list[MemoryRecord]:
        maximum_scan = max(1, min(100000, int(scan_limit)))
        maximum_output = maximum_scan if limit is None else max(0, min(maximum_scan, int(limit)))
        if maximum_output == 0:
            return []
        quarantine_root = (self.root / "quarantine").resolve()
        candidate_paths: list[Path] = []
        scanned = 0
        for directory, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(name for name in dirnames if name != "quarantine")
            for filename in sorted(filenames):
                if not filename.endswith(".md"):
                    continue
                scanned += 1
                if scanned > maximum_scan:
                    break
                path = Path(directory) / filename
                resolved = path.resolve()
                if quarantine_root == resolved or quarantine_root in resolved.parents:
                    continue
                candidate_paths.append(path)
            if scanned > maximum_scan:
                break
        candidate_paths.sort(key=lambda path: path.relative_to(self.root).as_posix())
        records: deque[MemoryRecord] = deque(maxlen=maximum_output)
        for path in candidate_paths:
            try:
                record = self._parse_file(path)
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                continue
            if record:
                records.append(record)
        return list(records)

    def _parse_file(self, path: Path) -> MemoryRecord | None:
        resolved = path.resolve()
        if self.root not in resolved.parents:
            return None
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        _, meta_text, body = text.split("---", 2)
        meta: dict[str, str] = {}
        for line in meta_text.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        title_match = re.search(r"^# (.+)$", body, flags=re.MULTILINE)
        if not title_match:
            return None
        content = body[title_match.end() :].strip()
        tag_text = meta.get("tags", "[]").strip("[]")
        tags = [tag.strip() for tag in tag_text.split(",") if tag.strip()]
        return MemoryRecord(
            id=meta["id"],
            category=meta["category"],
            title=title_match.group(1).strip(),
            content=content,
            importance=float(meta.get("importance", "0.5")),
            tags=tags,
            created_at=meta.get("created_at", ""),
            sim_time=float(meta.get("sim_time", "0")),
            path=str(path.relative_to(self.root)).replace("\\", "/"),
        )

    @staticmethod
    def _slugify(title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return slug[:64] or "memory"
