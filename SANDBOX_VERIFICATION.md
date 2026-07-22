# Sandbox verification

Verification date: 2026-07-22

## Verified in the sandbox

Environment used:

```text
Linux sandbox
Python 3.13.5
FastAPI 0.128.2
Uvicorn 0.48.0
HTTPX 0.28.1
Pydantic 2.13.4
pytest 9.0.2
pytest-asyncio 1.3.0
Node.js available for JavaScript syntax checking
```

Completed checks:

- `python -m pytest -q` — **40 passed**.
- `python -m compileall -q app tests scripts` — passed.
- `node --check app/web/static/app.js` — passed.
- `python -m json.tool appdock.json` — passed.
- `bash -n start.sh` — passed.
- `scripts/smoke_simulation.py` — passed a deterministic fallback run.
- Real Uvicorn process launched through `python -m app.serve` on sandbox port `8798`.
- `ss` confirmed the server listened on `0.0.0.0:8798`.
- Live `GET /health` returned `status: ok`, version `0.2.0`, and explicit fallback mode.
- Live dashboard HTML returned and contained the **Application updates** interface.
- Live `GET /api/update/status` returned a disabled updater state when `UPDATE_ENABLED=false` was supplied for the smoke process.
- Existing REST simulation controls, static files, and WebSocket state behavior remained covered by automated tests.
- A mock OpenAI-compatible model accepted valid structured actions and explicitly fell back after malformed output.
- Mock GitHub release API responses were used to verify update discovery, release metadata, package download, checksum download, SHA-256 verification, manifest validation, and staging.
- Malicious ZIP path traversal was rejected.
- A tampered worker manifest containing `../` was rejected before any file replacement.
- Incorrect checksum filenames were rejected.
- The update apply routine preserved `.env` and `data/`, removed an obsolete managed file, installed a new managed file, and wrote a backup.
- A deliberately incomplete staged update triggered rollback and restored the pre-update managed file.
- The update API rejected installation without the custom confirmation header.
- `scripts/build_release.py` built a version `0.2.0` release package with 66 managed files.
- The generated release ZIP passed integrity testing with `unzip -t`.
- The generated release manifest was parsed and validated with the same runtime security code used by the updater.

The automated suite covers:

- world ticks, day progression, needs, critical damage, temperature, and shelter effects
- movement, pathfinding, collisions, reachability, and invalid actions
- inventory, gathering, eating, drinking, sleeping, dropping, and building
- deterministic seed reproducibility
- objective truth versus agent beliefs
- snapshots, serialization, and transient SQLite lock retry
- deterministic fallback and mocked LLM behavior
- memory validation, retrieval, duplicates, and sleep consolidation
- REST, static dashboard, full-map versus limited-state APIs, and WebSockets
- all-interface host propagation through `app.serve`
- update discovery and status
- mocked GitHub release assets and SHA-256 verification
- ZIP traversal protection and manifest validation
- protected local-state preservation
- obsolete managed-file cleanup
- failed-update rollback
- update API confirmation behavior

## Checks that could not be run in the sandbox

### Windows updater process

The sandbox is Linux and has neither Windows PowerShell nor `pwsh`. Therefore these Windows-specific paths were not executed:

- `install-windows.ps1`
- the Windows `ctypes` process-wait branch used by `scripts/apply_update.py`
- detached Windows restart flags
- Windows Defender prompts or file-lock behavior

The cross-platform file apply/backup/rollback logic used by the worker was directly tested. The actual Windows process handoff remains a local verification item.

### Real GitHub repository and release

At verification time, `eWOOD29/embodied-alife` did not exist among the repositories visible through the connected GitHub account. The sandbox therefore could not verify:

- pushing the project to that repository
- the GitHub Actions test workflow
- the tag-triggered release workflow
- real GitHub Release creation
- a real public or private release API response
- real release-asset redirects/downloads
- a complete one-click update from one published version to another

Those network interactions were tested with an HTTPX mock server using GitHub-shaped release and asset responses.

### Project-local dependency installation and Ruff

The sandbox's package mirror previously returned HTTP 503 errors during isolated dependency installation. Tests used the sandbox's already-installed dependencies. Ruff was configured but unavailable and could not be run.

## Not verified because the sandbox has no access to the target computer

- Windows 11 installation or Git Bash behavior
- initial installation through the GitHub-hosted PowerShell installer
- actual one-click shutdown/update/restart on Windows
- AppDock state after an updater-managed restart
- LM Studio connection and exact model identifier
- RTX 5080 VRAM use, latency, throughput, and context limits
- browser behavior/performance on the target computer
- Windows Firewall helper execution
- actual Tailscale connectivity, MagicDNS, or tailnet policy
- private-repository token permissions
- long-duration operation over hours or days

Run the local checklist in `WINDOWS_SETUP.md` before treating those items as verified.
