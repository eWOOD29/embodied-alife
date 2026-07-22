# Verification record

_Last updated: 2026-07-22_  
_Current release at update: **v0.2.3**_

This file preserves the original sandbox verification and records the real Windows deployment results that superseded its earlier limitations. For current operations, use [`WINDOWS_SETUP.md`](WINDOWS_SETUP.md) and [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Original sandbox verification

The first packaged updater work was verified in a Linux sandbox before the GitHub repository and Windows release were available.

Environment at that time:

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

Checks completed for the original v0.2.0 candidate included:

- Python test suite passed at that point in development.
- Python compilation passed.
- JavaScript syntax checking passed.
- JSON and shell syntax checks passed.
- Deterministic fallback smoke simulation passed.
- A real Uvicorn process launched in the sandbox.
- `/health`, dashboard HTML, REST routes, and WebSocket behavior worked.
- Mock OpenAI-compatible responses validated structured actions and fallback behavior.
- Mock GitHub release responses covered discovery, download, SHA-256 verification, manifest validation, and staging.
- Malicious ZIP traversal and unsafe managed paths were rejected.
- Update apply logic preserved protected state, removed obsolete managed files, created backups, and rolled back incomplete updates.
- Release ZIP integrity and manifest validation passed.

The automated suite covered the major simulation, action, persistence, memory, web, LLM-adapter, and updater-security components.

## Real repository and release verification completed afterward

The following items that were originally unverified were subsequently exercised against the real public repository `eWOOD29/embodied-alife`:

- GitHub repository creation and direct pushes to `main`
- GitHub Actions test and release workflows
- custom release assets:
  - `embodied-alife-update.zip`
  - `embodied-alife-update.zip.sha256`
- installation through the GitHub-hosted PowerShell installer
- project-local `.venv` creation and dependency installation
- preservation of `.env`, `.venv`, and `data/` during repair/reinstallation
- real update discovery through GitHub Releases
- real update package download and staging
- real Windows process shutdown/update/restart debugging
- real browser dashboard and WebSocket behavior
- real Tailscale remote access through Tailscale Serve
- real LM Studio server availability at `127.0.0.1:1234`

## Real-world issues found and resolved

The live Windows installation found several issues that sandbox/unit coverage did not expose.

### Package validation lifecycle mismatch

Initial release validation rejected generated caches and runtime database files. Installed validation then rejected the `.venv` created by the installer and ordinary Python caches.

Resolution:

- source and installed validation modes were separated
- installed validation permits expected runtime artifacts
- source validation remains strict
- secret scanning skips the virtual environment

### False update badge

The dashboard showed **Update available** while the update API correctly reported current.

Cause:

```css
.pill { display: inline-block; }
```

overrode the HTML `hidden` attribute.

Resolution:

```css
[hidden] { display: none !important; }
```

### Stale version assertion

A release failed because a test asserted the literal version `0.2.0` after the application became `0.2.1`.

Resolution: tests now use the runtime `__version__` value.

### Windows environment and encoding behavior

A stale inherited `HOST` environment value could override the project `.env`, and PowerShell's UTF-8 behavior risked writing a BOM.

Resolution:

- project `.env` loads authoritatively
- helper scripts explicitly write UTF-8 without BOM

### Tailscale access architecture

Direct binding and Windows Firewall rules did not produce the expected remote behavior, even though the process listened on all interfaces and the desktop could reach its own Tailscale IP.

The working design is:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
```

The resulting tailnet-only HTTPS URL works from the user's phone.

### Updater WebSocket shutdown deadlock

The pre-v0.2.3 updater returned `200 OK`, downloaded and staged the package, and started shutdown, but Uvicorn remained at:

```text
Waiting for background tasks to complete
```

Cause: the dashboard WebSocket waited indefinitely on its queue, keeping the server alive while the detached update worker waited for the parent PID to exit.

Resolution in v0.2.3:

- browser closes the socket before requesting installation
- server closes sockets when shutdown begins
- reconnection is suppressed during updates
- Uvicorn graceful shutdown is bounded to five seconds
- regression coverage was added

The user repaired the old installation with the latest installer and confirmed v0.2.3 launched successfully.

## Current verified working paths

```text
Local app:
http://127.0.0.1:8797/

Health:
http://127.0.0.1:8797/health

LM Studio:
http://127.0.0.1:1234/v1

Tailscale Serve:
https://ethan-pc.tailce5cf1.ts.net:8797
```

The Tailscale endpoint has been confirmed from the user's phone. Laptop access remained unresolved at the time of this record and appears client-specific because the same server endpoint works from another tailnet device.

## Still requiring local or long-duration verification

- sustained operation over many hours or days
- Qwen3-14B structured-decision reliability across varied states
- latency, throughput, token use, and VRAM behavior on the RTX 5080
- actual effect/semantics of the app's context-length setting
- AppDock status after updater-managed restart
- repeated in-app updates beyond the v0.2.3 handoff fix
- backup/restore and future database migration paths
- laptop-specific Tailscale Serve access
- behavior with multiple simultaneously loaded LM Studio models
- behavior with OpenAI-compatible servers other than LM Studio

## Current validation checklist

Before a release:

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py --output dist/embodied-alife-update.zip
.venv/Scripts/ruff.exe check app tests scripts
```

Then verify locally as appropriate:

- `/health` reports the intended version
- fallback mode still works
- dashboard and WebSocket update normally
- LM Studio model discovery works
- a selected model completes a valid decision or produces a clear fallback reason
- Tailscale Serve URL opens from a trusted peer
- update check finds the intended GitHub Release
- update installation preserves persistent state and reconnects after restart

Do not treat the historical sandbox package count, test count, or v0.2.0 output as current release metadata.
