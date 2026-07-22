from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.updater.manager import UpdateError
from app.version import __version__

router = APIRouter()


class ControlRequest(BaseModel):
    action: Literal["pause", "resume", "speed", "reset", "save", "load", "fork", "decide"]
    speed: int | None = None
    seed: int | None = None
    name: str | None = Field(default=None, max_length=80)
    new_name: str | None = Field(default=None, max_length=80)


class InstallUpdateRequest(BaseModel):
    version: str | None = Field(default=None, max_length=40)


class LLMDiscoveryRequest(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:1234/v1", max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LLMSettingsRequest(BaseModel):
    enabled: bool = True
    base_url: str = Field(default="http://127.0.0.1:1234/v1", max_length=500)
    model: str = Field(default="", max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=900, ge=32, le=32768)
    timeout_seconds: float = Field(default=60.0, ge=5.0, le=600.0)
    context_length: int = Field(default=16384, ge=1024, le=262144)


def _engine(request: Request):
    return request.app.state.engine


def _updater(request: Request):
    return request.app.state.updater


@router.get("/health")
def health(request: Request) -> dict:
    engine = _engine(request)
    return {
        "status": "ok",
        "app": "embodied-alife",
        "version": __version__,
        "paused": engine.paused,
        "alive": engine.agent.alive,
        "seed": engine.world.seed,
        "sim_time": round(engine.world.sim_time, 2),
        "model_mode": engine.brain.status.get("mode"),
        "update_state": _updater(request).status.state,
    }


@router.get("/api/state")
def state(request: Request) -> dict:
    return _engine(request).observer_state()


@router.get("/api/world")
def world(request: Request) -> dict:
    return _engine(request).observer_state(include_map=True)


@router.get("/api/snapshots")
def snapshots(request: Request) -> list[dict]:
    return _engine(request).snapshots.list()


@router.get("/api/memories")
def memories(request: Request) -> list[dict]:
    return [record.to_dict() for record in _engine(request).vault.list_records()]


@router.get("/api/llm/settings")
def llm_settings(request: Request) -> dict:
    return _engine(request).brain.public_configuration()


@router.post("/api/llm/models")
async def llm_models(payload: LLMDiscoveryRequest, request: Request) -> dict:
    brain = _engine(request).brain
    try:
        models = await brain.discover_models(base_url=payload.base_url, api_key=payload.api_key)
        return {"models": models, "base_url": payload.base_url.rstrip("/")}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not read models from the local server: {exc}") from exc


@router.put("/api/llm/settings")
async def save_llm_settings(
    payload: LLMSettingsRequest,
    request: Request,
    x_embodied_alife_settings: str | None = Header(default=None),
) -> dict:
    if x_embodied_alife_settings != "confirm":
        raise HTTPException(status_code=403, detail="missing settings confirmation header")
    brain = _engine(request).brain
    try:
        return await brain.configure(
            enabled=payload.enabled,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            timeout_seconds=payload.timeout_seconds,
            context_length=payload.context_length,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/update/status")
def update_status(request: Request) -> dict:
    return _updater(request).public_status()


@router.post("/api/update/check")
async def check_update(request: Request) -> dict:
    return await _updater(request).check()


@router.post("/api/update/install")
async def install_update(
    payload: InstallUpdateRequest,
    request: Request,
    x_embodied_alife_update: str | None = Header(default=None),
) -> dict:
    if x_embodied_alife_update != "confirm":
        raise HTTPException(status_code=403, detail="missing update confirmation header")
    shutdown_callback = getattr(request.app.state, "shutdown_callback", None)
    try:
        return await _updater(request).install(
            expected_version=payload.version,
            shutdown_callback=shutdown_callback,
        )
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/control")
async def control(payload: ControlRequest, request: Request) -> dict:
    engine = _engine(request)
    try:
        if payload.action == "pause":
            return engine.set_paused(True)
        if payload.action == "resume":
            return engine.set_paused(False)
        if payload.action == "speed":
            if payload.speed is None:
                raise ValueError("speed is required")
            return engine.set_speed(payload.speed)
        if payload.action == "reset":
            return engine.reset(payload.seed)
        if payload.action == "save":
            return engine.save_snapshot(payload.name or f"snapshot-{int(engine.world.sim_time)}")
        if payload.action == "load":
            if not payload.name:
                raise ValueError("snapshot name is required")
            return engine.load_snapshot(payload.name)
        if payload.action == "fork":
            if not payload.name or not payload.new_name:
                raise ValueError("source name and new_name are required")
            return engine.fork_snapshot(payload.name, payload.new_name)
        if payload.action == "decide":
            await engine.make_decision()
            return {"ok": True, "decision": engine.last_decision}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"snapshot not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="unsupported control action")
