# Architecture

## Design goal

Embodied Artificial Life explores whether a language-model agent can accumulate useful behavior while remaining physically constrained by a deterministic simulation.

The central invariant is:

```text
LLM proposes; controller validates; world decides.
```

The LLM receives only Ari's permitted perception, body state, retrieved memories, current plan, and recent authoritative outcomes. It never receives unrestricted host access or direct mutation capabilities.

## Runtime layers

### World engine

`app/simulation/world.py`, `needs.py`, `npcs.py`, and the scheduler implement seeded terrain, resources, weather, time, physiology, regeneration, wildlife, and persistent simulation progression.

### Body and action controller

`app/simulation/actions.py` and `body.py` validate and execute structured actions. They own reachability, pathfinding, interaction distance, inventory constraints, materials, legal terrain, duration, interruption, and authoritative outcomes.

### Cognition layer

`app/llm/` builds compact prompts, calls an optional OpenAI-compatible model server, validates structured responses with Pydantic, records provider metadata, and falls back deterministically when generation fails.

A production decision may contain:

- one immediate intent;
- one structured action;
- a short conditional plan;
- evidence-backed belief updates;
- an optional durable-memory candidate.

Invalid or stale action proposals can be corrected at the deterministic boundary before execution. Corrections are recorded as events and do not create beliefs or memories.

### Memory

`app/memory/` stores validated Markdown memories separately from raw event history. A model-proposed memory is only a candidate until the associated action reaches an authoritative successful outcome. Resetting the seed starts a clean experiment with isolated world-specific memory and history.

### Persistence

`app/storage/` stores runtime state, events, model responses, memories, metadata, and snapshots in local application data. Package updates preserve `.env`, `.venv/`, `data/`, and `.git/`.

### Web application

`app/web/` exposes the observer dashboard, REST endpoints, WebSocket state updates, local-model configuration, diagnostics, validation readiness, snapshots, and updater controls.

### Updates

The updater reads stable GitHub Releases, verifies the custom update asset and checksum, rejects unsafe archives and protected paths, stages files, coordinates graceful shutdown, creates backups, applies managed files, synchronizes dependencies, and rolls back on failure.

## Observer truth versus agent perception

The dashboard may display the complete map and hidden world state for research and debugging. Ari's prompt must contain only information available through the perception builder and explicitly permitted cognitive state. Tests and reviews should treat accidental observer-truth leakage as a serious defect.

## Public repository boundary

The repository contains portable source code and public documentation only. Do not commit:

- personal usernames or absolute home-directory paths;
- private Tailscale hostnames or IP addresses;
- API keys, tokens, or `.env` contents;
- runtime databases, memories, snapshots, or diagnostic bundles;
- machine-specific support history;
- internal assistant prompts or private project-management notes.

Use environment variables, placeholders, and generic examples in documentation and tests.
