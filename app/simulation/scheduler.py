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
    load_or_create_key,
    safe_message,
    seal_deterministic_starters,
    seal_memory_record,
    seal_record,
    sign_payload,
    state_contains_proofs,
    verify_memory_record,
)
from app.simulation.actions import ActionController, ActionResult
from app.simulation.agent import AgentState
from app.simulation.events import Event
from app.simulation.needs import update_needs
from app.simulation.observer import build_observer_state
from app.simulation.npcs import resolve_npc_interactions
from app.simulation.perception import build_perception
from app.simulation.world import WorldState
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore

MEMORY_INTEGRITY_VERSION = 1


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
            self.database.clear_experiment()
            self.vault.clear()
        self.run_id = uuid.uuid4().hex
        self.world_generation_id = uuid.uuid4().hex
        self.database.set_metadata("run_id", self.run_id)
        self.database.set_metadata("world_generation_id", self.world_generation_id)
        self.world = WorldState.generate(seed, self.settings.world_size)
        self.agent = AgentState(x=float(self.world.spawn[0]), y=float(self.world.spawn[1]))
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
        self.controller = ActionController()
        self.events.clear()
        self.memory_writes.clear()
        self.last_action_result = None
        self.last_decision = None
        self.pending_memory = None
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
        if sim_dt <= 0:
            return
        remaining = sim_dt
        while remaining > 1e-9:
            dt = min(1.0, remaining)
            remaining -= dt
            self._advance_substep(dt)
        if allow_decision and self.agent.alive and not self.agent.sleeping and not self.controller.execution:
            now = time.monotonic()
            if self._decision_pending and (now - self._last_real_decision_time >= 1.0 or self._last_real_decision_time == 0):
                await self.make_decision()
                self._last_real_decision_time = now
        if self.world.sim_time - self._last_persist_time >= 30.0:
            self._persist_current()
        self._state_version += 1
        await self._broadcast()

    def _advance_substep(self, dt: float) -> None:
        for world_event in self.world.tick(dt):
            self._record(
                world_event["kind"],
                world_event["message"],
                world_event.get("importance", 0.4),
                world_event.get("data", {}),
            )

        completed, result, moving = self.controller.step(dt, self.world, self.agent)
        need_result = update_needs(self.agent, self.world, dt, moving=moving)
        for message in need_result.messages or []:
            self._record("needs", message, 0.8 if need_result.damage else 0.4)

        npc_events = resolve_npc_interactions(self.world, self.agent, dt)
        for event in npc_events:
            self._record(event["kind"], event["message"], event.get("importance", 0.5), event.get("data", {}))

        if self.world.weather == "storm":
            for shelter in self.world.shelters.values():
                if self.world._coord_value(self.world.seed, int(self.world.sim_time), shelter.x + shelter.y, shelter.id) > 0.985:
                    shelter.durability = max(0.0, shelter.durability - 0.4 * dt)
                    if shelter.durability == 0:
                        self._record("shelter", f"{shelter.id} was destroyed by the storm.", 0.9)

        interrupt_reason = self._interrupt_reason()
        if interrupt_reason:
            interrupted = self.controller.interrupt(interrupt_reason, self.agent)
            if interrupted:
                self._handle_action_result(interrupted)
                self._decision_pending = True

        if completed and result:
            self._handle_action_result(result)
            self._decision_pending = True
            if result.reason == "woke":
                self.agent.recent_events.append(
                    {
                        "sim_time": self.world.sim_time,
                        "kind": "consolidation_due",
                        "message": "A waking memory-consolidation pass is due.",
                        "importance": 0.7,
                        "data": {},
                    }
                )

        if not self.agent.alive:
            self.paused = True
            self._decision_pending = False

    def _interrupt_reason(self) -> str | None:
        execution = self.controller.execution
        if not execution:
            return None
        conditions = set(execution.metadata.get("interrupt_if", []))
        if "damage_taken" in conditions and self.agent.last_damage_time >= execution.started_at:
            return "damage_taken"
        if "energy_critical" in conditions and self.agent.energy <= 8:
            return "energy_critical"
        if "hydration_critical" in conditions and self.agent.hydration <= 7:
            return "hydration_critical"
        if "weather_worsens" in conditions and self.world.weather == "storm":
            return "weather_worsens"
        if "danger_detected" in conditions:
            agent_x = finite_number(self.agent.x, 0.0) or 0.0
            agent_y = finite_number(self.agent.y, 0.0) or 0.0
            npcs = self.world.npcs if isinstance(self.world.npcs, dict) else {}
            if any(bool(getattr(npc, "dangerous", False)) and math.hypot((finite_number(getattr(npc, "x", None), 0.0) or 0.0) - agent_x, (finite_number(getattr(npc, "y", None), 0.0) or 0.0) - agent_y) <= 5 for npc in npcs.values()):
                return "danger_detected"
        return None

    async def make_decision(self) -> None:
        if not self.agent.alive or self.controller.execution or self.agent.sleeping:
            return
        due_consolidation = next(
            (event for event in self.agent.recent_events[-4:] if event.get("kind") == "consolidation_due"),
            None,
        )
        if due_consolidation:
            await self._consolidate("wake")
            self.agent.recent_events = [event for event in self.agent.recent_events if event.get("kind") != "consolidation_due"]

        perception = build_perception(self.world, self.agent)
        query_parts = [self.agent.current_intention]
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
        self.agent.retrieved_memories = memories
        context = {
            "perception": perception,
            "active_plan": self.agent.active_plan,
            "retrieved_memories": memories,
            "recent_outcomes": [self.last_action_result] if self.last_action_result else [],
        }
        result = await self.brain.decide(context)
        model_response_id = self.database.add_model_response(self.world.sim_time, result)
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
            record = self.vault.write(request, self.world.sim_time)
            if not seal_memory_record(
                self.settings.runtime_dir,
                record,
                self._ari_integrity_key,
                "validated_action_event",
                source_ref=f"action-result:{action_event['id']}:{record.id}",
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
            sim_time=self.world.sim_time,
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
        event = self._record(
            "action_result",
            f"{result.action}: {result.details}",
            0.5 if result.success else 0.7,
            payload,
        )
        self._resolve_pending_memory(result, event)

    def _record(self, kind: str, message: str, importance: float = 0.3, data: dict[str, Any] | None = None) -> dict[str, Any]:
        event = Event(self.world.sim_time if hasattr(self, "world") else 0.0, kind, safe_message(message, 4000), json_safe_dict(data or {}, max_depth=10, max_items=1000, max_text=4000, max_nodes=50000), finite_number(importance, 0.3) or 0.3).to_dict()
        event["id"] = self.database.add_event(event)
        event["run_id"] = self.run_id
        event["world_generation_id"] = self.world_generation_id
        self.events.append(event)
        if hasattr(self, "agent"):
            self.agent.recent_events.append(event)
            self.agent.recent_events = self.agent.recent_events[-50:]
        return event

    def serialize(self) -> dict[str, Any]:
        state = {
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
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
        }
        return json_safe_dict(state, max_depth=12, max_items=10000, max_text=4000, max_nodes=200000, max_source_items=250000)

    def _restore(self, state: Any) -> None:
        from app.simulation.body import ActionExecution

        if not isinstance(state, dict):
            raise ValueError("invalid_state_envelope")
        raw_world = state.get("world")
        if not isinstance(raw_world, dict):
            raise ValueError("invalid_world_state")
        self.run_id = state.get("run_id") if isinstance(state.get("run_id"), str) and state.get("run_id") else uuid.uuid4().hex
        self.world_generation_id = state.get("world_generation_id") if isinstance(state.get("world_generation_id"), str) and state.get("world_generation_id") else uuid.uuid4().hex
        self.world = WorldState.from_dict(raw_world)
        self.agent = AgentState.from_dict(state.get("agent"))
        attach_key(self.agent, self._ari_integrity_key)
        seal_deterministic_starters(self.agent, self._ari_integrity_key)
        self.controller = ActionController()
        raw_controller = state.get("controller")
        if isinstance(raw_controller, dict):
            try:
                self.controller.execution = ActionExecution.from_dict(raw_controller)
                self.agent.current_action = self.controller.execution.to_dict()
            except (KeyError, TypeError, ValueError, OverflowError):
                self.controller.execution = None
                self.agent.current_action = None
        self.paused = state.get("paused") is True
        raw_speed = state.get("speed")
        self.speed = raw_speed if isinstance(raw_speed, int) and not isinstance(raw_speed, bool) and raw_speed in {1, 10, 100} else 1
        raw_events = state.get("events")
        self.events = deque(raw_events[:600], maxlen=600) if isinstance(raw_events, (list, tuple)) else deque(maxlen=600)
        self.last_action_result = state.get("last_action_result") if isinstance(state.get("last_action_result"), dict) else None
        self.last_decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else None
        raw_writes = state.get("memory_writes")
        self.memory_writes = deque(raw_writes[:60], maxlen=60) if isinstance(raw_writes, (list, tuple)) else deque(maxlen=60)
        self.pending_memory = state.get("pending_memory") if isinstance(state.get("pending_memory"), dict) else None
        self._decision_pending = not bool(self.controller.execution)
        self._last_persist_time = finite_number(getattr(self.world, "sim_time", None), 0.0) or 0.0
        self.database.set_metadata("run_id", self.run_id)
        self.database.set_metadata("world_generation_id", self.world_generation_id)

    def _persist_current(self) -> None:
        self.database.set_metadata("current_state", self.serialize())
        self._last_persist_time = self.world.sim_time

    def save_snapshot(self, name: str) -> dict[str, Any]:
        state = self.serialize()
        self.snapshots.save(name, state)
        self._record("snapshot", f"Snapshot '{name}' saved.", 0.4, {"name": name})
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": self.world.sim_time}

    def load_snapshot(self, name: str) -> dict[str, Any]:
        state = self.snapshots.load(name)
        if not state:
            raise KeyError(name)
        self._restore(state)
        self.database.set_metadata("last_snapshot_load_audit", {
            "name": name,
            "sim_time": self.world.sim_time,
            "run_id": self.run_id,
            "world_generation_id": self.world_generation_id,
        })
        self._persist_current()
        return {"ok": True, "name": name, "sim_time": self.world.sim_time}

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
