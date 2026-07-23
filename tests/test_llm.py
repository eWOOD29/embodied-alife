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
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["schema"]["type"] == "object"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 40}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(data_dir=tmp_path, no_llm=False, llm_model="mock-model")
    result = await LocalLLMClient(settings, client).decide(context())
    await client.aclose()
    assert result.source == "llm"
    assert result.value.action == "look"
    assert result.prompt_tokens == 100


@pytest.mark.asyncio
async def test_native_catalog_filters_loaded_models_and_repairs_stale_selection(tmp_path) -> None:
    models = [
        {
            "id": "qwen/qwen3-14b",
            "display_name": "Qwen3 14B",
            "type": "llm",
            "state": "loaded",
            "publisher": "qwen",
            "quantization": "Q4_K_M",
            "max_context_length": 32768,
        }
    ] + [
        {
            "id": f"saved/model-{index}",
            "display_name": f"Saved model {index}",
            "type": "llm",
            "state": "not-loaded",
        }
        for index in range(6)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/models"
        return httpx.Response(200, json={"object": "list", "data": models})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(data_dir=tmp_path, no_llm=False, llm_model="qwen/ qwen3-14b")
    brain = LocalLLMClient(settings, client)
    catalog = await brain.discover_model_catalog()
    status = await brain.check_status()
    await client.aclose()

    assert len(catalog["models"]) == 7
    assert [item["id"] for item in catalog["models"] if item["state"] == "loaded"] == ["qwen/qwen3-14b"]
    assert brain.settings.llm_model == "qwen/qwen3-14b"
    assert status["mode"] == "llm"
    assert status["available"] is True


@pytest.mark.asyncio
async def test_lm_studio_error_body_is_preserved(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Model not found: bad/model"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(data_dir=tmp_path, no_llm=False, llm_model="bad/model")
    result = await LocalLLMClient(settings, client).decide(context())
    await client.aclose()

    assert result.source == "fallback"
    assert "Model not found: bad/model" in (result.error or "")


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
