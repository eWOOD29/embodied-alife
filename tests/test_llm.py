from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.llm.client import LocalLLMClient
from app.llm.fallback import FallbackBrain
from app.simulation.agent import AgentState
from app.simulation.perception import build_perception
from app.simulation.world import WorldState


def context() -> dict:
    world = WorldState.generate(55, 40)
    agent = AgentState(x=world.spawn[0], y=world.spawn[1])
    return {"perception": build_perception(world, agent), "active_plan": [], "retrieved_memories": [], "recent_outcomes": []}


@pytest.mark.asyncio
async def test_malformed_llm_output_falls_back(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(data_dir=tmp_path, no_llm=False, llm_model="mock-model")
    brain = LocalLLMClient(settings, client)
    result = await brain.decide(context())
    await client.aclose()
    assert result.source == "fallback"
    assert result.error
    assert result.value.action in {"move", "move_to", "look", "inspect", "pick_up", "drop", "eat", "drink", "sleep", "rest", "build", "speak", "flee", "wait"}


@pytest.mark.asyncio
async def test_mock_openai_compatible_response_is_validated(tmp_path) -> None:
    content = {
        "intent": "survey the area",
        "action": "look",
        "target_id": None,
        "direction": None,
        "duration_seconds": 1,
        "interrupt_if": [],
        "reason": "I need current local information.",
        "memory_write": None,
    }
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 40}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(data_dir=tmp_path, no_llm=False, llm_model="mock-model")
    result = await LocalLLMClient(settings, client).decide(context())
    await client.aclose()
    assert result.source == "llm"
    assert result.value.action == "look"
    assert result.prompt_tokens == 100


def test_fallback_prioritizes_hydration_and_danger() -> None:
    world = WorldState.generate(66, 40)
    water = next((x, y) for y in range(world.size) for x in range(world.size) if world.is_water(x, y))
    agent = AgentState(x=water[0], y=water[1], hydration=10)
    perception = build_perception(world, agent)
    brain = FallbackBrain()
    decision = brain.decide(perception)
    assert decision.action in {"move", "move_to", "drink"}
    assert "water" in decision.intent.lower() or "thirst" in decision.intent.lower()

    wolf = world.npcs["wolf_01"]
    wolf.x, wolf.y = agent.x + 1, agent.y
    danger_decision = brain.decide(build_perception(world, agent))
    assert danger_decision.action == "flee"
