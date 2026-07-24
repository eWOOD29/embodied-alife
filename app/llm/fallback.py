from __future__ import annotations

from typing import Any

from app.llm.schemas import ActionDecision, ConsolidationResult, MemoryWrite
from app.serialization import finite_number


class FallbackBrain:
    """Deterministic policy used for tests, no-model mode, and model failures."""

    def __init__(self) -> None:
        self.decision_count = 0

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _records(value: Any, limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item for item in value[:limit] if isinstance(item, dict)]

    @staticmethod
    def _number(value: Any, default: float = 0.0, *, minimum: float | None = None, maximum: float | None = None) -> float:
        number = finite_number(value, default, minimum=minimum, maximum=maximum)
        return default if number is None else number

    @staticmethod
    def _text(value: Any, limit: int = 160) -> str:
        if isinstance(value, str):
            return value.strip()[:limit]
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)[:limit]
        return ""

    def decide(self, perception: dict) -> ActionDecision:
        self.decision_count += 1
        safe_perception = self._mapping(perception)
        body = self._mapping(safe_perception.get("body"))
        inventory_raw = self._mapping(body.get("inventory"))
        inventory: dict[str, int] = {}
        for index, (raw_key, raw_value) in enumerate(inventory_raw.items()):
            if index >= 64:
                break
            key = self._text(raw_key, 80)
            quantity = finite_number(raw_value, None, minimum=0.0, maximum=1_000_000.0)
            if key and quantity is not None:
                inventory[key] = int(quantity)
        visible_objects = self._records(safe_perception.get("visible_objects"), 64)
        visible_entities = self._records(safe_perception.get("visible_entities"), 32)
        raw_available = safe_perception.get("available_actions")
        available = {
            action
            for action in (
                self._text(item, 48)
                for item in (raw_available[:64] if isinstance(raw_available, (list, tuple)) else [])
            )
            if action
        }

        danger = next((entity for entity in visible_entities if entity.get("danger_signs") is True and self._text(entity.get("id"), 160)), None)
        if danger and "flee" in available:
            return ActionDecision(
                intent="Create distance from immediate danger.", action="flee",
                target_id=self._text(danger.get("id"), 160), duration_seconds=5,
                interrupt_if=["damage_taken", "target_unreachable"],
                reason="A nearby creature shows signs of danger.",
            )

        hydration = self._number(body.get("hydration_reserve", body.get("hydration")), 100.0, minimum=0.0, maximum=100.0)
        hunger = self._number(body.get("hunger_deficit", body.get("hunger")), 0.0, minimum=0.0, maximum=100.0)
        energy = self._number(body.get("energy_reserve", body.get("energy")), 100.0, minimum=0.0, maximum=100.0)
        sleep_pressure = self._number(body.get("sleep_pressure"), 0.0, minimum=0.0, maximum=100.0)

        if hydration <= 28:
            if "drink" in available:
                return ActionDecision(intent="Relieve severe thirst.", action="drink", duration_seconds=2, reason="Hydration is low and water is within reach.")
            water_tile = self._nearest_local_tile(safe_perception, {"shallow_water", "deep_water"})
            if water_tile and "move" in available:
                return self._move_toward_local(water_tile, "Find water while hydration is low.")
            known_water = self._known_location(safe_perception, "water_")
            if known_water and "move_to" in available:
                return ActionDecision(intent="Return to remembered water.", action="move_to", target_id=known_water, duration_seconds=8, interrupt_if=["danger_detected", "target_unreachable"], reason="Hydration is low and this is a remembered water location.")

        edible_inventory = next((kind for kind in ("berry", "edible_plant") if inventory.get(kind, 0) > 0), None)
        if hunger >= 62 and edible_inventory and "eat" in available:
            return ActionDecision(intent="Reduce hunger using carried food.", action="eat", target_id=edible_inventory, duration_seconds=2, reason="Hunger is high and edible food is in inventory.")
        if hunger >= 55:
            edible = next((obj for obj in visible_objects if obj.get("appears_edible") is True and self._text(obj.get("id"), 160)), None)
            if edible:
                distance = finite_number(edible.get("distance"), None, minimum=0.0, maximum=1_000_000.0)
                target_id = self._text(edible.get("id"), 160)
                if distance is not None and distance <= 1.6 and "eat" in available:
                    return ActionDecision(intent="Eat nearby food.", action="eat", target_id=target_id, duration_seconds=2, reason="Hunger is elevated and an edible object is within reach.")
                if distance is not None and distance > 1.6 and "move_to" in available:
                    return ActionDecision(intent="Approach visible food.", action="move_to", target_id=target_id, duration_seconds=5, interrupt_if=["danger_detected", "target_unreachable"], reason="Hunger is elevated and visible food may help.")

        if sleep_pressure >= 72 or energy <= 22:
            if "sleep" in available:
                return ActionDecision(intent="Sleep until the body recovers.", action="sleep", duration_seconds=55, interrupt_if=["danger_detected", "damage_taken", "weather_worsens"], reason="Energy is low or sleep pressure is high.")
            shelter = self._known_location(safe_perception, "shelter_")
            if shelter and "move_to" in available:
                return ActionDecision(intent="Reach remembered shelter before sleeping.", action="move_to", target_id=shelter, duration_seconds=8, reason="Rest would be safer and more effective under shelter.")

        if "build" in available and inventory.get("branch", 0) >= 3 and inventory.get("stone", 0) >= 2:
            return ActionDecision(
                intent="Assemble available materials into protection.", action="build", duration_seconds=16,
                interrupt_if=["danger_detected", "damage_taken", "weather_worsens"],
                reason="The ground appears suitable and the required materials are available.",
                memory_write=MemoryWrite(category="projects", title="Building a basic shelter", content="I began turning branches and stones into a protected sleeping place in the stable clearing.", importance=0.72, tags=["shelter", "building", "project"]),
            )

        portable = next(
            (
                obj for obj in visible_objects
                if obj.get("portable") is True
                and self._text(obj.get("id"), 160)
                and (finite_number(obj.get("distance"), None, minimum=0.0, maximum=1_000_000.0) or 1_000_001.0) <= 1.6
            ),
            None,
        )
        capacity = int(self._number(body.get("inventory_capacity"), 0.0, minimum=0.0, maximum=1_000_000.0))
        if portable and sum(inventory.values()) < capacity and "pick_up" in available:
            return ActionDecision(intent="Gather a nearby useful object.", action="pick_up", target_id=self._text(portable.get("id"), 160), duration_seconds=1.5, reason="A portable object is within reach and inventory has space.")

        interesting = next(
            (
                obj for obj in visible_objects
                if self._text(obj.get("id"), 160)
                and (finite_number(obj.get("distance"), None, minimum=0.0, maximum=1_000_000.0) or 0.0) > 1.6
            ),
            None,
        )
        if interesting and self.decision_count % 3 == 0 and "move_to" in available:
            return ActionDecision(intent="Approach an unfamiliar visible object.", action="move_to", target_id=self._text(interesting.get("id"), 160), duration_seconds=5, interrupt_if=["danger_detected", "target_unreachable"], reason="The object may reveal an affordance or resource.")

        if "move" not in available:
            return ActionDecision(intent="Wait until action feasibility can be established safely.", action="wait", duration_seconds=1.0, reason="Position-dependent actions are currently unavailable.")
        directions = ["north", "east", "south", "west", "northeast", "southwest", "southeast", "northwest"]
        day = int(self._number(safe_perception.get("day"), 1.0, minimum=1.0, maximum=10_000_000.0))
        direction = directions[(self.decision_count + day) % len(directions)]
        return ActionDecision(intent="Continue learning the shape of the unfamiliar environment.", action="move", direction=direction, duration_seconds=3.5, interrupt_if=["danger_detected", "target_unreachable", "energy_critical"], reason="No urgent need dominates, so cautious exploration is useful.")

    @classmethod
    def _known_location(cls, perception: dict[str, Any], prefix: str) -> str | None:
        for item in cls._records(perception.get("known_locations"), 64):
            label = cls._text(item.get("label"), 160)
            if label.startswith(prefix):
                return label
        return None

    @classmethod
    def _nearest_local_tile(cls, perception: dict[str, Any], terrain_types: set[str]) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for tile in cls._records(perception.get("local_tiles"), 1024):
            terrain = cls._text(tile.get("terrain"), 80)
            dx = finite_number(tile.get("offset_east"), None, minimum=-1_000_000.0, maximum=1_000_000.0)
            dy = finite_number(tile.get("offset_south"), None, minimum=-1_000_000.0, maximum=1_000_000.0)
            if terrain in terrain_types and dx is not None and dy is not None:
                candidates.append({"offset_east": dx, "offset_south": dy, "terrain": terrain})
        return min(candidates, key=lambda tile: abs(tile["offset_east"]) + abs(tile["offset_south"])) if candidates else None

    @classmethod
    def _move_toward_local(cls, tile: dict[str, Any], intent: str) -> ActionDecision:
        dx = cls._number(tile.get("offset_east"), 0.0, minimum=-1_000_000.0, maximum=1_000_000.0)
        dy = cls._number(tile.get("offset_south"), 0.0, minimum=-1_000_000.0, maximum=1_000_000.0)
        vertical = "north" if dy < 0 else "south"
        horizontal = "west" if dx < 0 else "east"
        direction = vertical if abs(dx) < 2 else horizontal if abs(dy) < 2 else vertical + horizontal
        return ActionDecision(intent=intent, action="move", direction=direction, duration_seconds=max(2, min(6, (abs(dx) + abs(dy)) / 2)), interrupt_if=["danger_detected", "target_unreachable"], reason="A relevant terrain feature is visible in that direction.")

    def consolidate(self, context: dict) -> ConsolidationResult:
        safe_context = self._mapping(context)
        raw_events = safe_context.get("events")
        events = self._records(raw_events[-12:] if isinstance(raw_events, (list, tuple)) else [], 12)
        messages = [self._text(event.get("message"), 400) for event in events]
        event_text = "; ".join(message for message in messages if message) or "The period passed without a major recorded event."
        day = int(self._number(safe_context.get("day"), 1.0, minimum=1.0, maximum=10_000_000.0))
        memory = MemoryWrite(category="daily", title=f"Day {day} consolidation", content=f"During this waking period: {event_text}"[:4000], importance=0.55, tags=["daily", f"day-{day}"])
        return ConsolidationResult(summary=memory.content, memories=[memory], belief_updates={}, next_intention="Reassess bodily needs and nearby changes after waking.")
