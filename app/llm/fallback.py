from __future__ import annotations

from app.llm.schemas import ActionDecision, ConsolidationResult, MemoryWrite


class FallbackBrain:
    """Deterministic policy used for tests, no-model mode, and model failures."""

    def __init__(self) -> None:
        self.decision_count = 0

    def decide(self, perception: dict) -> ActionDecision:
        self.decision_count += 1
        body = perception["body"]
        visible_objects = perception.get("visible_objects", [])
        visible_entities = perception.get("visible_entities", [])
        available = set(perception.get("available_actions", []))

        danger = next((entity for entity in visible_entities if entity.get("danger_signs")), None)
        if danger and "flee" in available:
            return ActionDecision(
                intent="Create distance from immediate danger.",
                action="flee",
                target_id=danger["id"],
                duration_seconds=5,
                interrupt_if=["damage_taken", "target_unreachable"],
                reason="A nearby creature shows signs of danger.",
            )

        if body["hydration"] <= 28:
            if "drink" in available:
                return ActionDecision(
                    intent="Relieve severe thirst.",
                    action="drink",
                    duration_seconds=2,
                    reason="Hydration is low and water is within reach.",
                )
            water_tile = self._nearest_local_tile(perception, {"shallow_water", "deep_water"})
            if water_tile:
                return self._move_toward_local(water_tile, "Find water while hydration is low.")
            known_water = next((key for key in perception.get("known_locations", {}) if key.startswith("water_")), None)
            if known_water:
                return ActionDecision(
                    intent="Return to remembered water.",
                    action="move_to",
                    target_id=known_water,
                    duration_seconds=8,
                    interrupt_if=["danger_detected", "target_unreachable"],
                    reason="Hydration is low and this is a remembered water location.",
                )

        edible_inventory = next((kind for kind in ("berry", "edible_plant") if body["inventory"].get(kind, 0) > 0), None)
        if body["hunger"] >= 62 and edible_inventory:
            return ActionDecision(
                intent="Reduce hunger using carried food.",
                action="eat",
                target_id=edible_inventory,
                duration_seconds=2,
                reason="Hunger is high and edible food is in inventory.",
            )
        if body["hunger"] >= 55:
            edible = next((obj for obj in visible_objects if obj.get("appears_edible")), None)
            if edible:
                if edible["distance"] <= 1.6:
                    return ActionDecision(
                        intent="Eat nearby food.",
                        action="eat",
                        target_id=edible["id"],
                        duration_seconds=2,
                        reason="Hunger is elevated and an edible object is within reach.",
                    )
                return ActionDecision(
                    intent="Approach visible food.",
                    action="move_to",
                    target_id=edible["id"],
                    duration_seconds=5,
                    interrupt_if=["danger_detected", "target_unreachable"],
                    reason="Hunger is elevated and visible food may help.",
                )

        if body["sleep_pressure"] >= 72 or body["energy"] <= 22:
            if "sleep" in available:
                return ActionDecision(
                    intent="Sleep until the body recovers.",
                    action="sleep",
                    duration_seconds=55,
                    interrupt_if=["danger_detected", "damage_taken", "weather_worsens"],
                    reason="Energy is low or sleep pressure is high.",
                )
            shelter = next((key for key in perception.get("known_locations", {}) if key.startswith("shelter_")), None)
            if shelter:
                return ActionDecision(
                    intent="Reach remembered shelter before sleeping.",
                    action="move_to",
                    target_id=shelter,
                    duration_seconds=8,
                    reason="Rest would be safer and more effective under shelter.",
                )

        if "build" in available and body["inventory"].get("branch", 0) >= 3 and body["inventory"].get("stone", 0) >= 2:
            return ActionDecision(
                intent="Assemble available materials into protection.",
                action="build",
                duration_seconds=16,
                interrupt_if=["danger_detected", "damage_taken", "weather_worsens"],
                reason="The ground appears suitable and the required materials are available.",
                memory_write=MemoryWrite(
                    category="projects",
                    title="Building a basic shelter",
                    content="I began turning branches and stones into a protected sleeping place in the stable clearing.",
                    importance=0.72,
                    tags=["shelter", "building", "project"],
                ),
            )

        portable = next((obj for obj in visible_objects if obj.get("portable") and obj["distance"] <= 1.6), None)
        if portable and sum(body["inventory"].values()) < body["inventory_capacity"]:
            return ActionDecision(
                intent="Gather a nearby useful object.",
                action="pick_up",
                target_id=portable["id"],
                duration_seconds=1.5,
                reason="A portable object is within reach and inventory has space.",
            )

        interesting = next((obj for obj in visible_objects if obj["distance"] > 1.6), None)
        if interesting and self.decision_count % 3 == 0:
            return ActionDecision(
                intent="Approach an unfamiliar visible object.",
                action="move_to",
                target_id=interesting["id"],
                duration_seconds=5,
                interrupt_if=["danger_detected", "target_unreachable"],
                reason="The object may reveal an affordance or resource.",
            )

        directions = ["north", "east", "south", "west", "northeast", "southwest", "southeast", "northwest"]
        direction = directions[(self.decision_count + int(perception.get("day", 1))) % len(directions)]
        return ActionDecision(
            intent="Continue learning the shape of the unfamiliar environment.",
            action="move",
            direction=direction,
            duration_seconds=3.5,
            interrupt_if=["danger_detected", "target_unreachable", "energy_critical"],
            reason="No urgent need dominates, so cautious exploration is useful.",
        )

    @staticmethod
    def _nearest_local_tile(perception: dict, terrain_types: set[str]) -> dict | None:
        candidates = [tile for tile in perception.get("local_tiles", []) if tile["terrain"] in terrain_types]
        return min(candidates, key=lambda tile: abs(tile["x"]) + abs(tile["y"])) if candidates else None

    @staticmethod
    def _move_toward_local(tile: dict, intent: str) -> ActionDecision:
        dx, dy = tile["x"], tile["y"]
        vertical = "north" if dy < 0 else "south"
        horizontal = "west" if dx < 0 else "east"
        if abs(dx) < 2:
            direction = vertical
        elif abs(dy) < 2:
            direction = horizontal
        else:
            direction = vertical + horizontal
        return ActionDecision(
            intent=intent,
            action="move",
            direction=direction,
            duration_seconds=max(2, min(6, (abs(dx) + abs(dy)) / 2)),
            interrupt_if=["danger_detected", "target_unreachable"],
            reason="A relevant terrain feature is visible in that direction.",
        )

    def consolidate(self, context: dict) -> ConsolidationResult:
        events = context.get("events", [])[-12:]
        event_text = "; ".join(event.get("message", "") for event in events if event.get("message"))
        if not event_text:
            event_text = "The period passed without a major recorded event."
        day = context.get("day", 1)
        memory = MemoryWrite(
            category="daily",
            title=f"Day {day} consolidation",
            content=f"During this waking period: {event_text}",
            importance=0.55,
            tags=["daily", f"day-{day}"],
        )
        return ConsolidationResult(
            summary=memory.content,
            memories=[memory],
            belief_updates={},
            next_intention="Reassess bodily needs and nearby changes after waking.",
        )
