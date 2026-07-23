# Changelog

All notable changes to Embodied Artificial Life are documented here.

The project uses semantic versioning pragmatically while it is still in early development. The GitHub release workflow is triggered when both `pyproject.toml` and `app/version.py` are updated on `main`.

## [Unreleased]

### Documentation

- Added a comprehensive project handoff.
- Added a prioritized roadmap.
- Added an operations and troubleshooting guide.
- Added a copy-paste new-session bootstrap prompt.
- Updated Windows setup guidance to reflect the working LM Studio UI and Tailscale Serve workflow.

## [0.3.2] — 2026-07-23

### Added

- Added diagnostic schema v3 with a machine-readable multi-day soak-test readiness report.
- Added scenario coverage for sleep/wake, memory consolidation, day/night cycles, weather, storms, temperature stress, danger encounters, interruptions, shelter construction/degradation, resource regeneration, snapshots, restart continuity, verified memories, memory filtering, and updater continuity.
- Added quality gates for minimum world duration, decision volume, LLM success, final-action success, structural integrity, pending-memory resolution, and agent survival.
- Added `/api/validation/readiness` for checking soak-test progress without downloading the full diagnostic bundle.
- Added `docs/SOAK_TEST.md` with the exact clean-reset, runtime, snapshot, restart, and export procedure.

### Changed

- Diagnostic exports now state which long-horizon systems were actually exercised and list all missing required scenarios.
- The death path is tracked separately from required healthy-run coverage.

### Tests

- Added regression coverage for readiness endpoint identity, scenario counts, quality gates, instructions, and diagnostic integration.

## [0.3.1] — 2026-07-23

### Added

- Upgraded diagnostic exports to schema v2 with run, world-generation, build, process, platform, dependency, path, uptime, and launch metadata.
- Added aggregate model latency/token/success statistics, action success and failure summaries, planning and belief-update counts, and memory candidate/write/rejection metrics.
- Added LM Studio model-catalog caching plus provider response IDs, finish reasons, and retry counts.
- Added sanitized tails of persistent runtime logs when available.
- Added explicit anomaly checks for duplicate live engines, duplicate restore events, and unresolved pending-memory candidates.
- Added release-build metadata generated from the exact Git commit and packaging time.

### Changed

- A transient malformed generation now marks generation health as failed without incorrectly claiming that the LM Studio server is unreachable.
- Provider metadata is persisted with each SQLite model-response record and survives restart.
- Application update status is checked automatically when the dashboard opens.
- Release summaries render as formatted headings, lists, inline code, emphasis, and links instead of raw Markdown.

### Fixed

- Fixed provider metadata storage for slotted result objects.
- Fixed the release-note renderer reading a non-global dashboard state variable.

### Security

- Diagnostic exports continue to exclude API keys, raw `.env` contents, authorization headers, and raw prompts.
- Release-note HTML is generated only after escaping source text.

### Tests

- Added regression coverage for provider metadata round-trips, diagnostic schema v2 sections and metrics, runtime identity, anomaly checks, and secret exclusion.

## [0.3.0] — 2026-07-23

### Added

- Added a deterministic executable-action map describing which visible targets can be inspected, picked up, or eaten immediately and which require `move_to` first.
- Added inventory-edible, drinking, building, material, reachability, and target-distance guidance to every LLM decision context.
- Added explicit prompt distinctions between immediate intent, conditional multi-step plans, evidence-backed belief updates, and durable memories.

### Changed

- Routine movement, looking, waiting, resting, and speaking memories are filtered before outcome staging.
- Inspection memories now require higher importance than other candidates.
- The decision prompt now instructs Ari to use the executable-action map as a hard constraint and to avoid target actions that the deterministic controller cannot currently execute.
- Memory requests are now described as usually null and reserved for surprising, safety-critical, location-specific, or broadly reusable learning.

### Tests

- Added regression coverage for reachability guidance, prompt policy fields, and routine-memory filtering.

## [0.2.9] — 2026-07-23

### Added

- Added stable run and world-generation identifiers to engine state, observer state, awakening events, and clean-reset responses.
- Added pending-memory events and provenance linking verified memories to model responses, decisions, and authoritative action results.
- Added quarantine support for pre-integrity memory files under `data/memory/quarantine/`.

### Changed

- **Reset seed** now starts a clean experiment: world history, model-response history, snapshots, active memories, and prior runtime state are cleared before a new world is generated.
- LLM memory requests are now treated as candidates. They are committed only after the deterministic controller reports a successful final outcome.
- Verified memories are rewritten from the authoritative action result instead of preserving unverified model claims.
- The managed launcher now creates only one application/engine instance; importing `app.main` no longer creates an unused engine and database connection.
- GitHub release bodies are now generated from the matching changelog section so the app displays a concise release summary instead of only an automatic compare link.

### Fixed

- Prevented failed, interrupted, or changed actions from becoming false durable memories.
- Quarantined existing pre-v0.2.9 active memories because their outcome provenance could not be trusted retroactively.
- Removed duplicate restore events caused by import-time application construction.

### Tests

- Added regression coverage for failed-action memory rejection, successful outcome-verified memory creation, clean experiment resets, and release-note extraction.

## [0.2.8] — 2026-07-23

### Added

- Added a **Download diagnostic logs** dashboard control.
- Added a timestamped JSON diagnostic bundle containing application/version metadata, health, complete observer state and map, serialized engine state, non-secret LLM configuration and status, update status, durable memories, snapshots, persisted event history, and persisted model-response history.
- Added diagnostic manifests, section counts, latency/token/error history, attachment filenames, and explicit privacy metadata.
- Added database queries for persisted events and model responses with identifiers and timestamps.

### Security

- Diagnostic exports explicitly exclude API keys and raw `.env` contents.

### Tests

- Added regression coverage for attachment headers, diagnostic completeness, full-world inclusion, versioning, history counts, and secret exclusion.

## [0.2.7] — 2026-07-23

### Fixed

- Disabled Qwen3 thinking for short structured control and memory-consolidation requests using `/no_think`, preventing the model from consuming its output budget without emitting final JSON.
- Separated the minimal LM Studio grammar schema from the complete schema embedded in Ari's prompt.
- Restored the full field-by-field action and consolidation contract in prompts while retaining strict Pydantic validation after generation.

### Tests

- Added regression coverage ensuring server grammars remain minimal, prompt schemas remain complete, and structured prompts disable thinking.

## [0.2.6] — 2026-07-23

### Fixed

- Added deterministic repair for missing descriptive `intent` or `reason` fields when the other field is present.
- Continued rejecting unknown actions, malformed directions, unsafe values, and invalid memory writes.

## [0.2.5] — 2026-07-23

### Fixed

- Replaced the full Pydantic response grammar sent to LM Studio with a grammar-safe top-level JSON object schema.
- Kept complete in-process Pydantic validation so invalid model actions remain blocked.

## [0.2.4] — 2026-07-23

### Added

- Added LM Studio native model discovery with loaded-state metadata.
- Replaced free-text model entry with a loaded-model selector.
- Added model metadata such as state, publisher, quantization, and context length when available.

### Fixed

- Prevented saved but unloaded models from being reported as loaded.
- Corrected stale or mistyped model IDs when LM Studio reports exactly one loaded model.
- Improved LM Studio HTTP errors to include the provider response body.

## [0.2.3] — 2026-07-22

### Fixed

- Fixed in-app updates hanging after successful staging while Uvicorn waited for the dashboard WebSocket.
- The browser now closes the live WebSocket before requesting installation.
- The server now closes WebSocket connections when application shutdown begins.
- Added a five-second Uvicorn graceful-shutdown ceiling so the detached update worker can take over.
- Suppressed normal WebSocket reconnection while an update is in progress.

### Tests

- Added regression coverage for updater WebSocket shutdown handoff.

## [0.2.2] — 2026-07-22

### Added

- Added a **Local LLM brain** settings panel to the dashboard.
- Added model discovery through an OpenAI-compatible `/v1/models` endpoint.
- Added live model switching without editing `.env` or restarting the app.
- Added runtime controls for local LLM enablement, base URL, model ID, temperature, maximum output tokens, timeout, context metadata, and optional API key.
- Added automatic selection when exactly one model is loaded.
- Added persistent runtime LLM settings at `data/runtime/llm-settings.json`.
- Added automatic GitHub tag/release creation when version files change on `main`.

### Changed

- Runtime LLM settings now override baseline LLM values loaded from `.env`.
- Release assets are replaced when rebuilding an existing release.

## [0.2.1] — 2026-07-22

### Fixed

- Fixed the **Update available** badge remaining visible while the application was current.
- Added a global CSS rule so elements with `hidden` cannot be forced visible by component display styles.
- Replaced a hard-coded version assertion in updater tests with the runtime application version.
- Made the project `.env` authoritative over stale inherited Windows environment variables.
- Updated the Tailscale helper to enforce the configured bind address.
- Made PowerShell write `.env` using UTF-8 without a BOM.

## [0.2.0] — 2026-07-22

### Added

- Added the first installable Windows release workflow.
- Added `install-windows.ps1` for verified release installation.
- Added custom `embodied-alife-update.zip` release packages and SHA-256 files.
- Added GitHub Release update checks and dashboard controls.
- Added safe archive inspection, protected paths, update staging, managed-file replacement, dependency synchronization, backup, rollback, and restart.
- Added source-package and installed-package validation modes.
- Added local/Tailscale-oriented server configuration and Windows helper scripts.

### Fixed during initial deployment

- Cleaned test, compile, and runtime artifacts before source-package validation.
- Allowed `.venv`, generated runtime files, and ordinary caches in installed-package validation.
- Prevented secret scanning from traversing the project virtual environment.

## Earlier prototype work

Before the first packaged release, the project established:

- A deterministic wilderness simulation.
- Ari's body, needs, perception, beliefs, plans, and memories.
- A constrained local-LLM boundary with deterministic fallback behavior.
- Persistent SQLite and Markdown state.
- A FastAPI observer dashboard with REST and WebSocket interfaces.
