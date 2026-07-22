from __future__ import annotations

import math
import re
from typing import Iterable

from app.memory.vault import MemoryRecord


def retrieve_memories(
    records: Iterable[MemoryRecord],
    query: str,
    *,
    categories: set[str] | None = None,
    tags: set[str] | None = None,
    sim_time: float = 0.0,
    limit: int = 6,
) -> list[dict]:
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    wanted_tags = {tag.lower() for tag in (tags or set())}
    scored: list[tuple[float, MemoryRecord]] = []
    for record in records:
        if categories and record.category not in categories:
            continue
        haystack = f"{record.title} {record.content} {' '.join(record.tags)}".lower()
        terms = set(re.findall(r"[a-z0-9]+", haystack))
        keyword_score = len(query_terms & terms) / max(1, len(query_terms))
        tag_score = len(wanted_tags & set(record.tags)) / max(1, len(wanted_tags)) if wanted_tags else 0.0
        age = max(0.0, sim_time - record.sim_time)
        recency = math.exp(-age / 3600.0)
        score = 0.45 * keyword_score + 0.20 * tag_score + 0.25 * record.importance + 0.10 * recency
        if score > 0.08 or not query_terms:
            scored.append((score, record))
    scored.sort(key=lambda pair: (pair[0], pair[1].sim_time), reverse=True)
    return [record.to_dict() | {"retrieval_score": round(score, 4)} for score, record in scored[:limit]]
