# Embodied Artificial Life — Project Handoff

_Last updated: 2026-07-22_  
_Current release: **v0.2.3**_  
_Repository: `eWOOD29/embodied-alife`_  
_Default branch: `main`_

This document is the canonical handoff for continuing the Embodied Artificial Life project in a new development or ChatGPT session. Read it before making architectural changes. Operational troubleshooting lives in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md), future work in [`ROADMAP.md`](ROADMAP.md), and a copy-paste session bootstrap in [`NEW_SESSION_PROMPT.md`](NEW_SESSION_PROMPT.md).

## 1. Project goal

Embodied Artificial Life is a local, inspectable artificial-life experiment centered on one persistent language-model agent, currently named **Ari**. Ari has a body, internal needs, partial perception, beliefs, plans, memories, and a persistent history. The environment, body, and action controller—not the language model—decide what actually happens.

The core research/product idea is:

```text
partial observation
       ↓
LLM proposes intent, plan, belief updates, and one structured action
       ↓
deterministic controller validates feasibility
       ↓
deterministic world applies consequences
       ↓
explicit outcome, memory, and future observation
```

The LLM is deliberately not an all-powerful game master. It cannot directly edit the world, database, files, or its own success state. It interprets what Ari can perceive and proposes actions through a constrained schema. This separation is the most important architectural invariant in the project.

## 2. Current working state

As of v0.2.3, the application is installed and working on the user's Windows desktop.

### Canonical local installation

```text
C:\Users\ethan\workspace\local-apps\embodied-alife
```

### Local application URL

```text
http://127.0.0.1:8797/
```

### Health endpoint

```text
http://127.0.0.1:8797/health
```

### Working Tailscale endpoint

```text
https://ethan-pc.tailce5cf1.ts.net:8797
```

The working remote-access pattern is **Tailscale Serve reverse-proxying the local application**, not direct access to `http://<tailscale-ip>:8797`.

Canonical Serve mapping:

```text
https://ethan-pc.tailce5cf1.ts.net:8797
└── proxy http://127.0.0.1:8797
```

Command used to create it:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
```

The endpoint has been confirmed working from the user's phone. It was not working from the user's laptop at the time of this handoff, despite both devices being on the same tailnet. Because the phone works, the unresolved laptop issue is probably client-specific—browser, DNS, certificate, local security software, or Tailscale client state—rather than an application server problem.

### Local model server

The user runs LM Studio's OpenAI-compatible server at its defaults:

```text
http://127.0.0.1:1234/v1
```

The user currently has a Qwen3-14B model loaded in LM Studio. The exact model ID should be discovered from LM Studio rather than guessed. v0.2.2 added an in-app model settings panel so model changes no longer require `.env` edits or an app restart.

## 3. Product principles and architectural invariants

Future development should preserve these principles unless the user explicitly decides to change them.

### 3.1 The world is authoritative

The language model may propose an action, but the deterministic simulation decides:

- whether the target exists
- whether it is visible or known
- whether Ari can reach it
- whether Ari has required items or materials
- how long the action takes
- whether it is interrupted
- what physical consequences occur
- whether the action succeeds

Do not let the LLM directly mutate world state.

### 3.2 The agent receives partial perception

The observer dashboard can show complete world truth, but Ari should receive only local line-of-sight perception, bodily state, retrieved memories, known locations, recent outcomes, and other explicitly permitted context.

Avoid accidentally leaking the observer's complete map or hidden NPC/resource state into LLM prompts.

### 3.3 Structured model output is mandatory

LLM decisions are validated against Pydantic schemas. Invalid text, malformed JSON, schema violations, timeouts, or HTTP failures fall back to the deterministic brain. The system retries once with a stricter repair instruction before falling back.

### 3.4 The app remains useful without an LLM

The deterministic fallback brain is not merely an error screen. It keeps the simulation functional when:

- LM Studio is stopped
- no model is loaded
- the selected model ID no longer exists
- the model returns invalid output
- the local model is too slow
- local LLM use is disabled

### 3.5 Local-first and inspectable

The project is designed to run locally with:

- a project-local Python virtual environment
- SQLite persistence
- a Markdown memory vault
- a local OpenAI-compatible model server
- a local web dashboard
- optional tailnet-only remote access

Avoid adding mandatory cloud dependencies unless the user explicitly asks for them.

### 3.6 Persistent user data must survive updates

The updater must preserve:

```text
.env
.venv/
data/
.git/
```

Runtime preferences that should survive package replacement belong under `data/`, not in package-managed source files.

## 4. Architecture and repository map

### Runtime entrypoints

- `app/serve.py` — managed Uvicorn launcher. This is the supported server entrypoint because it provides the graceful-shutdown callback required by the updater.
- `start-embodied-alife.bat` — Windows convenience launcher.
- `app/main.py` — FastAPI application factory and router/static mounting.

Do not recommend raw `uvicorn app.main:app` for normal use. It bypasses the updater's managed shutdown hook.

### Configuration

- `app/config.py` — loads `.env` and creates the `Settings` dataclass.
- `.env.example` — baseline server, simulation, LLM, and updater settings.
- Project `.env` is loaded with `override=True`, making it authoritative over stale inherited Windows environment variables such as `HOST=127.0.0.1`.

The `.env` remains the baseline/startup configuration, but runtime LLM choices now override its LLM fields through `data/runtime/llm-settings.json`.

### Simulation

- `app/simulation/scheduler.py` — simulation engine, async loop, persistence, decisions, subscriptions, snapshots, and observer state.
- `app/simulation/world.py` — deterministic seeded world generation and environmental state.
- `app/simulation/agent.py` — Ari's persistent body/cognitive state.
- `app/simulation/body.py` — action execution state.
- `app/simulation/actions.py` — deterministic action validation and execution.
- `app/simulation/perception.py` — constructs Ari's limited local perception.
- `app/simulation/needs.py` — bodily need changes and damage.
- `app/simulation/npcs.py` — NPC interactions.
- `app/simulation/events.py` — event representation.

Current implemented world features include a seeded 128×128 wilderness, terrain, water, resources, a cave entrance, a building clearing, weather, day/night, temperature, resource regeneration, passive wildlife, and a dangerous wolf.

Current implemented body/action features include health, energy, hunger, hydration, sleep pressure, temperature, pain, inventory, movement, pathfinding, gathering, eating, drinking, sleeping, resting, inspecting, dropping, fleeing, speaking, and shelter building.

### LLM brain

- `app/llm/client.py` — OpenAI-compatible client, model discovery, live configuration, status, retries, schema validation, and fallback handling.
- `app/llm/settings.py` — persistent runtime LLM settings store.
- `app/llm/prompts.py` — decision and consolidation prompts.
- `app/llm/schemas.py` — Pydantic output schemas.
- `app/llm/fallback.py` — deterministic fallback brain.

The current client calls:

```text
GET  <base_url>/models
POST <base_url>/chat/completions
```

The request asks for a non-streaming JSON object and includes the selected model, messages, temperature, and maximum output tokens.

Important nuance: `context_length` is currently stored in settings and displayed in the UI, but the application does not reconfigure LM Studio's loaded-model context window. LM Studio remains authoritative for the actual loaded context size. This field should eventually either be integrated with a supported server parameter/API or relabeled as an advisory value.

### Memory

- `app/memory/vault.py` — durable Markdown memory records and validation.
- `app/memory/retrieval.py` — memory retrieval.
- `app/memory/consolidation.py` — sleep/wake consolidation using either the LLM or fallback brain.

The memory system is intentionally separate from raw simulation history. Durable memories are validated before writing.

### Storage

- `app/storage/database.py` — SQLite database for runtime state, events, model responses, action results, memories, and metadata.
- `app/storage/snapshots.py` — named simulation snapshots and forks.

### Web UI and API

- `app/web/templates/index.html` — dashboard layout.
- `app/web/static/app.js` — dashboard rendering, controls, update flow, LLM settings, WebSocket lifecycle.
- `app/web/static/style.css` — dashboard styling.
- `app/web/routes.py` — REST API routes.
- `app/web/websocket.py` — live observer-state WebSocket.

Important API routes:

```text
GET  /health
GET  /api/state
GET  /api/world
GET  /api/snapshots
GET  /api/memories
POST /api/control

GET  /api/llm/settings
POST /api/llm/models
PUT  /api/llm/settings

GET  /api/update/status
POST /api/update/check
POST /api/update/install

WS   /ws
```

Mutating LLM settings and update installation require confirmation headers. This is not authentication; it only prevents casual or accidental cross-origin/form-style calls.

### Installer, package validation, and updater

- `install-windows.ps1` — installs the latest custom GitHub Release asset.
- `scripts/build_release.py` — builds `embodied-alife-update.zip` and its SHA-256 file.
- `scripts/validate_package.py` — validates source packages and installed packages with different rules.
- `app/updater/manager.py` — release discovery, download, checksum verification, staging, and worker launch.
- `app/updater/security.py` — archive inspection and safe extraction.
- `scripts/apply_update.py` — detached update worker, backup, managed-file replacement, dependency synchronization, rollback, and restart.
- `.github/workflows/tests.yml` — normal CI.
- `.github/workflows/release.yml` — automatic release workflow triggered by version-file changes on `main`.

## 5. Persistent files and state

The most important runtime paths are under `data/`.

```text
data/
├── runtime/
│   ├── embodied_alife.db
│   ├── llm-settings.json
│   ├── update-state.json
│   ├── update-worker.log
│   ├── installed-update-manifest.json
│   ├── updates/
│   └── update-backups/
└── agent_memory/
    └── ... durable Markdown memories ...
```

### `embodied_alife.db`

Contains the persistent simulation state and history. Do not delete it during normal upgrades or debugging unless the user explicitly wants a complete reset.

### `llm-settings.json`

Contains the current runtime model configuration selected in the UI. It overrides LLM-related `.env` values when the brain client starts.

The file may contain an API key in plaintext if the user enters one. LM Studio's default local server does not require a meaningful API key, so the user should leave the field blank. A future security improvement is Windows Credential Manager or DPAPI-backed secret storage.

### `update-worker.log`

First place to inspect after a failed or stalled in-app update.

### `update-state.json`

Persistent updater state shown after restart. It records errors, install state, current/latest version, and the last install result.

### `update-backups/`

Backups of managed files created immediately before each update. The updater rolls back managed files automatically on copy or dependency-sync failure.

## 6. LLM settings behavior

The **Local LLM brain** panel was added in v0.2.2.

It supports:

- enabling/disabling local LLM use
- changing the OpenAI-compatible base URL
- discovering loaded models from `/v1/models`
- selecting or manually typing a model ID
- temperature
- maximum output tokens
- timeout
- context-length metadata
- optional API key
- applying settings immediately without an app restart

If LM Studio reports exactly one loaded model and no model has been selected, the app automatically selects and persists it.

Status modes:

- `fallback` — disabled, unconfigured, unavailable, incompatible response, or request failure
- `configured` — server or model selection still needs attention
- `llm` — selected model is visible in `/models` and available

A successful `/models` check does not prove the model can produce valid action JSON. A future **Test model** button should send a small schema-constrained request and report latency, parsing success, and exact failure details.

## 7. Installation and update design

### Why custom release assets are required

GitHub's automatically generated source-code ZIP files are not the updater package. A valid release must contain:

```text
embodied-alife-update.zip
embodied-alife-update.zip.sha256
```

The custom ZIP includes an `update-manifest.json` that identifies the version, managed paths, protected roots, and entrypoint.

### Automatic release flow

As of v0.2.2, release publication is automated. Changing both:

```text
pyproject.toml
app/version.py
```

on `main` triggers `.github/workflows/release.yml`.

The workflow:

1. installs the project and development dependencies
2. verifies the two version declarations match
3. runs tests
4. compiles Python files
5. cleans generated caches/runtime files
6. validates the source package
7. builds the update ZIP and checksum
8. creates the version tag if needed
9. creates or updates the GitHub Release and uploads assets

Do not manually create tags for normal releases unless the workflow is unavailable. A version bump should be the final change after implementation and validation so the release points at the complete commit.

### Update installation flow

The running app:

1. checks the latest GitHub Release
2. finds the fixed package asset
3. downloads through GitHub's release asset API
4. verifies SHA-256
5. validates archive safety and the manifest
6. extracts into `data/runtime/updates/`
7. writes an install request
8. launches a detached update worker
9. closes live WebSockets and shuts down Uvicorn
10. waits for the old process to exit
11. backs up managed files
12. replaces managed files only
13. synchronizes dependencies into the existing `.venv`
14. writes installed state
15. restarts `python -m app.serve`

## 8. Version history and work completed

### v0.2.0 — first installable updater release

Major capabilities:

- custom Windows installer
- custom release package and checksum
- source/installed package validation
- GitHub Release update checking
- safe update staging, backup, rollback, and restart
- Tailscale-aware server configuration

Problems found during first installation:

- the package validator rejected `.pytest_cache`, `__pycache__`, and generated runtime database files
- installed validation then rejected the `.venv` the installer had just created
- installed validation still rejected ordinary runtime caches

Resolution: source and installed validation were separated. Source packages remain strict; installed validation permits normal runtime artifacts and ignores the virtual environment for secret scanning.

### v0.2.1 — update badge and binding fixes

Problems found:

- CSS `.pill { display: inline-block; }` overrode the element's HTML `hidden` attribute, making **Update available** appear even when the update API said the app was current
- one updater test hard-coded `0.2.0`
- inherited Windows environment variables could override the project `.env`
- the Tailscale helper wrote UTF-8 with a BOM, creating a potential `.env` parsing edge case

Resolution:

- global `[hidden] { display: none !important; }`
- tests compare to runtime `__version__`
- project `.env` loads with `override=True`
- PowerShell writes `.env` as UTF-8 without BOM

### v0.2.2 — live LM Studio configuration

Added:

- persistent LLM runtime settings
- model discovery through `/v1/models`
- live model switching
- in-app enable/disable control
- base URL, temperature, token, timeout, and context controls
- automatic selection when exactly one model is loaded
- automatic GitHub release publication from version bumps

### v0.2.3 — reliable updater shutdown handoff

Problem found:

- the update API returned `200 OK` and staged the package, but Uvicorn stayed at `Waiting for background tasks to complete`
- the open dashboard WebSocket was blocked on its queue and prevented shutdown
- the detached worker waited for the parent PID, so it never applied the update
- a browser surfaced a vague `The string did not match the requested pattern` message during the broken handoff

Resolution:

- browser closes the live socket before requesting installation
- reconnection is suppressed while updating
- WebSocket server polls a shutdown flag and closes with code 1012
- Uvicorn graceful shutdown has a five-second ceiling
- regression coverage was added for the shutdown handoff

The user manually re-ran the installer once to get from the broken old updater to v0.2.3. The app then launched successfully.

## 9. Lessons learned

These are important because several bugs looked like one problem but existed at different layers.

### 9.1 A listening socket is not the same as Tailscale Serve

`0.0.0.0:8797` means the application accepts connections on all local interfaces. It does not create a `tailscale serve` mapping. The user's other local applications worked remotely because they were explicitly listed in `tailscale serve status`.

For this machine, the canonical solution is a localhost-bound service behind Tailscale Serve.

### 9.2 `0.0.0.0` is not a browser destination

It is a bind address. Local browsing still uses `127.0.0.1`, and remote Tailscale Serve uses the MagicDNS HTTPS hostname.

### 9.3 Ping success only proves part of the path

The laptop could ping the desktop's Tailscale IP while TCP port 8797 failed. This proved tailnet reachability but did not prove direct application exposure. Testing the service from the desktop's own Tailscale IP also did not prove that another peer could connect.

### 9.4 Release source archives are insufficient

The updater depends on a custom manifest and checksum. A tag or GitHub-generated source ZIP alone is not an installable release.

### 9.5 Validation rules depend on lifecycle stage

A clean source archive should reject caches, virtual environments, generated databases, and secrets. An installed application naturally contains a virtual environment, caches, and runtime data. One validator mode cannot sensibly enforce both sets of rules.

### 9.6 Runtime preferences should not live only in `.env`

`.env` is useful for bootstrapping and administrator-level settings, but frequently changed model choices belong in a runtime settings store controlled through the UI. Persisting them under `data/runtime` also makes them update-safe.

### 9.7 Browser sockets must be part of shutdown design

An updater cannot merely set `server.should_exit`. Long-lived WebSockets and other background tasks need an explicit coordinated shutdown signal or bounded cancellation.

### 9.8 Version assertions must not duplicate literals

Tests that assert a specific version string become guaranteed release failures. Import `__version__` or test version-source consistency instead.

### 9.9 Windows text encoding is an operational concern

PowerShell's encoding defaults vary by version. Configuration files written by scripts should explicitly use UTF-8 without BOM.

### 9.10 UI visibility needs CSS-level verification

HTML's `hidden` attribute can be overridden by CSS `display` rules. The global `[hidden]` rule is intentional and should remain.

## 10. Known issues and risks

### 10.1 Laptop cannot currently open the Tailscale Serve endpoint

The phone can open it, so server configuration is working. Investigate the laptop independently:

- Tailscale client connected to the expected account/tailnet
- MagicDNS resolution
- system clock and TLS certificate validation
- browser-specific behavior
- local DNS filtering or VPN conflict
- endpoint protection/firewall
- `tailscale ping ethan-pc`
- opening the MagicDNS hostname in a different browser

Do not change the server until client-side diagnostics show a server problem.

### 10.2 No application authentication

The app assumes localhost or trusted tailnet access. Do not expose it through a public router port-forward or public Tailscale Funnel. Mutation endpoints can control the simulation, settings, and updates.

A future security phase should add local authentication or at least an application access token before broader exposure.

### 10.3 Runtime API keys are plaintext

`data/runtime/llm-settings.json` can contain an API key. This is acceptable for the current no-key LM Studio default but not ideal for real credentials.

### 10.4 Model compatibility is only partially checked

The app verifies that the selected model appears in `/models`. It does not proactively test JSON-schema compliance before enabling it. Some local models may repeatedly fall back because of malformed JSON, unsupported `response_format`, or poor instruction following.

### 10.5 Context-length setting is advisory

Changing the UI field does not change LM Studio's loaded context window. The app should make this clearer.

### 10.6 AppDock restart behavior is not fully verified

The updater restarts the app directly. If AppDock is later used as the process manager, verify that its status and restart behavior remain coherent after an updater-managed process replacement.

### 10.7 Direct Tailscale firewall scripts are no longer the preferred path

`scripts/enable-tailscale-access.ps1` represents the earlier direct-IP approach. It may remain useful for optional direct binding, but the working and safer default is Tailscale Serve. A future release should replace or supplement it with a `configure-tailscale-serve.ps1` helper.

### 10.8 Direct commits to `main`

The user explicitly prefers that the assistant make and push changes rather than repeatedly asking the user to run Git commands. The work so far has therefore been committed directly to `main`.

For risky or large refactors, a branch and pull request may be safer, but do not impose that workflow without discussing it with the user. Whatever workflow is used, the user should not be asked to manually perform routine repository operations that the connected GitHub tools can perform.

## 11. Development and release workflow

### User collaboration preference

When the user requests a repository change:

1. inspect the current repository state
2. implement the change
3. add or update tests where behavior changes
4. push changes directly through the connected GitHub tooling
5. report commits and validation results
6. do not make the user run routine `git pull`, tag, or push commands

Ask for user action only when it must happen on their local machine—for example, testing LM Studio, browser behavior, Windows permissions, or hardware-specific functionality.

### Versioning rule

Do not bump the version for every commit. Accumulate a coherent feature/fix set, validate it, then update both:

```text
pyproject.toml
app/version.py
```

Use semantic versioning pragmatically:

- patch: fixes, small UI improvements, minor operational features
- minor: meaningful new simulation/cognition/product capabilities
- major: incompatible persistence/API/architecture changes

### Pre-release validation

At minimum:

```bash
python -m pytest -q
python -m compileall -q app tests scripts
python scripts/validate_package.py
python scripts/build_release.py --output dist/embodied-alife-update.zip
ruff check app tests scripts
```

The release workflow runs the core checks again.

### Documentation rule

Update this handoff, roadmap, troubleshooting guide, and changelog whenever changes affect:

- architecture
- persistent data
- installation
- remote access
- updater behavior
- model configuration
- known issues
- the next recommended milestone

## 12. Immediate recommended next steps

The highest-value next work is stabilization and observability around the newly connected local model.

1. **Verify Qwen3-14B end to end.** Discover the exact model ID in the UI, save it, request a decision, and confirm LM Studio logs a request and the dashboard reports `mode: llm`.
2. **Add a model test button.** It should make a minimal schema-constrained request without advancing the simulation and report latency, tokens, raw/cleaned output, and validation errors.
3. **Improve LLM failure visibility.** Show recent failure type, attempt count, and fallback reason in a readable panel rather than only raw JSON.
4. **Add model profiles/presets.** Save named configurations for different local models without retyping values.
5. **Add a Tailscale Serve helper/status panel.** Detect `tailscale serve status`, show the expected URL, and configure/remove the mapping through an administrator script.
6. **Add an end-to-end updater integration test.** Start a real local server with a WebSocket client, initiate a staged update in a temporary project, and verify the old process exits and the worker proceeds.
7. **Investigate the laptop-only Tailscale issue** without changing the working phone/server path.

The broader roadmap is in [`ROADMAP.md`](ROADMAP.md).

## 13. New-session checklist

A future session should begin by doing the following:

1. Read this file, [`ROADMAP.md`](ROADMAP.md), [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md), and [`CHANGELOG.md`](../CHANGELOG.md).
2. Inspect `README.md`, `app/version.py`, and `pyproject.toml` to confirm current version and instructions have not changed.
3. Inspect recent commits on `main` before assuming this document is fully current.
4. Treat the user's local runtime state as valuable. Never delete `data/`, `.env`, or `.venv` casually.
5. Preserve the deterministic-world/structured-action boundary.
6. Use connected GitHub tools to implement and push requested repository changes.
7. Avoid asking the user to repeat Git commands already handled by automation or connected tools.
8. For local-only validation, provide one consolidated PowerShell or Git Bash block and explain what output matters.
9. When diagnosing remote access, distinguish application binding, Windows Firewall, Tailscale policy, and Tailscale Serve instead of conflating them.
10. When diagnosing updates, inspect both the running server log and `data/runtime/update-worker.log`.

## 14. Current handoff summary

The project has moved from a local prototype to a small but genuinely operable application:

- installable from a verified GitHub Release
- persistent across restarts
- observable through a live dashboard
- usable with or without a local LLM
- configurable from the UI
- remotely accessible through Tailscale Serve
- self-updating with verification, backup, rollback, and restart
- protected against the first major classes of Windows packaging and shutdown failures discovered during real installation

The immediate product opportunity is no longer basic deployment. It is improving the quality, transparency, and scientific usefulness of Ari's cognition and behavior while preserving deterministic, inspectable consequences.
