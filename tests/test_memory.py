from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.schemas import MemoryWrite
from app.memory.retrieval import retrieve_memories
from app.memory.vault import MemoryValidationError, MemoryVault


def request(**overrides):
    data = {
        "category": "survival",
        "title": "Cold water at night",
        "content": "Sleeping beside open water during rain made the body colder and cost energy.",
        "importance": 0.8,
        "tags": ["water", "night", "cold"],
    }
    data.update(overrides)
    return MemoryWrite(**data)


def test_memory_write_is_sandboxed(tmp_path: Path) -> None:
    vault = MemoryVault(tmp_path / "vault")
    record = vault.write(request(), 120.0)
    path = (vault.root / record.path).resolve()
    assert vault.root in path.parents
    assert path.exists()
    assert "# Cold water at night" in path.read_text(encoding="utf-8")


def test_memory_rejects_unsafe_title_and_content(tmp_path: Path) -> None:
    vault = MemoryVault(tmp_path / "vault")
    with pytest.raises(MemoryValidationError, match="unsafe_title"):
        vault.write(request(title="../../escape"), 1)
    with pytest.raises(MemoryValidationError, match="unsafe_markdown"):
        vault.write(request(title="Unsafe html", content="<script>alert(1)</script>"), 1)


def test_memory_rejects_near_duplicate(tmp_path: Path) -> None:
    vault = MemoryVault(tmp_path / "vault")
    vault.write(request(), 10)
    with pytest.raises(MemoryValidationError, match="near_duplicate"):
        vault.write(request(), 20)


def test_memory_retrieval_scores_keywords_tags_importance(tmp_path: Path) -> None:
    vault = MemoryVault(tmp_path / "vault")
    cold = vault.write(request(), 10)
    vault.write(request(category="entities", title="A quiet raven", content="A raven watched from a tree and did not attack.", importance=0.4, tags=["raven"]), 20)
    found = retrieve_memories(vault.list_records(), "cold water sleep", tags={"water"}, sim_time=100, limit=2)
    assert found[0]["id"] == cold.id
    assert found[0]["retrieval_score"] > 0
