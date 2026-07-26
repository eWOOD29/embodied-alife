from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import deque
from contextlib import suppress
from typing import Any

from app.config import Settings
from app.llm.client import LocalLLMClient
from app.llm.schemas import MemoryWrite
from app.memory.consolidation import consolidate_sleep
from app.memory.retrieval import retrieve_memories
from app.memory.vault import MemoryValidationError, MemoryVault
from app.serialization import finite_number, json_safe, json_safe_dict
from app.simulation.integrity import (
    agent_key,
    attach_key,
    current_epoch_id,
    load_or_create_key,
    rotate_authority_epoch,
    safe_message,
    seal_deterministic_starters,
    seal_memory_record,
    seal_record,
    sign_event,
    state_contains_proofs,
    verify_memory_record,
)
from app.simulation.actions import ActionController, ActionResult
from app.simulation.agent import AgentState
from app.simulation.events import Event
from app.simulation.needs import update_needs
from app.simulation.observer import build_observer_state
from app.simulation.npcs import resolve_npc_interactions
from app.simulation.perception import build_perception, observe
from app.simulation.safe_state import builtin_sequence, exact_dict, exact_sequence, exact_weather, finite, finite_pair, integer, records, strict_text
from app.simulation.world import Shelter, WorldState
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore

MEMORY_INTEGRITY_VERSION = 1


def _matching_awakening_timestamp(
    events: Any,
    *,
    run_id: str,
    world_generation_id: str,
) -> float | None:
    """Return a bounded timestamp only from an awakening event bound to this experiment."""

    matches: list[float] = []
    for event in builtin_sequence(events, limit=10000):
        if type(event) is not dict or event.get("kind") != "awakening":
            continue
        data = event.get("data") if type(event.get("data")) is dict else {}
        event_run_id = event.get("run_id") if type(event.get("run_id")) is str else data.get("run_id")
        event_world_id = (
            event.get("world_generation_id")
            if type(event.get("world_generation_id")) is str
            else data.get("world_generation_id")
        )
        if event_run_id != run_id or event_world_id != world_generation_id:
            continue
        timestamp = finite_number(event.get("sim_time"), None, minimum=0.0, maximum=1_000_000_000.0)
        if timestamp is not None:
            matches.append(timestamp)
    return matches[-1] if matches else None


def _restored_agent_payload(
    raw_agent: Any,
    *,
    run_id: str,
    world_generation_id: str,
    state_events: Any,
    database_events: Any,
) -> tuple[dict[str, Any], bool]:
    """Sanitize awakening at the existing-experiment restore boundary.

    AgentState.from_dict intentionally remains context-free so genuinely new and
    Reset-created agents keep their not-yet-presented awakening. Existing state
    must instead distinguish an explicit current-format value from legacy absence
    or malformed input before any Ari-facing consumer runs.
    """

    if type(raw_agent) is not dict:
        raise ValueError("invalid_agent_state")
    payload = dict(raw_agent)
    sentinel = object()
    raw_awakening = raw_agent.get("awakening", sentinel)
    if type(raw_awakening) is dict and type(raw_awakening.get("presented")) is bool:
        current: dict[str, Any] = {"presented": raw_awakening["presented"]}
        narrative = raw_awakening.get("narrative")
        if type(narrative) is str:
            current["narrative"] = narrative
        presented_at = raw_awakening.get("presented_at")
        if presented_at is None:
            current["presented_at"] = None
        else:
            current["presented_at"] = finite_number(
                presented_at,
                None,
                minimum=0.0,
                maximum=1_000_000_000.0,
            )
        payload["awakening"] = current
        return payload, False

    timestamp = _matching_awakening_timestamp(
        state_events,
        run_id=run_id,
        world_generation_id=world_generation_id,
    )
    if timestamp is None:
        timestamp = _matching_awakening_timestamp(
            database_events,
            run_id=run_id,
            world_generation_id=world_generation_id,
        )
    payload["awakening"] = {"presented": True, "presented_at": timestamp}
    return payload, True


class SimulationEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        brain: LocalLLMClient | None = None,
        vault: MemoryVault | None = None,
        load_existing: bool = True,
    ) -> None:
        self.settings = settings
        self.database = database or Database(settings.database_path)
        self.snapshots = SnapshotStore(self.database)
        self.brain = brain or LocalLLMClient(settings)
        self.vault = vault or MemoryVault(settings.memory_dir)
        self.controller = ActionController()
        self.paused = settings.sim_start_paused
        self.speed = settings.sim_speed
        self.events: deque[dict[str, Any]] = deque(maxlen=600)
        self.subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_persist_time = 0.0
        self._last_real_decision_time = 0.0
        self._decision_pending = True
        self._state_version = 0
        self.last_action_result: dict[str, Any] | None = None
        self.last_decision: dict[str, Any] | None = None
        self.memory_writes: deque[dict[str, Any]] = deque(maxlen=60)
        self.pending_memory: dict[str, Any] | None = None
        self.run_id = uuid.uuid4().hex
        self.world_generation_id = uuid.uuid4().hex
        self.current_decision_event_id: int | None = None

        self._migrate_memory_integrity()
        existing = self.database.get_metadata("current_state") if load_existing else None
        self._ari_integrity_key = load_or_create_key(
            settings.runtime_dir,
            allow_create=not state_contains_proofs(existing),
        )
        restored = False
        if existing:
            try:
                self._restore(existing)
                restored = True
            except (KeyError, TypeError, ValueError, OverflowError):
                self.database.set_metadata(
                    "quarantined_malformed_current_state",
                    json_safe(existing, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000, max_source_items=250000),
                )
                self.database.set_metadata("malformed_current_state_recovery", {"action": "started_new_world", "seed": settings.world_seed})
        if restored:
            self._record("system", "Restored the latest local runtime state.", 0.4)
        else:
            self._new_world(settings.world_seed)
            if existing:
                self._record("system", "Malformed persisted state was quarantined; a new world was started without deleting the recovery copy.", 0.8)

    def _migrate_memory_integrity(self) -> None:
        if self.database.get_metadata("memory_integrity_version") == MEMORY_INTEGRITY_VERSION:
            return
        moved = self.vault.quarantine_all("pre-v0.2.9-unverified")
        self.database.clear_memories()
        self.database.set_metadata("memory_integrity_version", MEMORY_INTEGRITY_VERSION)
        self.database.set_metadata("quarantined_pre_integrity_memories", moved)

    def _new_world(self, seed: int, *, clean_experiment: bool = False) -> None:
        if clean_experiment:
            rotate_authority_epoch(self.settings.runtime_dir, self._ari_integrity_key)
            self.database.clear_experiment()
            self.vault.clear()
        self.run_id = uuid.uuid4().hex
        self.world_generation_id = uuid.uuid4().hex
        live_epoch = current_epoch_id(self.settings.runtime_dir)
        self.database.set_metadata("run_id", self.run_id)
        self.database.set_metadata("world_generation_id", self.world_generation_id)
        self.database.set_metadata("authorization_epoch_id", live_epoch)
        self.world = WorldState.generate(seed, self.settings.world_size)
        self.agent = AgentState(x=float(self.world.spawn[0]), y=float(self.world.spawn[1]))
        attach_key(
            self.agent,
            self._ari_integrity_key,
            epoch_id=current_epoch_id(self.settings.runtime_dir),
            run_id=self.run_id,
            world_generation_id=self.world_generation_id,
        )
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
                authority=self.agent,
            )
        self.controller = ActionController()
        self.events.clear()
        self.memory_writes.clear()
        self.last_action_result = None
        self.last_decision = None
        self.pending_memory = None
        self.current_decision_event_id = None
        self._decision_pending = True
        self._record(
            "awakening",
            "Ari wakes in an unfamiliar world with minimal knowledge.",
            0.9,
            {
                "seed": seed,
                "position": list(self.world.spawn),
                "run_id": self.run_id,
                "world_generation_id": self.world_generation_id,
            },
        )
        self._persist_current()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        await self.brain.check_status()
        self._task = asyncio.create_task(self._run_loop(), name="embodied-alife-loop")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._persist_current()
        self.database.close()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.perf_counter()
            if not self.paused:
                await self.advance(self.settings.sim_tick_seconds * self.speed, allow_decision=True)
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.01, self.settings.sim_tick_seconds - elapsed))

    async def advance(self, sim_dt: float, *, allow_decision: bool = True) -> None:
        safe_dt = finite(sim_dt, None, minimum=0.0, maximum=86_400.0)
        if safe_dt is None or safe_dt <= 0:
            return
        remaining = safe_dt
        while remaining > 1e-9:
            dt = min(1.0, remaining)
            remaining -= dt
            self._advance_substep(dt)
        if allow_decision and self.agent.alive is True and self.agent.sleeping is not True and not self.controller.execution:
            now = time.monotonic()
            if self._decision_pending and (now - self._last_real_decision_time >= 1.0 or self._last_real_decision_time == 0):
                await self.make_decision()
                self._last_real_decision_time = now
        current_time = finite(getattr(self.world, "sim_time", None), None, minimum=0.0)
        last_persist = finite(self._last_persist_time, None, minimum=0.0)
        if current_time is not None and last_persist is not None and current_time - last_persist >= 30.0:
            self._persist_current()
        self._state_version = (integer(self._state_version, 0, minimum=0, maximum=10**15) or 0) + 1
        await self._broadcast()

    def _advance_substep(self, dt: float) -> None:
        safe_dt = finite(dt, None, minimum=0.0, maximum=1.0)
        if safe_dt is None or safe_dt <= 0:
            return
        try:
            world_events = self.world.tick(safe_dt)
        except Exception:
            world_events = []
        for world_event in exact_sequence(world_events, limit=4096):
            if type(world_event) is not dict:
                continue
            kind = strict_text(world_event.get("kind"), maximum=120)
            message = strict_text(world_event.get("message"), maximum=4000, allow_empty=True)
            if kind is None or message is None:
                continue
            self._record(kind, message, world_event.get("importance", 0.4), exact_dict(world_event.get("data")))

        try:
            completed, result, moving = self.controller.step(safe_dt, self.world, self.agent)
        except Exception:
            completed, result, moving = False, None, False
        need_result = update_needs(self.agent, self.world, safe_dt, moving=moving is True)
        for message in exact_sequence(need_result.messages, limit=128):
            if type(message) is str:
                self._record("needs", message, 0.8 if need_result.damage else 0.4)

        for event in exact_sequence(resolve_npc_interactions(self.world, self.agent, safe_dt), limit=4096):
            if type(event) is not dict:
                continue
            kind = strict_text(event.get("kind"), maximum=120)
            message = strict_text(event.get("message"), maximum=4000, allow_empty=True)
            if kind is not None and message is not None:
                self._record(kind, message, event.get("importance", 0.5), exact_dict(event.get("data")))

        sim_time = finite(getattr(self.world, "sim_time", None), None, minimum=0.0)
        seed = integer(getattr(self.world, "seed", None), None, minimum=-2_147_483_648, maximum=2_147_483_647)
        weather = exact_weather(getattr(self.world, "weather", None))
        if weather == "storm" and sim_time is not None and seed is not None:
            for shelter in records(getattr(self.world, "shelters", None), Shelter):
                durability = finite(shelter.durability, None, minimum=0.0, maximum=1_000_000.0)
                position = finite_pair(shelter.x, shelter.y)
                shelter_id = strict_text(shelter.id, maximum=160)
                if durability is None or position is None or shelter_id is None:
                    continue
                if self.world._coord_value(seed, int(sim_time), int(position[0] + position[1]), shelter_id) > 0.985:
                    shelter.durability = max(0.0, durability - 0.4 * safe_dt)
                    if shelter.durability == 0:
                        self._record("shelter", f"{shelter_id} was destroyed by the storm.", 0.9)

        interrupt_reason = self._interrupt_reason()
        if interrupt_reason:
            try:
                interrupted = self.controller.interrupt(interrupt_reason, self.agent)
            except Exception:
                interrupted = None
            if interrupted:
                self._handle_action_result(interrupted)
                self._decision_pending = True

        if completed and type(result) is ActionResult:
            self._handle_action_result(result)
            self._decision_pending = True
            if result.reason == "woke":
                recent = self.agent.recent_events if type(self.agent.recent_events) is list else []
                recent.append({
                    "sim_time": sim_time,
                    "kind": "consolidation_due",
                    "message": "A waking memory-consolidation pass is due.",
                    "importance": 0.7,
                    "data": {},
                })
                self.agent.recent_events = recent[-50:]

        if self.agent.alive is not True:
            self.paused = True
            self._decision_pending = False

    def _interrupt_reason(self) -> str | None:
        execution = self.controller.execution
        if not execution:
            return None
        metadata = exact_dict(getattr(execution, "metadata", None))
        conditions = {item for item in exact_sequence(metadata.get("interrupt_if"), limit=32) if type(item) is str}
        last_damage = finite(getattr(self.agent, "last_damage_time", None), None)
        started_at = finite(getattr(execution, "started_at", None), None)
        if "damage_taken" in conditions and last_damage is not None and started_at is not None and last_damage >= started_at:
            return "damage_taken"
        energy = finite(getattr(self.agent, "energy", None), None)
        hydration = finite(getattr(self.agent, "hydration", None), None)
        if "energy_critical" in conditions and energy is not None and energy <= 8:
            return "energy_critical"
        if "hydration_critical" in conditions and hydration is not None and hydration <= 7:
            return "hydration_critical"
        weather = exact_weather(getattr(self.world, "weather", None))
        if "weather_worsens" in conditions and weather == "storm":
            return "weather_worsens"
        if "danger_detected" in conditions:
            position = finite_pair(getattr(self.agent, "x", None), getattr(self.agent, "y", None))
            if position is not None:
                from app.simulation.world import NPC
                for npc in records(getattr(self.world, "npcs", None), NPC):
                    npc_position = finite_pair(npc.x, npc.y)
                    health = finite(npc.health, None, minimum=0.0)
                    if npc.dangerous is True and health is not None and health > 0 and npc_position is not None:
                        if math.hypot(npc_position[0] - position[0], npc_position[1] - position[1]) <= 5:
                            return "danger_detected"
        return None

    async def make_decision(self) -> None:
        if self.agent.alive is not True or self.controller.execution or self.agent.sleeping is True:
            return
        recent_events = builtin_sequence(self.agent.recent_events, limit=4096)
        due_consolidation = next(
            (event for event in recent_events[-4:] if type(event) is dict and event.get("kind") == "consolidation_due"),
            None,
        )
        if due_consolidation:
            await self._consolidate("wake")
            self.agent.recent_events = [event for event in recent_events if type(event) is not dict or event.get("kind") != "consolidation_due"]

        perception = observe(self.world, self.agent)
        query_parts: list[str] = []
        intention = self.agent.current_intention if type(self.agent.current_intention) is str else ""
        if intention.strip():
            query_parts.append(intention.strip()[:400])
        for obj in (perception.get("visible_objects") if type(perception.get("visible_objects")) is list else [])[:8]:
            if type(obj) is dict and type(obj.get("kind")) is str and obj.get("kind"):
                query_parts.append(obj["kind"][:80])
        for entity in (perception.get("visible_entities") if type(perception.get("visible_entities")) is list else [])[:5]:
            if type(entity) is dict and type(entity.get("classification")) is str and entity.get("classification"):
                query_parts.append(entity["classification"][:80])
        inventory = self.agent.inventory if type(self.agent.inventory) is dict else {}
        tags = {key[:80] for index, key in enumerate(inventory) if index < 64 and type(key) is str and key}
        verified_memory_records = [
            record
            for record in self.vault.list_records(limit=4096, scan_limit=4096)
            if verify_memory_record(self.settings.runtime_dir, record, self._ari_integrity_key, authority=self.agent)
        ]
        memories = retrieve_memories(
            verified_memory_records,
            " ".join(query_parts)[:2000],
            tags=tags,
            sim_time=finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0,
            limit=6,
        )
        self.agent.retrieved_memories = memories
        context = {
            "perception": perception,
            "active_plan": self.agent.active_plan,
            "retrieved_memories": memories,
            "recent_outcomes": [self.last_action_result] if self.last_action_result else [],
        }
        result = await self.brain.decide(context)
        model_response_id = self.database.add_model_response(finite(getattr(self.world, "sim_time", None), 0.0) or 0.0, result)
        decision = result.value
        self.agent.decision_source = result.source
        if decision.plan:
            self.agent.active_plan = [step.strip()[:240] for step in decision.plan if step.strip()]
        for key, value in decision.belief_updates.items():
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
                    authority=self.agent,
                )
        self.last_decision = decision.model_dump()
        decision_event = self._record(
            "decision",
            f"Ari chose {decision.action}: {decision.reason}",
            0.55,
            {
                "source": result.source,
                "decision": self.last_decision,
                "status": result.status,
                "error": result.error,
                "model_response_id": model_response_id,
            },
        )
        self.current_decision_event_id = decision_event["id"]

        self.pending_memory = None
        if decision.memory_write:
            self.pending_memory = {
                "candidate": decision.memory_write.model_dump(),
                "decision_event_id": decision_event["id"],
                "model_response_id": model_response_id,
                "decision": self.last_decision,
                "run_id": self.run_id,
                "world_generation_id": self.world_generation_id,
            }
            self._record(
                "memory_candidate",
                f"Ari proposed a memory pending outcome verification: {decision.memory_write.title}",
                0.35,
                self.pending_memory,
            )

        action_result = self.controller.start(decision, self.world, self.agent)
        self._handle_action_result(action_result)
        self._decision_pending = not action_result.success
        if action_result.success and decision.action == "sleep":
            await self._consolidate("sleep_start")

    def _verified_memory_request(self, result: ActionResult, action_event_id: int) -> MemoryWrite | None:
        pending = self.pending_memory
        if not pending or not result.success:
            return None
        candidate = pending["candidate"]
        decision = pending["decision"]
        target = decision.get("target_id") or "current situation"
        tags = list(candidate.get("tags", [])) + ["verified-outcome", result.action.replace("_", "-")]
        content = (
            f"Authoritative outcome: {result.details}\n\n"
            f"Action: {result.action}\n"
            f"Target: {target}\n"
            f"Intent at decision time: {decision.get('intent', '')}\n"
            f"Outcome reason: {result.reason}\n"
            f"Run ID: {self.run_id}\n"
            f"World generation ID: {self.world_generation_id}\n"
            f"Source decision event ID: {pending['decision_event_id']}\n"
            f"Source action-result event ID: {action_event_id}"
        )
        return MemoryWrite(
            category=candidate["category"],
            title=f"Verified {result.action.replace('_', ' ')} outcome: {target}"[:120],
            content=content,
            importance=float(candidate.get("importance", 0.5)),
            tags=tags,
        )

    def _resolve_pending_memory(self, result: ActionResult, action_event: dict[str, Any]) -> None:
        if result.reason == "started" or not self.pending_memory:
            return
        pending = self.pending_memory
        self.pending_memory = None
        if not result.success:
            self._record(
                "memory_rejected",
                "Proposed memory rejected because the authoritative action outcome was unsuccessful.",
                0.65,
                {
                    "reason": "action_outcome_not_successful",
                    "candidate": pending["candidate"],
                    "action_result": result.to_dict(),
                    "decision_event_id": pending["decision_event_id"],
                    "action_result_event_id": action_event["id"],
                },
            )
            return
        request = self._verified_memory_request(result, action_event["id"])
        if request is None:
            return
        try:
            record = self.vault.write(request, finite(getattr(self.world, "sim_time", None), 0.0) or 0.0)
            if not seal_memory_record(
                self.settings.runtime_dir,
                record,
                self._ari_integrity_key,
                "validated_action_event",
                source_ref=f"action-result:{action_event['id']}:{record.id}",
                authority=self.agent,
            ):
                raise MemoryValidationError("memory_integrity_proof_failed")
            self.database.add_memory(record)
            payload = record.to_dict()
            payload["provenance"] = {
                "run_id": self.run_id,
                "world_generation_id": self.world_generation_id,
                "decision_event_id": pending["decision_event_id"],
                "action_result_event_id": action_event["id"],
                "model_response_id": pending["model_response_id"],
            }
            self.memory_writes.append(payload)
            self._record("memory_write", f"Ari wrote verified memory: {record.title}", 0.65, payload)
        except MemoryValidationError as exc:
            self._record(
                "memory_rejected",
                f"Verified memory write rejected: {exc}",
                0.6,
                {
                    "request": request.model_dump(),
                    "reason": str(exc),
                    "decision_event_id": pending["decision_event_id"],
                    "action_result_event_id": action_event["id"],
                },
            )

    async def _consolidate(self, phase: str) -> None:
        outcome = await consolidate_sleep(
            self.brain,
            self.vault,
            self.agent,
            day=self.world.day,
            sim_time=finite(getattr(self.world, "sim_time", None), 0.0) or 0.0,
            events=list(self.events),
        )
        for record in outcome.written:
            self.database.add_memory(record)
            self.memory_writes.append(record.to_dict())
        self._record(
            "consolidation",
            f"Memory consolidation ({phase}) completed via {outcome.source}.",
            0.7,
            {
                "phase": phase,
                "summary": outcome.summary,
                "written": [record.to_dict() for record in outcome.written],
                "rejected": outcome.rejected,
            },
        )

    def _handle_action_result(self, result: ActionResult) -> None:
        payload = result.to_dict()
        if result.reason != "started":
            payload["decision_event_id"] = self.current_decision_event_id
            decision = self.last_decision if type(self.last_decision) is dict else {}
            target_id = decision.get("target_id")
            if type(target_id) is str and target_id:
                payload["target_id"] = target_id
        event = self._record(
            "action_result",
            f"{result.action}: {result.details}",
            0.5 if result.success else 0.7,
            payload,
            authorize_family="recent_outcome" if result.reason != "started" else None,
        )
        self.last_action_result = event["data"]
        self._resolve_pending_memory(result, event)

    def _record(
        self,
        kind: str,
        message: str,
        importance: float = 0.3,
        data: dict[str, Any] | None = None,
        *,
        authorize_family: str | None = None,
    ) -> dict[str, Any]:
        safe_time = finite_number(getattr(self.world, "sim_time", None), 0.0) if hasattr(self, "world") else 0.0
        safe_kind = safe_message(kind, 120) or "unknown"
        safe_event_message = safe_message(message, 4000)
        safe_importance = finite_number(importance, 0.3, minimum=0.0, maximum=1.0) or 0.3
        safe_data = json_safe_dict(
            data if type(data) is dict else {},
            max_depth=12,
            max_items=2048,
            max_text=12000,
            max_nodes=100000,
            max_source_items=120000,
        )
        epoch = current_epoch_id(self.settings.runtime_dir) or "missing-authorization-epoch"

        def finalize(event_id: int) -> dict[str, Any]:
            event = Event(safe_time or 0.0, safe_kind, safe_event_message, safe_data, safe_importance).to_dict()
            event["id"] = event_id
            event["run_id"] = self.run_id
            event["world_generation_id"] = self.world_generation_id
            event["authorization_epoch_id"] = epoch
            if authorize_family is not None and hasattr(self, "agent"):
                evidence = sign_event(
                    self.agent,
                    authorize_family,
                    event,
                    "validated_action_event",
                    source_ref=f"event:{event_id}",
                )
                if evidence is not None:
                    event["data"]["_ari_integrity"] = evidence
            return event

        event = self.database.add_finalized_event(finalize)
        events = builtin_sequence(self.events, limit=599)
        events.append(event)
        self.events = deque(events[-600:], maxlen=600)
        if hasattr(self, "agent"):
            recent = builtin_sequence(self.agent.recent_events, limit=49)
            recent.append(event)
            self.agent.recent_events = recent[-50:]
        return event

    def serialize(self) -> dict[str, Any]:
        state = {
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
            "authorization_epoch_id": current_epoch_id(self.settings.runtime_dir),
            "world": self.world.to_dict(),
            "agent": self.agent.to_dict(),
            "controller": self.controller.execution.to_dict() if self.controller.execution else None,
            "paused": self.paused,
            "speed": self.speed,
            "events": self.events,
            "last_action_result": self.last_action_result,
            "last_decision": self.last_decision,
            "memory_writes": self.memory_writes,
            "pending_memory": self.pending_memory,
            "current_decision_event_id": self.current_decision_event_id,
        }
        return json_safe_dict(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000, max_source_items=250000)

    def _restore(self, state: Any) -> None:
        from app.simulation.body import ActionExecution

        if type(state) is not dict:
            raise ValueError("invalid_state_envelope")
        stored_epoch = state.get("authorization_epoch_id")
        live_epoch = current_epoch_id(self.settings.runtime_dir)
        if stored_epoch is not None and (type(stored_epoch) is not str or stored_epoch != live_epoch):
            raise ValueError("authorization_epoch_mismatch")
        raw_world = state.get("world")
        if type(raw_world) is not dict:
            raise ValueError("invalid_world_state")
        raw_run_id = state.get("run_id")
        raw_world_generation_id = state.get("world_generation_id")
        self.run_id = raw_run_id if type(raw_run_id) is str and raw_run_id else uuid.uuid4().hex
        self.world_generation_id = raw_world_generation_id if type(raw_world_generation_id) is str and raw_world_generation_id else uuid.uuid4().hex
        self.world = WorldState.from_dict(raw_world)
        try:
            database_events = self.database.list_events(limit=10000)
        except Exception:
            database_events = []
        agent_payload, awakening_migrated = _restored_agent_payload(
            state.get("agent"),
            run_id=self.run_id,
            world_generation_id=self.world_generation_id,
            state_events=state.get("events"),
            database_events=database_events,
        )
        self.agent = AgentState.from_dict(agent_payload)
        attach_key(
            self.agent,
            self._ari_integrity_key,
            epoch_id=live_epoch,
            run_id=self.run_id,
            world_generation_id=self.world_generation_id,
        )
        seal_deterministic_starters(self.agent, self._ari_integrity_key)
        self.controller = ActionController()
        raw_controller = state.get("controller")
        if type(raw_controller) is dict:
            try:
                self.controller.execution = ActionExecution.from_dict(raw_controller)
                self.agent.current_action = self.controller.execution.to_dict()
            except (KeyError, TypeError, ValueError, OverflowError):
                self.controller.execution = None
                self.agent.current_action = None
        self.paused = state.get("paused") is True
        raw_speed = state.get("speed")
        self.speed = raw_speed if type(raw_speed) is int and raw_speed in {1, 10, 100} else 1
        raw_events = state.get("events")
        self.events = deque(builtin_sequence(raw_events, limit=600), maxlen=600)
        self.last_action_result = state.get("last_action_result") if type(state.get("last_action_result")) is dict else None
        self.last_decision = state.get("last_decision") if type(state.get("last_decision")) is dict else None
        raw_writes = state.get("memory_writes")
        self.memory_writes = deque(builtin_sequence(raw_writes, limit=60), maxlen=60)
        self.pending_memory = state.get("pending_memory") if type(state.get("pending_memory")) is dict else None
        raw_decision_event_id = state.get("current_decision_event_id")
        self.current_decision_event_id = raw_decision_event_id if type(raw_decision_event_id) is int and raw_decision_event_id > 0 else None
        self._decision_pending = not bool(self.controller.execution)
        self._last_persist_time = finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0
        self.database.set_metadata("run_id", self.run_id)
        self.database.set_metadata("world_generation_id", self.world_generation_id)
        self.database.set_metadata("authorization_epoch_id", live_epoch)
        if awakening_migrated:
            self._persist_current()

    def _persist_current(self) -> None:
        self.database.set_metadata("current_state", self.serialize())
        self._last_persist_time = finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0

    def save_snapshot(self, name: str) -> dict[str, Any]:
        state = self.serialize()
        self.snapshots.save(name, state)
        self._record("snapshot", f"Snapshot '{name}' saved.", 0.4, {"name": name})
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": finite(getattr(self.world, "sim_time", None), 0.0) or 0.0}

    def load_snapshot(self, name: str) -> dict[str, Any]:
        state = self.snapshots.load(name)
        if not state:
            raise KeyError(name)
        self._restore(state)
        self.database.set_metadata("last_snapshot_load_audit", {
            "name": name,
            "sim_time": finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0,
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
        })
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": finite(getattr(self.world, "sim_time", None), 0.0) or 0.0}

    def fork_snapshot(self, name: str, new_name: str) -> dict[str, Any]:
        state = self.snapshots.load(name)
        if not state:
            raise KeyError(name)
        state["paused"] = True
        self.snapshots.save(new_name, state)
        return {"ok": True, "source": name, "name": new_name}

    def reset(self, seed: int | None = None) -> dict[str, Any]:
        self.paused = True
        self._new_world(
            seed if seed is not None else int(time.time()) % 2_147_483_647,
            clean_experiment=True,
        )
        self.paused = False
        return {
            "ok": True,
            "seed": self.world.seed,
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
            "clean_experiment": True,
        }

    def set_paused(self, paused: bool) -> dict[str, Any]:
        self.paused = paused
        self._persist_current()
        return {"ok": True, "paused": self.paused}

    def set_speed(self, speed: int) -> dict[str, Any]:
        if speed not in {1, 10, 100}:
            raise ValueError("speed must be 1, 10, or 100")
        self.speed = speed
        return {"ok": True, "speed": speed}

    def observer_state(self, *, include_map: bool = False) -> dict[str, Any]:
        return build_observer_state(self, include_map=include_map)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.subscribers.add(queue)
        await queue.put(self.observer_state())
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    async def _broadcast(self) -> None:
        if not self.subscribers:
            return
        state = self.observer_state()
        for queue in list(self.subscribers):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                    queue.put_nowait(json_safe(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=250000))
