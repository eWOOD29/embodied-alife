from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from contextlib import suppress
from typing import Any

from app.config import Settings
from app.llm.client import LocalLLMClient
from app.memory.consolidation import consolidate_sleep
from app.memory.retrieval import retrieve_memories
from app.memory.vault import MemoryValidationError, MemoryVault
from app.simulation.actions import ActionController, ActionResult
from app.simulation.agent import AgentState
from app.simulation.events import Event
from app.simulation.needs import update_needs
from app.simulation.npcs import resolve_npc_interactions
from app.simulation.perception import build_perception
from app.simulation.world import WorldState
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore


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

        existing = self.database.get_metadata("current_state") if load_existing else None
        if existing:
            self._restore(existing)
            self._record("system", "Restored the latest local runtime state.", 0.4)
        else:
            self._new_world(settings.world_seed)

    def _new_world(self, seed: int) -> None:
        self.world = WorldState.generate(seed, self.settings.world_size)
        self.agent = AgentState(x=float(self.world.spawn[0]), y=float(self.world.spawn[1]))
        self.agent.beliefs = {
            "self": "I have a physical body in an unfamiliar place.",
            "world": "The environment appears real and partially observable; my interpretations may be wrong.",
        }
        self.controller = ActionController()
        self.events.clear()
        self.memory_writes.clear()
        self.last_action_result = None
        self.last_decision = None
        self._decision_pending = True
        self._record(
            "awakening",
            "Ari wakes in an unfamiliar world with minimal knowledge.",
            0.9,
            {"seed": seed, "position": list(self.world.spawn)},
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

        # Weather can slowly damage exposed shelters, while the world continues during sleep.
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
                # Consolidation is deferred to the async decision boundary.
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
            if any(npc.dangerous and math.hypot(npc.x - self.agent.x, npc.y - self.agent.y) <= 5 for npc in self.world.npcs.values()):
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
        memories = retrieve_memories(
            self.vault.list_records(),
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
        self.database.add_model_response(self.world.sim_time, result)
        decision = result.value
        self.agent.decision_source = result.source
        if decision.plan:
            self.agent.active_plan = [step.strip()[:240] for step in decision.plan if step.strip()]
        for key, value in decision.belief_updates.items():
            safe_key = key.strip()[:100]
            safe_value = value.strip()[:500]
            if safe_key and safe_value:
                self.agent.beliefs[safe_key] = safe_value
        self.last_decision = decision.model_dump()
        self._record(
            "decision",
            f"Ari chose {decision.action}: {decision.reason}",
            0.55,
            {"source": result.source, "decision": self.last_decision, "status": result.status, "error": result.error},
        )

        if decision.memory_write:
            try:
                record = self.vault.write(decision.memory_write, self.world.sim_time)
                self.database.add_memory(record)
                self.memory_writes.append(record.to_dict())
                self._record("memory_write", f"Ari wrote memory: {record.title}", 0.65, record.to_dict())
            except MemoryValidationError as exc:
                self._record(
                    "memory_rejected",
                    f"Memory write rejected: {exc}",
                    0.6,
                    {"request": decision.memory_write.model_dump(), "reason": str(exc)},
                )

        action_result = self.controller.start(decision, self.world, self.agent)
        self._handle_action_result(action_result)
        self._decision_pending = not action_result.success
        if action_result.success and decision.action == "sleep":
            await self._consolidate("sleep_start")

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
        self.last_action_result = payload
        self._record(
            "action_result",
            f"{result.action}: {result.details}",
            0.5 if result.success else 0.7,
            payload,
        )

    def _record(self, kind: str, message: str, importance: float = 0.3, data: dict[str, Any] | None = None) -> None:
        event = Event(self.world.sim_time if hasattr(self, "world") else 0.0, kind, message, data or {}, importance).to_dict()
        self.events.append(event)
        if hasattr(self, "agent"):
            self.agent.recent_events.append(event)
            self.agent.recent_events = self.agent.recent_events[-50:]
        self.database.add_event(event)

    def serialize(self) -> dict[str, Any]:
        return {
            "world": self.world.to_dict(),
            "agent": self.agent.to_dict(),
            "controller": self.controller.execution.to_dict() if self.controller.execution else None,
            "paused": self.paused,
            "speed": self.speed,
            "events": list(self.events),
            "last_action_result": self.last_action_result,
            "last_decision": self.last_decision,
            "memory_writes": list(self.memory_writes),
        }

    def _restore(self, state: dict[str, Any]) -> None:
        from app.simulation.body import ActionExecution

        self.world = WorldState.from_dict(state["world"])
        self.agent = AgentState.from_dict(state["agent"])
        self.controller = ActionController()
        if state.get("controller"):
            self.controller.execution = ActionExecution.from_dict(state["controller"])
            self.agent.current_action = self.controller.execution.to_dict()
        self.paused = state.get("paused", True)
        self.speed = state.get("speed", 1)
        self.events = deque(state.get("events", []), maxlen=600)
        self.last_action_result = state.get("last_action_result")
        self.last_decision = state.get("last_decision")
        self.memory_writes = deque(state.get("memory_writes", []), maxlen=60)
        self._decision_pending = not bool(self.controller.execution)
        self._last_persist_time = self.world.sim_time

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
        self.paused = True
        self._record("snapshot", f"Snapshot '{name}' loaded; simulation paused.", 0.5, {"name": name})
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
        self._new_world(seed if seed is not None else int(time.time()) % 2_147_483_647)
        self.paused = False
        return {"ok": True, "seed": self.world.seed}

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
        perception = build_perception(self.world, self.agent)
        state = {
            "version": self._state_version,
            "paused": self.paused,
            "speed": self.speed,
            "world": {
                "seed": self.world.seed,
                "size": self.world.size,
                "sim_time": round(self.world.sim_time, 2),
                "day": self.world.day,
                "hour": round(self.world.hour(), 2),
                "daylight": round(self.world.daylight(), 3),
                "weather": self.world.weather,
                "ambient_temperature_c": self.world.ambient_temperature_c,
                "resources": [r.to_dict() for r in self.world.resources.values() if r.quantity > 0],
                "shelters": [s.to_dict() for s in self.world.shelters.values()],
                "npcs": [npc.to_dict() for npc in self.world.npcs.values()],
                "truth": self.world.truth_notes,
            },
            "agent": self.agent.to_dict(),
            "agent_perception": perception,
            "agent_beliefs": dict(self.agent.beliefs),
            "last_decision": self.last_decision,
            "last_action_result": self.last_action_result,
            "events": list(self.events)[-120:],
            "memory_writes": list(self.memory_writes),
            "memories": [record.to_dict() for record in self.vault.list_records()[-60:]],
            "model_status": dict(self.brain.status),
            "snapshots": self.snapshots.list(),
        }
        if include_map:
            state["world"]["tiles"] = self.world.tiles
        return state

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
                queue.put_nowait(state)
