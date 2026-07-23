# Embodied Artificial Life

A local, inspectable artificial-life experiment in which a language-model agent has a body, partial perception, internal needs, beliefs, plans, durable memories, and a deterministic wilderness that decides what actually happens.

The application works without an LLM through a deterministic fallback brain and can optionally use an OpenAI-compatible local server such as LM Studio. It includes persistent state, a live observer dashboard, local-model selection, verified in-app updates, snapshots, diagnostic exports, and multi-day validation tooling.

## Core architecture

```text
partial perception + body state + memories
                  ↓
       local LLM proposal (optional)
                  ↓
 deterministic controller validation
                  ↓
       authoritative world outcome
```

The LLM may propose one structured action, a short plan, belief updates, and a memory candidate. It cannot directly move the body, edit the world, access host files, mutate SQLite, execute code, or declare success. The deterministic controller checks target existence, reachability, inventory, terrain, materials, action duration, and interruptions before the world applies consequences.

## Features

- Seeded 128×128 wilderness with terrain, water, resources, shelters, wildlife, weather, temperature, and day/night cycles.
- Embodied agent state including health, energy, hunger, hydration, sleep pressure, body temperature, pain, inventory, beliefs, plans, explored terrain, and memories.
- Limited-radius line-of-sight perception separated from the observer's complete map.
- Deterministic pathfinding, movement, collisions, interaction ranges, action durations, and interruptions.
- Gathering, eating, drinking, sleeping, resting, exploring, inspecting, dropping, fleeing, speaking, and shelter construction.
- OpenAI-compatible local-LLM adapter with model discovery, schema validation, retries, timeout handling, usage metrics, and explicit fallback.
- Outcome-verified durable memories and clean experiment resets that isolate memories between generated worlds.
- SQLite persistence, snapshots, restart recovery, event history, and model-response history.
- FastAPI/WebSocket observer dashboard with complete world truth, agent perception, decisions, outcomes, beliefs, needs, resources, NPCs, controls, model settings, and updater status.
- Diagnostic JSON exports with runtime identity, model/action/memory metrics, anomaly checks, and soak-test readiness.
- GitHub Release updater with SHA-256 verification, protected paths, rollback, dependency synchronization, graceful shutdown, and restart.

## Documentation

- [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md) — public Windows installation and operation guide
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design invariants and repository structure
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — portable troubleshooting procedures
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — planned research and engineering work
- [`docs/SOAK_TEST.md`](docs/SOAK_TEST.md) — multi-day validation protocol
- [`CHANGELOG.md`](CHANGELOG.md) — release history

## Windows installation

Prerequisites:

- Windows 10 or 11
- [uv](https://docs.astral.sh/uv/) available on `PATH`
- Python 3.11, which `uv` can install automatically
- Optional: LM Studio or another OpenAI-compatible local model server

Open PowerShell:

```powershell
$installer = "$env:TEMP\install-embodied-alife.ps1"
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/eWOOD29/embodied-alife/main/install-windows.ps1" `
  -OutFile $installer
PowerShell -ExecutionPolicy Bypass -File $installer
```

The default installation directory is:

```text
%LOCALAPPDATA%\EmbodiedArtificialLife
```

Choose another directory with:

```powershell
PowerShell -ExecutionPolicy Bypass -File $installer `
  -InstallPath "D:\Apps\EmbodiedArtificialLife"
```

The installer downloads the latest custom release asset, verifies its SHA-256 digest, validates archive paths, copies only package-managed files, creates or reuses a project-local `.venv`, installs dependencies, preserves `.env` and `data/`, validates the package, and launches the application.

## Run

From PowerShell:

```powershell
$root = "$env:LOCALAPPDATA\EmbodiedArtificialLife"
Set-Location $root
& .\.venv\Scripts\python.exe -m app.serve
```

Or double-click `start-embodied-alife.bat`.

Default endpoints:

```text
Dashboard:       http://127.0.0.1:8797/
Health:          http://127.0.0.1:8797/health
Soak readiness: http://127.0.0.1:8797/api/validation/readiness
```

Use `app.serve`, the included batch launcher, or another process manager that supports graceful shutdown. Raw `uvicorn app.main:app` does not provide the coordinated shutdown hook required by the updater.

## Local LLM configuration

1. Load a model in LM Studio or another compatible server.
2. Start its OpenAI-compatible API, commonly at `http://127.0.0.1:1234/v1`.
3. Open the dashboard's **Local LLM brain** panel.
4. Click **Discover models**.
5. Select the exact loaded model ID.
6. Click **Save and apply**.

Runtime model settings are stored under `data/runtime/llm-settings.json` and survive application updates. API keys are excluded from diagnostic exports.

## Remote access

The application has no independent authentication. Do not expose it through public port forwarding or Tailscale Funnel.

For private tailnet access, Tailscale Serve can proxy the localhost application:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
tailscale serve status
```

Use the HTTPS hostname reported by `tailscale serve status`; hostnames are specific to each user's tailnet and should not be committed to the repository.

## Updates and persistent data

The updater checks the latest stable GitHub Release and displays a concise release summary in the dashboard. It verifies the release asset before installation and preserves:

```text
.env
.venv/
data/
.git/
```

Update state, backups, and worker logs live under `data/runtime/`.

## Development

Create a development environment from a source checkout:

```powershell
uv venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
Copy-Item .env.example .env
```

Run the checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe scripts\validate_package.py
.\.venv\Scripts\ruff.exe check app tests scripts
```

Normal releases are built by GitHub Actions after matching version changes in `pyproject.toml` and `app/version.py`. The release workflow tests, validates, builds, tags, and publishes the custom update ZIP and checksum.

## Security and privacy

This repository should contain no personal usernames, private hostnames, local absolute paths, API keys, `.env` contents, runtime databases, memories, diagnostic bundles, or device-specific logs. Use placeholders and environment-variable-based paths in documentation and examples.
