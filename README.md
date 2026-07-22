# Embodied Artificial Life

A local, inspectable artificial-life experiment in which one persistent language-model agent has a body, partial perception, internal needs, durable memories, and a deterministic wilderness that decides what actually happens.

The application runs without a model through a deterministic fallback brain and can optionally use any OpenAI-compatible local server such as LM Studio. Version 0.2 adds Tailscale-ready binding and verified, one-click updates from GitHub Releases.

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
- Sandboxed Markdown memory vault with retrieval and sleep consolidation.
- SQLite state, events, model responses, action results, memories, snapshots, loading, reset, and snapshot forking.
- FastAPI/WebSocket dashboard with observer truth, agent perception, beliefs, decisions, outcomes, needs, NPCs, resources, and controls.
- GitHub Release updater with automatic checks, dashboard notification, SHA-256 verification, safe extraction, rollback, dependency synchronization, and restart.

## Install directly from GitHub

After the repository has at least one published release, open PowerShell and run:

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

For a private repository, download `install-windows.ps1` while signed in and run it with a read-only fine-grained token:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\install-windows.ps1 `
  -GitHubToken "<read-only token>"
```

The installer downloads the latest `embodied-alife-update.zip` release asset, verifies its SHA-256 digest, copies only package-managed files, creates a project-local `.venv`, installs dependencies with `uv`, preserves an existing `.env` and `data/`, validates the package, and launches it.

Manual ZIP/Git Bash installation remains documented in [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md).

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

Use `app.serve`, `start-embodied-alife.bat`, or AppDock rather than invoking `uvicorn app.main:app` directly. The managed launcher provides the graceful shutdown hook required by one-click updates.

## Automatic updates

The updater checks GitHub Releases shortly after startup and then every six hours by default. The dashboard displays:

- installed and latest versions
- release notes
- update-check errors
- a **Download and install** button when a newer stable release exists
- install/restart progress

The updater only accepts the repository and fixed asset name configured in `.env`. It does not accept arbitrary URLs from the browser.

Before installing, it:

1. reads the latest published GitHub release
2. locates `embodied-alife-update.zip`
3. verifies GitHub's SHA-256 asset digest or `embodied-alife-update.zip.sha256`
4. rejects path traversal, symbolic links, oversized archives, protected paths, malformed manifests, and version mismatches
5. extracts into `data/runtime/updates/`
6. launches a separate updater process
7. gracefully stops the server
8. backs up managed files under `data/runtime/update-backups/`
9. replaces package-managed files only
10. runs `uv pip install` against the existing project `.venv`
11. rolls back files if installation or dependency synchronization fails
12. restarts `python -m app.serve`

These paths are always preserved:

```text
.env
.venv/
data/
.git/
```

Update logs and state are stored in:

```text
data/runtime/update-worker.log
data/runtime/update-state.json
data/runtime/installed-update-manifest.json
data/runtime/update-backups/
data/runtime/updates/
```

### Publishing an update

1. Increase the version in both `pyproject.toml` and `app/version.py`.
2. Commit and push the change.
3. Tag that exact version and push the tag:

```bash
git tag v0.2.0
git push origin main
git push origin v0.2.0
```

`.github/workflows/release.yml` runs tests, validates the tag/version match, builds the update ZIP and checksum, and publishes a GitHub Release. The updater only sees published releases, not ordinary commits or tags without releases.

Build the same release assets locally with:

```bash
.venv/Scripts/python.exe scripts/build_release.py
```

## Configuration

Copy `.env.example` to `.env`.

| Variable | Default | Purpose |
|---|---:|---|
| `HOST` | `0.0.0.0` | Listen on all interfaces, including Tailscale |
| `PORT` | `8797` | Application port |
| `DATA_DIR` | `data` | Runtime database and memory root |
| `WORLD_SEED` | `20260722` | Initial deterministic seed |
| `WORLD_SIZE` | `128` | Logical map width/height |
| `SIM_TICK_SECONDS` | `0.2` | Real loop interval |
| `SIM_START_PAUSED` | `false` | Initial pause state |
| `SIM_SPEED` | `1` | Initial 1×, 10×, or 100× speed |
| `NO_LLM` | `false` | Force deterministic fallback mode |
| `LLM_BASE_URL` | `http://127.0.0.1:1234/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | `***` | Local-server bearer placeholder |
| `LLM_MODEL` | empty | Exact server model ID; empty means fallback |
| `LLM_CONTEXT_LENGTH` | `16384` | Documented operating target |
| `LLM_TIMEOUT_SECONDS` | `60` | Model timeout |
| `UPDATE_ENABLED` | `true` | Enable checks and installation |
| `UPDATE_REPOSITORY` | `eWOOD29/embodied-alife` | Fixed GitHub repository |
| `UPDATE_CHANNEL` | `stable` | `stable` or `prerelease` |
| `UPDATE_ASSET_NAME` | `embodied-alife-update.zip` | Fixed release package name |
| `UPDATE_CHECK_ON_STARTUP` | `true` | Start the periodic checker |
| `UPDATE_CHECK_INTERVAL_HOURS` | `6` | Check cadence; minimum one hour |
| `UPDATE_AUTO_RESTART` | `true` | Restart after successful installation |
| `UPDATE_GITHUB_TOKEN` | empty | Optional read-only token for a private repo |

Do not commit `.env` or a GitHub token. Public repositories require no token for release checks or asset downloads.

## LM Studio

A practical initial model for 16 GB VRAM is **Qwen3-14B Q4_K_M or an equivalent strong Q4 quant** at **16,384 context**.

1. Load the model in LM Studio.
2. Set context to 16,384.
3. Start its OpenAI-compatible server on `127.0.0.1:1234`.
4. Query the exact model ID:

```bash
curl http://127.0.0.1:1234/v1/models
```

5. Set `LLM_MODEL` in `.env`, leave `NO_LLM=false`, and restart.

The dashboard explicitly reports LLM, fallback, timeout, malformed-response, and API-error states.

## Tailscale access

Because `HOST=0.0.0.0` also listens on LAN interfaces, apply the restricted Windows Firewall rules from an Administrator PowerShell:

```powershell
cd C:\Users\ethan\workspace\local-apps\embodied-alife
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\enable-tailscale-access.ps1
```

Find the desktop's Tailscale IP:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
```

Open from another authorized tailnet device:

```text
http://<desktop-tailscale-ip>:8797/
```

Remove the firewall rules with:

```powershell
.\scripts\disable-tailscale-access.ps1
```

Do not create a router port-forward for port 8797. The dashboard has no independent login, so restrict Tailscale access to trusted identities/devices.

## Fallback mode

Set:

```text
NO_LLM=true
```

or leave `LLM_MODEL` empty. The deterministic brain prioritizes danger, critical hydration, hunger, sleep, shelter, gathering, and exploration. The dashboard labels it `fallback`.

## Persistence and memory

SQLite database:

```text
data/runtime/embodied_alife.db
```

Project-local Markdown vault:

```text
data/agent_memory/
  memories/
  beliefs/
  locations/
  entities/
  projects/
  reflections/
  daily/
```

The application never writes to a personal Obsidian vault.

## API

- `GET /` — dashboard
- `GET /health` — health and version
- `GET /api/state` — live state without the full tile map
- `GET /api/world` — full observer state
- `GET /api/memories` — memory index
- `GET /api/snapshots` — snapshots
- `POST /api/control` — simulation controls
- `GET /api/update/status` — updater status
- `POST /api/update/check` — immediate release check
- `POST /api/update/install` — verified staged installation; requires the dashboard confirmation header
- `WS /ws` — live observer updates
- `GET /docs` — FastAPI API documentation

## Tests

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/smoke_simulation.py
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py
.venv/Scripts/ruff.exe check app tests scripts
```

Tests cover the deterministic world, needs, actions, memory, snapshots, SQLite retries, API/WebSocket behavior, model fallback, update discovery, mocked GitHub assets, checksum verification, archive traversal rejection, protected-state preservation, update rollback, and update API confirmation.

## AppDock

`appdock.json` launches:

```text
.venv\Scripts\python.exe -m app.serve
```

It uses port 8797, `http://127.0.0.1:8797/health`, manual start, and no automatic startup. AppDock discovery and process behavior must be verified on the Windows machine.

## Current limitations

- One LLM-controlled agent; NPCs are deterministic.
- Grid movement and simple line-of-sight rather than physical simulation.
- No separate vision model, extensive crafting tree, society, or learned motor policy.
- Memory retrieval is lexical rather than vector-based.
- Updater trust is based on GitHub repository control plus SHA-256 release-asset integrity; package signing with a separately pinned public key is future work.
- A failed dependency update can roll back project files, but a dependency tool may already have modified the virtual environment before failure. The backup and log make manual recovery possible.
- One-click install requires the managed `app.serve` launcher; a raw `uvicorn app.main:app` process cannot request graceful shutdown.

See [`SANDBOX_VERIFICATION.md`](SANDBOX_VERIFICATION.md) for exactly what was tested here and what remains to verify on Windows.
