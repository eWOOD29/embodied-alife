from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


# Cognition provenance schema and type-safe awakening loading.
cognition = read("app/simulation/cognition.py")
cognition = replace_between(
    cognition,
    "@dataclass(slots=True)\nclass Provenance:",
    "\n\n@dataclass(slots=True)\nclass KeyItem:",
    '''@dataclass(slots=True)
class Provenance:
    source_type: str
    source_id: str | None = None
    detail: str | None = None
    creation_path: str | None = None
    proof_version: int | None = None
    proof: str | None = None

    @classmethod
    def from_dict(cls, value: Any, *, default_source: str = "unknown") -> "Provenance":
        value = value if isinstance(value, dict) else {}
        proof_version = value.get("proof_version")
        try:
            parsed_version = int(proof_version) if proof_version is not None and not isinstance(proof_version, bool) else None
        except (TypeError, ValueError, OverflowError):
            parsed_version = None
        proof = _text(value.get("proof"), limit=128) or None
        return cls(
            source_type=_text(value.get("source_type"), default_source, 64),
            source_id=_text(value.get("source_id"), limit=160) or None,
            detail=_text(value.get("detail"), limit=240) or None,
            creation_path=_text(value.get("creation_path"), limit=80) or None,
            proof_version=parsed_version,
            proof=proof,
        )
''',
    "cognition provenance",
)
cognition = replace_once(
    cognition,
    '''    def from_dict(cls, value: dict[str, Any] | None) -> "AwakeningState":
        value = value or {}
        return cls(
''',
    '''    def from_dict(cls, value: Any) -> "AwakeningState":
        value = value if isinstance(value, dict) else {}
        return cls(
''',
    "awakening loader",
)
write("app/simulation/cognition.py", cognition)


# Type-aware AgentState loading, bounded containers, and hidden runtime key.
write("app/simulation/agent.py", '''from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from app.serialization import finite_number, json_safe_dict
from app.simulation.belief_store import BeliefStore
from app.simulation.cognition import (
    AwakeningState,
    EpisodeRecord,
    KeyItem,
    MapMarker,
    NoteRecord,
    TaskRecord,
    starter_key_items,
    starter_tasks,
)


@dataclass(slots=True)
class InventoryItem:
    kind: str
    quantity: int = 1


def _scalar_text(value: Any, limit: int = 160) -> str:
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:limit]
    return ""


def _load_records(value: Any, record_type: Any, id_field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    records: dict[str, Any] = {}
    for index, (key, raw) in enumerate(value.items()):
        if index >= 10000 or not isinstance(raw, dict):
            break
        payload = dict(raw)
        identity = _scalar_text(raw.get(id_field) or key)
        if not identity:
            continue
        payload[id_field] = identity
        try:
            record = record_type.from_dict(payload)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        loaded_id = _scalar_text(getattr(record, id_field, ""))
        if loaded_id and loaded_id not in records:
            records[loaded_id] = record
    return records


def _mapping(value: Any, limit: int = 10000) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(value.items()):
        if index >= limit:
            break
        key = _scalar_text(raw_key)
        if key:
            result[key] = raw_value
    return result


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for raw in value:
        item = _scalar_text(raw, 4000)
        if item:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _inventory(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(value, dict):
        return result
    for index, (raw_key, raw_quantity) in enumerate(value.items()):
        if index >= 1000:
            break
        key = _scalar_text(raw_key, 80)
        quantity = finite_number(raw_quantity, None, minimum=0.0, maximum=1_000_000.0)
        if key and quantity is not None:
            result[key] = int(quantity)
    return result


@dataclass(slots=True)
class AgentState:
    name: str = "Ari"
    x: float = 0.0
    y: float = 0.0
    facing: str = "north"
    movement_speed: float = 2.0
    collision_radius: float = 0.35
    health: float = 100.0
    energy: float = 78.0
    hunger: float = 18.0
    hydration: float = 82.0
    body_temperature_c: float = 37.0
    sleep_pressure: float = 12.0
    pain: float = 0.0
    injury: str | None = None
    inventory: dict[str, int] = field(default_factory=dict)
    inventory_capacity: int = 8
    key_items: dict[str, KeyItem] = field(default_factory=starter_key_items)
    tasks: dict[str, TaskRecord] = field(default_factory=starter_tasks)
    notes: dict[str, NoteRecord] = field(default_factory=dict)
    map_markers: dict[str, MapMarker] = field(default_factory=dict)
    beliefs: BeliefStore = field(default_factory=BeliefStore)
    short_term_episodes: dict[str, EpisodeRecord] = field(default_factory=dict)
    awakening: AwakeningState = field(default_factory=AwakeningState)
    cognition_schema_version: int = 1
    current_action: dict[str, Any] | None = None
    current_intention: str = "Understand what is around me."
    active_plan: list[str] = field(default_factory=list)
    known_locations: dict[str, dict[str, Any]] = field(default_factory=dict)
    explored: set[str] = field(default_factory=set)
    known_terrain: dict[str, str] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    retrieved_memories: list[dict[str, Any]] = field(default_factory=list)
    personality_traits: dict[str, float] = field(
        default_factory=lambda: {"curiosity": 0.78, "caution": 0.61, "persistence": 0.67, "sociability": 0.42}
    )
    alive: bool = True
    sleeping: bool = False
    grace_seconds_remaining: float = 240.0
    last_damage_time: float = -1.0
    last_decision_reason: str = ""
    decision_source: str = "fallback"
    ari_knowledge_proofs: dict[str, dict[str, Any]] = field(default_factory=dict)
    _ari_integrity_key: bytes | None = field(default=None, repr=False, compare=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "beliefs" and not isinstance(value, BeliefStore):
            value = BeliefStore(value)
        object.__setattr__(self, name, value)

    @property
    def inventory_used(self) -> int:
        return sum(quantity for quantity in self.inventory.values() if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0)

    def can_add(self, quantity: int = 1) -> bool:
        requested = quantity if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity > 0 else 0
        capacity = finite_number(self.inventory_capacity, 0.0, minimum=0.0, maximum=1_000_000.0) or 0.0
        return self.inventory_used + requested <= int(capacity)

    def add_item(self, kind: str, quantity: int = 1) -> bool:
        if kind in self.key_items or not self.can_add(quantity):
            return False
        self.inventory[kind] = self.inventory.get(kind, 0) + quantity
        return True

    def remove_item(self, kind: str, quantity: int = 1) -> bool:
        available = self.inventory.get(kind, 0)
        if kind in self.key_items or not isinstance(available, int) or isinstance(available, bool) or available < quantity:
            return False
        self.inventory[kind] -= quantity
        if self.inventory[kind] <= 0:
            del self.inventory[kind]
        return True

    def to_dict(self) -> dict[str, Any]:
        data = {
            field_info.name: getattr(self, field_info.name)
            for field_info in fields(self)
            if not field_info.name.startswith("_")
        }
        explored = self.explored if isinstance(self.explored, (list, tuple, set)) else []
        safe_explored = []
        for raw in explored:
            item = _scalar_text(raw)
            if item:
                safe_explored.append(item)
            if len(safe_explored) >= 10000:
                break
        data["explored"] = sorted(set(safe_explored))
        return json_safe_dict(data, max_depth=10, max_items=10000, max_text=4000, max_nodes=100000)

    @classmethod
    def from_dict(cls, data: Any) -> "AgentState":
        if not isinstance(data, dict):
            return cls()
        allowed = {field_info.name for field_info in fields(cls) if not field_info.name.startswith("_")}
        copied = {key: value for key, value in data.items() if key in allowed}

        explored = copied.get("explored", [])
        copied["explored"] = set(_string_list(explored, 10000)) if isinstance(explored, (list, tuple, set)) else set()
        copied["inventory"] = _inventory(copied.get("inventory"))

        raw_key_items = copied.get("key_items") if "key_items" in copied else None
        copied["key_items"] = starter_key_items() if "key_items" not in copied else _load_records(raw_key_items, KeyItem, "key_item_id")
        raw_tasks = copied.get("tasks") if "tasks" in copied else None
        copied["tasks"] = starter_tasks() if "tasks" not in copied else _load_records(raw_tasks, TaskRecord, "task_id")
        copied["notes"] = _load_records(copied.get("notes"), NoteRecord, "note_id")
        copied["map_markers"] = _load_records(copied.get("map_markers"), MapMarker, "marker_id")
        copied["beliefs"] = BeliefStore(copied.get("beliefs"))
        copied["short_term_episodes"] = _load_records(copied.get("short_term_episodes"), EpisodeRecord, "episode_id")
        copied["awakening"] = AwakeningState.from_dict(copied.get("awakening"))

        copied["known_locations"] = _mapping(copied.get("known_locations"))
        copied["known_terrain"] = _mapping(copied.get("known_terrain"))
        copied["personality_traits"] = _mapping(copied.get("personality_traits"), 1000)
        copied["ari_knowledge_proofs"] = _mapping(copied.get("ari_knowledge_proofs"), 20000)
        copied["current_action"] = copied.get("current_action") if isinstance(copied.get("current_action"), dict) else None
        copied["active_plan"] = _string_list(copied.get("active_plan"), 1000)
        copied["recent_events"] = list(copied.get("recent_events", []))[:1000] if isinstance(copied.get("recent_events"), (list, tuple)) else []
        copied["retrieved_memories"] = list(copied.get("retrieved_memories", []))[:1000] if isinstance(copied.get("retrieved_memories"), (list, tuple)) else []
        try:
            copied["cognition_schema_version"] = int(copied.get("cognition_schema_version", 1))
        except (TypeError, ValueError, OverflowError):
            copied["cognition_schema_version"] = 1
        return cls(**copied)
''')


# Extend integrity module with deterministic starter migration and safe scalar messages.
integrity = read("app/simulation/integrity.py")
if "def seal_deterministic_starters" not in integrity:
    integrity += '''


def safe_message(value: Any, limit: int = 4000) -> str:
    return _text(value, limit)


def _same_record(family: str, left: Any, right: Any) -> bool:
    left_payload = record_payload(family, left, creation_path="deterministic_starter", source_ref="starter")
    right_payload = record_payload(family, right, creation_path="deterministic_starter", source_ref="starter")
    if left_payload is None or right_payload is None:
        return False
    left_payload["source_type"] = "system_initialization"
    right_payload["source_type"] = "system_initialization"
    return left_payload["identity"] == right_payload["identity"] and left_payload["content"] == right_payload["content"]


def seal_deterministic_starters(agent: Any, key: bytes | None) -> None:
    if key is None:
        return
    from app.simulation.cognition import starter_key_items, starter_tasks

    expected_items = starter_key_items()
    actual_items = _member(agent, "key_items")
    if isinstance(actual_items, Mapping):
        for identity, expected in expected_items.items():
            actual = actual_items.get(identity)
            if actual is not None and _same_record("key_item", actual, expected):
                seal_record("key_item", actual, key, "deterministic_starter", source_type="system_initialization", source_ref="v0.4.0-starter-kit")

    expected_tasks = starter_tasks()
    actual_tasks = _member(agent, "tasks")
    if isinstance(actual_tasks, Mapping):
        for identity, expected in expected_tasks.items():
            actual = actual_tasks.get(identity)
            if actual is not None and _same_record("task", actual, expected):
                seal_record("task", actual, key, "deterministic_starter", source_type="system_initialization", source_ref="v0.4.0-starter-journal")
'''
write("app/simulation/integrity.py", integrity)


# Consolidation only receives verified Ari-facing inputs and seals controlled outputs.
write("app/memory/consolidation.py", '''from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LocalLLMClient
from app.memory.vault import MemoryRecord, MemoryValidationError, MemoryVault
from app.simulation.agent import AgentState
from app.simulation.integrity import (
    agent_key,
    seal_memory_record,
    seal_record,
    verify_memory_record,
    verify_record,
)


@dataclass(slots=True)
class ConsolidationOutcome:
    source: str
    summary: str
    written: list[MemoryRecord]
    rejected: list[str]


async def consolidate_sleep(
    brain: LocalLLMClient,
    vault: MemoryVault,
    agent: AgentState,
    *,
    day: int,
    sim_time: float,
    events: list[dict],
) -> ConsolidationOutcome:
    key = agent_key(agent)
    runtime_dir = vault.root.parent / "runtime"
    verified_beliefs = {
        belief_id: belief
        for belief_id, belief in (agent.beliefs.items() if isinstance(agent.beliefs, dict) else [])
        if verify_record("belief", belief, agent)
    }
    verified_memories = [
        record.to_dict()
        for record in vault.list_records()
        if verify_memory_record(runtime_dir, record, key)
    ][-12:]
    result = await brain.consolidate(
        {
            "day": day,
            "body": agent.to_dict(),
            "events": events,
            "beliefs": verified_beliefs,
            "memories": verified_memories,
        }
    )
    written: list[MemoryRecord] = []
    rejected: list[str] = []
    for request in result.value.memories:
        try:
            record = vault.write(request, sim_time)
            if seal_memory_record(
                runtime_dir,
                record,
                key,
                "validated_consolidation",
                source_ref=f"consolidation:{sim_time:.3f}:{record.id}",
            ):
                written.append(record)
            else:
                rejected.append("memory_integrity_proof_failed")
        except MemoryValidationError as exc:
            rejected.append(str(exc))
    for raw_key, raw_value in result.value.belief_updates.items():
        safe_key = raw_key.strip()[:100]
        safe_value = raw_value.strip()[:500]
        if safe_key and safe_value:
            agent.beliefs[safe_key] = safe_value
            belief = agent.beliefs.get(safe_key)
            if isinstance(belief, dict):
                belief["source_type"] = "reflection"
                provenance = belief.get("provenance")
                if isinstance(provenance, dict):
                    provenance["source_type"] = "reflection"
            seal_record(
                "belief",
                belief,
                key,
                "validated_consolidation",
                source_type="reflection",
                source_ref=f"consolidation:{sim_time:.3f}:{safe_key}",
            )
    if result.value.next_intention:
        agent.current_intention = result.value.next_intention
    return ConsolidationOutcome(result.source, result.value.summary, written, rejected)
''')


# Scheduler: key lifecycle, controlled record sealing, verified memories/outcomes.
scheduler = read("app/simulation/scheduler.py")
scheduler = replace_once(
    scheduler,
    "from app.serialization import finite_number, json_safe, json_safe_dict\n",
    '''from app.serialization import finite_number, json_safe, json_safe_dict
from app.simulation.integrity import (
    agent_key,
    attach_key,
    load_or_create_key,
    safe_message,
    seal_deterministic_starters,
    seal_memory_record,
    seal_record,
    sign_payload,
    state_contains_proofs,
    verify_memory_record,
)
''',
    "scheduler imports",
)
scheduler = replace_once(
    scheduler,
    '''        self._migrate_memory_integrity()
        existing = self.database.get_metadata("current_state") if load_existing else None
        if existing:
''',
    '''        self._migrate_memory_integrity()
        existing = self.database.get_metadata("current_state") if load_existing else None
        self._ari_integrity_key = load_or_create_key(
            settings.runtime_dir,
            allow_create=not state_contains_proofs(existing),
        )
        if existing:
''',
    "scheduler key initialization",
)
scheduler = replace_once(
    scheduler,
    '''        self.agent = AgentState(x=float(self.world.spawn[0]), y=float(self.world.spawn[1]))
        self.agent.beliefs = {
            "self": "I have a physical body in an unfamiliar place.",
            "world": "The environment appears real and partially observable; my interpretations may be wrong.",
        }
''',
    '''        self.agent = AgentState(x=float(self.world.spawn[0]), y=float(self.world.spawn[1]))
        attach_key(self.agent, self._ari_integrity_key)
        seal_deterministic_starters(self.agent, self._ari_integrity_key)
        self.agent.beliefs = {
            "self": "I have a physical body in an unfamiliar place.",
            "world": "The environment appears real and partially observable; my interpretations may be wrong.",
        }
        for belief_id, belief in self.agent.beliefs.items():
            if isinstance(belief, dict):
                belief["source_type"] = "system_initialization"
                provenance = belief.get("provenance")
                if isinstance(provenance, dict):
                    provenance["source_type"] = "system_initialization"
            seal_record(
                "belief",
                belief,
                self._ari_integrity_key,
                "deterministic_starter",
                source_type="system_initialization",
                source_ref=f"initial-belief:{belief_id}",
            )
''',
    "scheduler new world sealing",
)
scheduler = replace_once(
    scheduler,
    '''        memories = retrieve_memories(
            self.vault.list_records(),
''',
    '''        verified_memory_records = [
            record
            for record in self.vault.list_records()
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
''',
    "scheduler verified memories",
)
scheduler = replace_once(
    scheduler,
    '''        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
''',
    '''        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
                belief = self.agent.beliefs.get(safe_key)
                if isinstance(belief, dict):
                    belief["source_type"] = "model_belief_update"
                    provenance = belief.get("provenance")
                    if isinstance(provenance, dict):
                        provenance["source_type"] = "model_belief_update"
                seal_record(
                    "belief",
                    belief,
                    self._ari_integrity_key,
                    "validated_model_response",
                    source_type="model_belief_update",
                    source_ref=f"model-response:{model_response_id}:{safe_key}",
                )
''',
    "scheduler belief sealing",
)
scheduler = replace_once(
    scheduler,
    '''            record = self.vault.write(request, self.world.sim_time)
            self.database.add_memory(record)
''',
    '''            record = self.vault.write(request, self.world.sim_time)
            if not seal_memory_record(
                self.settings.runtime_dir,
                record,
                self._ari_integrity_key,
                "validated_action_event",
                source_ref=f"action-result:{action_event['id']}:{record.id}",
            ):
                raise MemoryValidationError("memory_integrity_proof_failed")
            self.database.add_memory(record)
''',
    "scheduler memory proof",
)
scheduler = replace_once(
    scheduler,
    '''    def _handle_action_result(self, result: ActionResult) -> None:
        payload = result.to_dict()
        self.last_action_result = payload
''',
    '''    def _handle_action_result(self, result: ActionResult) -> None:
        payload = result.to_dict()
        if result.reason != "started":
            evidence = sign_payload(
                self.agent,
                "recent_outcome",
                payload,
                "validated_action_event",
                source_ref=uuid.uuid4().hex,
            )
            if evidence is not None:
                payload["_ari_integrity"] = evidence
        self.last_action_result = payload
''',
    "scheduler action result proof",
)
scheduler = replace_once(
    scheduler,
    '''        event = Event(self.world.sim_time if hasattr(self, "world") else 0.0, kind, str(message)[:4000], json_safe_dict(data or {}, max_depth=10, max_items=1000, max_text=4000, max_nodes=50000), finite_number(importance, 0.3) or 0.3).to_dict()
''',
    '''        event = Event(self.world.sim_time if hasattr(self, "world") else 0.0, kind, safe_message(message, 4000), json_safe_dict(data or {}, max_depth=10, max_items=1000, max_text=4000, max_nodes=50000), finite_number(importance, 0.3) or 0.3).to_dict()
''',
    "scheduler safe message",
)
scheduler = replace_once(
    scheduler,
    '''        self.agent = AgentState.from_dict(state["agent"])
        self.controller = ActionController()
''',
    '''        self.agent = AgentState.from_dict(state.get("agent"))
        attach_key(self.agent, self._ari_integrity_key)
        seal_deterministic_starters(self.agent, self._ari_integrity_key)
        self.controller = ActionController()
''',
    "scheduler restore attach",
)
write("app/simulation/scheduler.py", scheduler)


# Production engine mirrors the verified-memory and belief proof contracts.
engine = read("app/simulation/engine.py")
engine = replace_once(
    engine,
    "from app.simulation.perception import build_perception\n",
    '''from app.simulation.perception import build_perception
from app.simulation.integrity import seal_memory_record, seal_record, verify_memory_record, verify_payload
''',
    "engine integrity imports",
)
engine = replace_once(
    engine,
    '''            result = event.get("data") or {}
            if result.get("reason") == "started":
                continue
''',
    '''            raw_result = event.get("data") if isinstance(event, dict) else None
            if not isinstance(raw_result, dict):
                continue
            evidence = raw_result.get("_ari_integrity")
            result = {key: value for key, value in raw_result.items() if key != "_ari_integrity"}
            if not verify_payload(self.agent, "recent_outcome", result, evidence):
                continue
            if result.get("reason") == "started":
                continue
''',
    "engine outcome verification",
)
engine = replace_once(
    engine,
    '''        memories = retrieve_memories(
            self.vault.list_records(),
''',
    '''        verified_memory_records = [
            record
            for record in self.vault.list_records()
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key)
        ]
        memories = retrieve_memories(
            verified_memory_records,
''',
    "engine verified memories",
)
engine = replace_once(
    engine,
    '''        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
''',
    '''        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
                belief = self.agent.beliefs.get(safe_key)
                if isinstance(belief, dict):
                    belief["source_type"] = "model_belief_update"
                    provenance = belief.get("provenance")
                    if isinstance(provenance, dict):
                        provenance["source_type"] = "model_belief_update"
                seal_record(
                    "belief",
                    belief,
                    self._ari_integrity_key,
                    "validated_model_response",
                    source_type="model_belief_update",
                    source_ref=f"model-response:{model_response_id}:{safe_key}",
                )
''',
    "engine belief sealing",
)
engine = replace_once(
    engine,
    '''            record = self.vault.write(request, self.world.sim_time)
            self.database.add_memory(record)
''',
    '''            record = self.vault.write(request, self.world.sim_time)
            if not seal_memory_record(
                self.settings.runtime_dir,
                record,
                self._ari_integrity_key,
                "validated_action_event",
                source_ref=f"action-result:{action_event['id']}:{record.id}",
            ):
                raise MemoryValidationError("memory_integrity_proof_failed")
            self.database.add_memory(record)
''',
    "engine memory proof",
)
write("app/simulation/engine.py", engine)

print("post5 phase1 applied")
