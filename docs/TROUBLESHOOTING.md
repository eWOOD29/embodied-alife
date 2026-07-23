# Troubleshooting

This guide uses portable paths and generic hostnames. Set the installation root once in PowerShell:

```powershell
$root = "$env:LOCALAPPDATA\EmbodiedArtificialLife"
```

Use your actual custom install path instead when applicable.

## Quick health checks

```powershell
Invoke-RestMethod "http://127.0.0.1:8797/health"
Get-NetTCPConnection -LocalPort 8797 -ErrorAction SilentlyContinue |
  Select-Object State, LocalAddress, LocalPort, OwningProcess
```

A healthy response reports `status: ok`, the installed version, and an alive simulation process.

## Start or restart the app

```powershell
Start-Process `
  -FilePath "$root\start-embodied-alife.bat" `
  -WorkingDirectory $root
```

For visible console output:

```powershell
Set-Location $root
& .\.venv\Scripts\python.exe -m app.serve
```

Use `app.serve`, not raw Uvicorn, so the updater can coordinate graceful shutdown.

## Dashboard does not open

Check, in order:

1. `/health` responds.
2. Port 8797 has one listener.
3. `.venv\Scripts\python.exe` exists.
4. The visible launcher shows no import or dependency error.
5. Another process is not already using the port.
6. The browser is not showing a cached page after an update.

Hard-refresh after upgrades when the installed version changed but the page still looks old.

## Wrong Python environment or missing dependencies

```powershell
& "$root\.venv\Scripts\python.exe" -c "import sys; print(sys.executable)"
Set-Location $root
uv pip install --python .venv\Scripts\python.exe -e .
```

The interpreter should be inside the installation's `.venv`.

## Local model remains in fallback

Check the model server directly:

```powershell
Invoke-RestMethod "http://127.0.0.1:1234/v1/models"
```

Then verify in **Local LLM brain**:

- local LLM use is enabled;
- the base URL is correct;
- the selected model ID exactly matches a loaded model;
- the model server is running;
- the dashboard status has no current `last_error`.

A successful model-list request proves discovery only. Generation can still fail because of timeouts, malformed JSON, unsupported response formatting, context exhaustion, or an unloaded model.

The diagnostic export includes provider finish reason, latency, token usage, errors, and model-response history without including API keys.

## Repetitive or looping behavior

Download a diagnostic bundle before resetting the experiment. Useful indicators include:

- repeated action/target pairs;
- repeated authoritative failure reasons;
- high model success but low action success;
- stale target IDs that no longer appear in `target_constraints`;
- repeated controller corrections;
- plans or beliefs that ignore recent outcomes.

The deterministic boundary rejects or corrects target-specific actions that are not executable, stale target IDs, no-op approaches, and repeatedly failing action/target pairs. A continuing loop after those corrections should be reported with the unedited diagnostic JSON and the installed version.

Do not upload diagnostic bundles publicly without reviewing paths, model IDs, memories, and runtime metadata.

## Tailscale Serve

The application has no independent authentication. Keep it on localhost or a private tailnet.

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
tailscale serve status
```

Use the HTTPS hostname displayed by `tailscale serve status`. Do not commit or publish that hostname.

When one tailnet device works and another does not, check the failing client before changing the server:

```powershell
tailscale status
tailscale ping <server-device-name>
Resolve-DnsName <server-device-name>.<your-tailnet>.ts.net
```

Also check account/tailnet membership, MagicDNS, system time, browser certificate state, VPN conflicts, DNS filtering, antivirus, and endpoint protection.

Do not use public Tailscale Funnel or router port forwarding.

## Update does not appear

Check:

```powershell
Invoke-RestMethod "http://127.0.0.1:8797/api/update/status"
```

Then confirm the repository's latest stable GitHub Release contains:

```text
embodied-alife-update.zip
embodied-alife-update.zip.sha256
```

GitHub-generated source archives are not accepted by the application updater.

## Update fails or hangs

Inspect:

```powershell
Get-Content "$root\data\runtime\update-worker.log" -Tail 200
Get-Content "$root\data\runtime\update-state.json"
```

The updater should preserve `.env`, `.venv/`, `data/`, and `.git/`, create a managed-file backup, and roll back if file replacement or dependency synchronization fails.

To repair from the latest published release, rerun the public installer. Do not bypass checksum verification.

## App does not restart after an update

```powershell
Start-Process "$root\start-embodied-alife.bat" -WorkingDirectory $root
Invoke-RestMethod "http://127.0.0.1:8797/health"
```

Review `update-worker.log` for Defender, permissions, dependency, or process-launch errors.

## Package validation fails

Source checkouts and installed trees contain different expected files. Do not weaken validation simply because `.venv`, caches, or runtime data exist in an installed directory. Run:

```powershell
Set-Location $root
& .\.venv\Scripts\python.exe scripts\validate_package.py
```

Fix the exact reported path or lifecycle assumption.

## CI or release failure

Both version declarations must match:

```text
pyproject.toml
app/version.py
```

Run locally:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe scripts\validate_package.py
.\.venv\Scripts\ruff.exe check app tests scripts
```

Tests should import `app.version.__version__` rather than assert a historical literal version.

## Safe issue reports

A useful public issue includes:

- installed version;
- operating-system version;
- the relevant error text;
- minimal reproduction steps;
- a redacted excerpt from diagnostics or logs.

Remove personal usernames, absolute home paths, private hostnames, IP addresses, API keys, tokens, `.env` contents, runtime databases, memories, and full diagnostic bundles before posting publicly.
