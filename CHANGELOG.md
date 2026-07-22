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

- seeded deterministic world generation
- Ari's body and internal needs
- partial line-of-sight perception
- deterministic movement, pathfinding, actions, interruptions, and outcomes
- fallback and OpenAI-compatible LLM brains
- structured Pydantic decision schemas
- persistent SQLite runtime state
- durable Markdown memories and consolidation
- snapshots and forks
- FastAPI REST endpoints
- live WebSocket dashboard
- observer truth versus agent perception/belief views
