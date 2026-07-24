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


actions = read("app/simulation/actions.py")
actions = replace_once(
    actions,
    '''    def _complete(self, execution: ActionExecution, world: WorldState, agent: AgentState) -> ActionResult:
        action, target_id = execution.action, execution.target_id
        agent_x = _finite_number(agent.x, 0.0) or 0.0
        agent_y = _finite_number(agent.y, 0.0) or 0.0
''',
    '''    def _complete(self, execution: ActionExecution, world: WorldState, agent: AgentState) -> ActionResult:
        action, target_id = execution.action, execution.target_id
        agent_x = _finite_number(getattr(agent, "x", None))
        agent_y = _finite_number(getattr(agent, "y", None))
        if action not in VIEW_ACTIONS | {"wait", "rest", "speak"} and (agent_x is None or agent_y is None):
            return ActionResult(False, action, "position_unknown", "The body's position became invalid; location-dependent completion is unknown.")
        safe_agent_x = agent_x if agent_x is not None else 0.0
        safe_agent_y = agent_y if agent_y is not None else 0.0
''',
    "complete position normalization",
)
actions = replace_once(
    actions,
    '''        if action in {"move", "move_to", "flee"}:
            return ActionResult(True, action, "completed", "The body reached the destination.", {"position": [round(_finite_number(agent.x, 0.0) or 0.0, 2), round(_finite_number(agent.y, 0.0) or 0.0, 2)]})
''',
    '''        if action in {"move", "move_to", "flee"}:
            return ActionResult(True, action, "completed", "The body reached the destination.", {"position": [round(safe_agent_x, 2), round(safe_agent_y, 2)]})
''',
    "complete movement position",
)
actions = replace_once(
    actions,
    '''        if action == "pick_up":
            resource = world.resources.get(target_id or "")
            if not resource or resource.quantity <= 0 or math.hypot(resource.x - safe_agent_x, resource.y - safe_agent_y) > INTERACTION_RADIUS:
                return ActionResult(False, action, "target_changed", "The resource is no longer available within reach.")
            item_kind = "berry" if resource.kind == "berry_bush" else resource.kind
''',
    '''        if action == "pick_up":
            resources = world.resources if isinstance(getattr(world, "resources", None), dict) else {}
            resource = resources.get(target_id or "")
            quantity = _finite_number(getattr(resource, "quantity", None)) if resource is not None else None
            resource_x = _finite_number(getattr(resource, "x", None)) if resource is not None else None
            resource_y = _finite_number(getattr(resource, "y", None)) if resource is not None else None
            if resource is None or quantity is None or quantity <= 0 or resource_x is None or resource_y is None or math.hypot(resource_x - safe_agent_x, resource_y - safe_agent_y) > INTERACTION_RADIUS:
                return ActionResult(False, action, "target_changed", "The resource is no longer available within reach.")
            item_kind = "berry" if getattr(resource, "kind", "") == "berry_bush" else _bounded_text(getattr(resource, "kind", ""), 80)
            if not item_kind:
                return ActionResult(False, action, "target_changed", "The resource kind is no longer valid.")
''',
    "complete pickup normalization",
)
actions = replace_once(
    actions,
    '''            resource.quantity -= 1
            resource.last_harvest_time = world.sim_time
''',
    '''            resource.quantity = quantity - 1
            resource.last_harvest_time = _finite_number(getattr(world, "sim_time", None), 0.0) or 0.0
''',
    "complete pickup mutation",
)
actions = replace_once(
    actions,
    '''            agent.hunger = max(0.0, agent.hunger - nutrition)
            agent.energy = min(100.0, agent.energy + energy)
''',
    '''            hunger = _finite_number(getattr(agent, "hunger", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            current_energy = _finite_number(getattr(agent, "energy", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.hunger = max(0.0, hunger - nutrition)
            agent.energy = min(100.0, current_energy + energy)
''',
    "complete eat needs",
)
actions = replace_once(
    actions,
    '''            agent.hydration = min(100.0, agent.hydration + 42.0)
''',
    '''            hydration = _finite_number(getattr(agent, "hydration", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.hydration = min(100.0, hydration + 42.0)
''',
    "complete drink hydration",
)
actions = replace_once(
    actions,
    '''            agent.energy = min(100.0, agent.energy + 5.0)
''',
    '''            current_energy = _finite_number(getattr(agent, "energy", None), 0.0, minimum=0.0, maximum=100.0) or 0.0
            agent.energy = min(100.0, current_energy + 5.0)
''',
    "complete rest energy",
)
actions = replace_once(
    actions,
    '''            if agent.inventory.get("branch", 0) < 3 or agent.inventory.get("stone", 0) < 2:
                return ActionResult(False, action, "materials_changed", "Required materials were no longer available.")
''',
    '''            inventory = agent.inventory if isinstance(getattr(agent, "inventory", None), dict) else {}
            branches = _finite_number(inventory.get("branch"), None, minimum=0.0, maximum=1_000_000.0)
            stones = _finite_number(inventory.get("stone"), None, minimum=0.0, maximum=1_000_000.0)
            if branches is None or stones is None or branches < 3 or stones < 2:
                return ActionResult(False, action, "materials_changed", "Required materials were no longer available.")
''',
    "complete build inventory",
)
actions = replace_once(
    actions,
    '''            shelter_id = f"shelter_{len(world.shelters) + 1:02d}"
''',
    '''            shelters = world.shelters if isinstance(getattr(world, "shelters", None), dict) else {}
            shelter_id = f"shelter_{len(shelters) + 1:02d}"
''',
    "complete shelter mapping",
)
actions = replace_once(
    actions,
    '''            world.shelters[shelter_id] = shelter
            agent.known_locations[shelter_id] = {"x": shelter.x, "y": shelter.y, "certainty": 1.0, "last_seen": world.sim_time}
''',
    '''            shelters[shelter_id] = shelter
            if isinstance(getattr(agent, "known_locations", None), dict):
                agent.known_locations[shelter_id] = {"x": shelter.x, "y": shelter.y, "certainty": 1.0, "last_seen": _finite_number(getattr(world, "sim_time", None), 0.0) or 0.0}
''',
    "complete shelter mutation",
)
write("app/simulation/actions.py", actions)
print("post5 phase3 applied")
