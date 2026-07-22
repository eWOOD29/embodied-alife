# Embodied Artificial Life

A local, inspectable artificial-life experiment in which one persistent language-model agent has a body, partial perception, internal needs, durable memories, and a deterministic wilderness that decides what actually happens.

The application runs without a model through a deterministic fallback brain and can optionally use any OpenAI-compatible local server such as LM Studio. It includes persistent state, a live observer dashboard, in-app local-model selection, tailnet-only remote access through Tailscale Serve, and verified one-click updates from GitHub Releases.

## Documentation

Start here when continuing development or diagnosing a real installation:

- [`docs/PROJECT_HANDOFF.md`](docs/PROJECT_HANDOFF.md) — canonical architecture, current state, history, lessons, risks, and continuation workflow
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — prioritized feature and research roadmap
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — Windows, LM Studio, Tailscale, updater, CI, recovery, and backup procedures
- [`docs/NEW_SESSION_PROMPT.md`](docs/NEW_SESSION_PROMPT.md) — copy-paste prompt for resuming the project in a new ChatGPT session
- [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md) — current Windows installation and operations guide
- [`CHANGELOG.md`](CHANGELOG.md) — release history

## Architecture

```text
deterministic world engine
        ↓
deterministic body/controller
        ↓
local LLM brain (optional)
```

The LLM interprets observations, proposes a plan and one structured action, updates beliefs, and may request a memory write. It cannot move the body directly, alter SQLite, access host files, execute code, or declare success. The controller checks pathfinding, reachability, inventory, materials, legal terrain, action duration, and interruptions. The world engine applies consequences and returns an explicit result.

## Implemented vertical slice

- Seeded 128×128 wilderness: meadow, forests, water, rocks, cave entrance, and building clearing.
- Deterministic day/night, temperature, rain/storms, resource regeneration, passive wildlife, and a dangerous wolf.
- Ari has health, energy, hunger, hydration, temperature, sleep pressure, pain, inventory, beliefs, plans, explored terrain, and memories.
- Limited-radius line-of-sight perception remains separate from the observer's complete map.
- Deterministic A* movement, collisions, reachability, action durations, and interruptions.
- Gathering, eating, drinking, sleeping, resting, exploring, inspecting, dropping, fleeing, speaking, and shelter building.
- OpenAI-compatible `/v1/chat/completions` adapter with schema validation, retry, timeout handling, usage/latency reporting, and explicit fallback.
- Dashboard-based model discovery and live settings for LM Studio or another OpenAI-compatible local server.
- Sandboxed Markdown memory vault with retrieval and sleep consolidation.
- SQLite state, events, model responses, action results, memories, snapshots, loading, reset, and snapshot forking.
- FastAPI/WebSocket dashboard with observer truth, agent perception, beliefs, decisions, outcomes, needs, NPCs, resources, controls, model settings, and update status.
- GitHub Release updater with automatic checks, dashboard notification, SHA-256 verification, safe extraction, rollback, dependency synchronization, coordinated WebSocket shutdown, and restart.

## Install directly from GitHub

Open PowerShell:

```powershell
$installer = "$env:TEMP\install-embodied-alife.ps1"
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/eWOOD29/embodied-alife/main/install-windows.ps1" `
  -OutFile $installer
PowerShell -ExecutionPolicy Bypass -File $installer
```

The default installation location is:

```text
C:\Users\ethan\workspace\local-apps\embodied-alife
```

The installer downloads the latest custom release asset, verifies its SHA-256 digest, copies only package-managed files, creates or reuses a project-local `.venv`, installs dependencies, preserves existing `.env` and `data/`, validates the package, and launches it.

For a private repository, see [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md).

## Run

```bash
cd /c/Users/ethan/workspace/local-apps/embodied-alife
unset PYTHONPATH
.venv/Scripts/python.exe -m app.serve
```

Local URL:

```text
http://127.0.0.1:8797/
```

Health endpoint:

```text
http://127.0.0.1:8797/health
```

Use `app.serve`, `start-embodied-alife.bat`, or a compatible process manager rather than invoking raw Uvicorn. The managed launcher provides the graceful shutdown hook required by one-click updates.

## Local LLM through LM Studio

1. Load a model in LM Studio.
2. Start LM Studio's OpenAI-compatible server at `http://127.0.0.1:1234/v1`.
3. Open the dashboard's **Local LLM brain** panel.
4. Click **Discover models**.
5. Select the exact returned model ID.
6. Click **Save and apply**.

Model changes do not require editing `.env` or restarting the app. Runtime LLM settings persist under `data/runtime/llm-settings.json` and survive application updates.

## Tailnet-only remote access

The currently proven setup is Tailscale Serve proxying the localhost application:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
tailscale serve status
```

Do not use public port forwarding or Tailscale Funnel. The app currently has no independent authentication. See [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md) and [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for details.

## Automatic updates

The updater checks GitHub Releases shortly after startup and then periodically. The dashboard displays installed/latest versions, release notes, errors, and an install button when a newer stable release exists.

Before installing, it:

1. reads the latest published GitHub release
2. locates `embodied-alife-update.zip`
3. verifies GitHub's SHA-256 asset digest or `embodied-alife-update.zip.sha256`
4. rejects path traversal, symbolic links, oversized archives, protected paths, malformed manifests, and version mismatches
5. extracts into `data/runtime/updates/`
6. launches a separate updater process
7. closes the dashboard WebSocket and gracefully stops the server
8. backs up managed files under `data/runtime/update-backups/`
9. replaces package-managed files only
10. synchronizes dependencies against the existing project `.venv`
11. rolls back files if installation or dependency synchronization fails
12. restarts `python -m app.serve`

These paths are always preserved:

```text
.env
.venv/
data/
.git/
```

Update logs and state are stored under `data/runtime/`.

## Development and releases

Run the local checks from the project root:

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py --output dist/embodied-alife-update.zip
.venv/Scripts/ruff.exe check app tests scripts
```

Normal releases are automatic. When a coherent release is ready, update matching versions in:

```text
pyproject.toml
app/version.py
```

The release workflow tests, validates, builds, tags, and publishes the custom ZIP and checksum. Documentation-only commits should not bump the application version.
