from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str, label: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def replace_between(path: str, start: str, end: str, replacement: str, label: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    target.write_text(text[:start_index] + replacement + text[end_index:], encoding="utf-8", newline="\n")


recent_method = '''    def _recent_action_outcomes(self, limit: int = 8) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(32, int(limit))) if isinstance(limit, int) and not isinstance(limit, bool) else 8
        verified: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        current_decision: dict[str, Any] | None = None
        events = self.events if isinstance(self.events, (list, tuple, deque)) else []
        for index, event in enumerate(events):
            if index >= 4096 or not isinstance(event, dict):
                break
            kind = event.get("kind") if isinstance(event.get("kind"), str) else ""
            if kind == "decision":
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                current_decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
                continue
            if kind != "action_result":
                continue
            raw_result = event.get("data") if isinstance(event.get("data"), dict) else None
            if raw_result is None:
                continue
            evidence = raw_result.get("_ari_integrity")
            result = {key: value for key, value in raw_result.items() if key != "_ari_integrity"}
            if not verify_payload(self.agent, "recent_outcome", result, evidence) or result.get("reason") == "started":
                continue
            action = result.get("action") if isinstance(result.get("action"), str) else (current_decision or {}).get("action")
            outcome = {
                "sim_time": finite_number(event.get("sim_time"), None),
                "action": action if isinstance(action, str) else None,
                "target_id": (current_decision or {}).get("target_id") if isinstance((current_decision or {}).get("target_id"), str) else None,
                "success": result.get("success") is True,
                "reason": result.get("reason") if isinstance(result.get("reason"), str) else "unknown",
                "details": result.get("details") if isinstance(result.get("details"), str) else (event.get("message") if isinstance(event.get("message"), str) else ""),
            }
            verified.append((outcome, event, result))
        selected_pairs = verified[-bounded_limit:]
        selected = [outcome for outcome, _, _ in selected_pairs]
        if selected_pairs:
            latest, _, latest_result = selected_pairs[-1]
            latest_action = latest_result.get("action") if isinstance(latest_result.get("action"), str) else None
            if latest.get("success") and latest_action in VIEW_ACTIONS:
                projected = project_view_result_for_recent_outcome(latest_action, latest_result.get("data"))
                if projected:
                    latest["view_result"] = projected
        return selected

'''
replace_between("app/simulation/engine.py", "    def _recent_action_outcomes(", "    def _correct_decision(", recent_method, "verified outcome pairing")
patch(
    "app/simulation/engine.py",
    "from typing import Any\n",
    "from collections import deque\nfrom typing import Any\n",
    "engine deque import",
)
patch(
    "app/simulation/engine.py",
    "from app.memory.vault import MemoryValidationError, MemoryVault\n",
    "from app.memory.vault import MemoryValidationError, MemoryVault\nfrom app.serialization import finite_number\n",
    "engine finite import",
)
patch(
    "app/simulation/engine.py",
    '''        if not self.agent.alive or self.controller.execution or self.agent.sleeping:
            return
        due_consolidation = next(
            (event for event in self.agent.recent_events[-4:] if event.get("kind") == "consolidation_due"),
            None,
        )
''',
    '''        if self.agent.alive is not True or self.controller.execution or self.agent.sleeping is True:
            return
        recent_events = self.agent.recent_events if isinstance(self.agent.recent_events, list) else []
        due_consolidation = next(
            (event for event in recent_events[-4:] if isinstance(event, dict) and event.get("kind") == "consolidation_due"),
            None,
        )
''',
    "engine decision preconditions",
)
patch(
    "app/simulation/engine.py",
    '''            self.agent.recent_events = [
                event for event in self.agent.recent_events if event.get("kind") != "consolidation_due"
            ]
''',
    '''            self.agent.recent_events = [
                event for event in recent_events
                if not isinstance(event, dict) or event.get("kind") != "consolidation_due"
            ]
''',
    "engine consolidation filter",
)
patch(
    "app/simulation/engine.py",
    '''        query_parts = [self.agent.current_intention]
        query_parts.extend(obj["kind"] for obj in perception["visible_objects"][:8])
        query_parts.extend(entity["classification"] for entity in perception["visible_entities"][:5])
        tags = {item for item in self.agent.inventory}
        verified_memory_records = [
            record
            for record in self.vault.list_records()
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
            " ".join(query_parts),
            tags=tags,
            sim_time=self.world.sim_time,
            limit=6,
        )
''',
    '''        query_parts: list[str] = []
        intention = self.agent.current_intention if isinstance(self.agent.current_intention, str) else ""
        if intention.strip():
            query_parts.append(intention.strip()[:400])
        visible_objects = perception.get("visible_objects") if isinstance(perception.get("visible_objects"), list) else []
        for obj in visible_objects[:8]:
            if isinstance(obj, dict) and isinstance(obj.get("kind"), str) and obj.get("kind"):
                query_parts.append(obj["kind"][:80])
        visible_entities = perception.get("visible_entities") if isinstance(perception.get("visible_entities"), list) else []
        for entity in visible_entities[:5]:
            if isinstance(entity, dict) and isinstance(entity.get("classification"), str) and entity.get("classification"):
                query_parts.append(entity["classification"][:80])
        inventory = self.agent.inventory if isinstance(self.agent.inventory, dict) else {}
        tags = {
            key[:80]
            for index, key in enumerate(inventory)
            if index < 64 and isinstance(key, str) and key
        }
        verified_memory_records = [
            record
            for record in self.vault.list_records(limit=4096, scan_limit=4096)
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
            " ".join(query_parts)[:2000],
            tags=tags,
            sim_time=finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0,
            limit=6,
        )
''',
    "engine decision query normalization",
)
# Keep the base scheduler safe for direct use and tests even though the production subclass overrides it.
patch(
    "app/simulation/scheduler.py",
    '''        if not self.agent.alive or self.controller.execution or self.agent.sleeping:
            return
        due_consolidation = next(
            (event for event in self.agent.recent_events[-4:] if event.get("kind") == "consolidation_due"),
            None,
        )
''',
    '''        if self.agent.alive is not True or self.controller.execution or self.agent.sleeping is True:
            return
        recent_events = self.agent.recent_events if isinstance(self.agent.recent_events, list) else []
        due_consolidation = next(
            (event for event in recent_events[-4:] if isinstance(event, dict) and event.get("kind") == "consolidation_due"),
            None,
        )
''',
    "scheduler decision preconditions",
)
patch(
    "app/simulation/scheduler.py",
    '''            self.agent.recent_events = [event for event in self.agent.recent_events if event.get("kind") != "consolidation_due"]
''',
    '''            self.agent.recent_events = [event for event in recent_events if not isinstance(event, dict) or event.get("kind") != "consolidation_due"]
''',
    "scheduler consolidation filter",
)
patch(
    "app/simulation/scheduler.py",
    '''        query_parts = [self.agent.current_intention]
        query_parts.extend(obj["kind"] for obj in perception["visible_objects"][:8])
        query_parts.extend(entity["classification"] for entity in perception["visible_entities"][:5])
        tags = {item for item in self.agent.inventory}
        verified_memory_records = [
            record
            for record in self.vault.list_records()
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
            " ".join(query_parts),
            tags=tags,
            sim_time=self.world.sim_time,
            limit=6,
        )
''',
    '''        query_parts: list[str] = []
        intention = self.agent.current_intention if isinstance(self.agent.current_intention, str) else ""
        if intention.strip():
            query_parts.append(intention.strip()[:400])
        for obj in (perception.get("visible_objects") if isinstance(perception.get("visible_objects"), list) else [])[:8]:
            if isinstance(obj, dict) and isinstance(obj.get("kind"), str) and obj.get("kind"):
                query_parts.append(obj["kind"][:80])
        for entity in (perception.get("visible_entities") if isinstance(perception.get("visible_entities"), list) else [])[:5]:
            if isinstance(entity, dict) and isinstance(entity.get("classification"), str) and entity.get("classification"):
                query_parts.append(entity["classification"][:80])
        inventory = self.agent.inventory if isinstance(self.agent.inventory, dict) else {}
        tags = {key[:80] for index, key in enumerate(inventory) if index < 64 and isinstance(key, str) and key}
        verified_memory_records = [
            record
            for record in self.vault.list_records(limit=4096, scan_limit=4096)
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
            " ".join(query_parts)[:2000],
            tags=tags,
            sim_time=finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0,
            limit=6,
        )
''',
    "scheduler decision query normalization",
)
print("post5 phase11 applied")
