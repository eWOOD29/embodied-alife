# Embodied Artificial Life — Operations and Troubleshooting

_Last updated: 2026-07-22_  
_Current release at guide creation: **v0.2.3**_

This guide is ordered from fastest checks to deeper diagnostics. The canonical Windows installation is:

```text
C:\Users\ethan\workspace\local-apps\embodied-alife
```

## Quick status checks

Open PowerShell:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"

Invoke-RestMethod "http://127.0.0.1:8797/health"

Get-NetTCPConnection `
  -LocalPort 8797 `
  -State Listen `
  -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

Healthy output should show:

- `status: ok`
- the expected app version
- `alive: True`
- a listener on port `8797`

The listener may be `127.0.0.1` when using Tailscale Serve or `0.0.0.0` for direct interface binding. The recommended current setup is localhost plus Tailscale Serve.

## Start or restart the application

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
Start-Process `
  -FilePath "$root\start-embodied-alife.bat" `
  -WorkingDirectory $root
```

Or from Git Bash:

```bash
cd /c/Users/ethan/workspace/local-apps/embodied-alife
unset PYTHONPATH
.venv/Scripts/python.exe -m app.serve
```

Use `app.serve`, not raw Uvicorn, because the managed launcher provides updater shutdown coordination.

## Stop the application

```powershell
Get-NetTCPConnection `
  -LocalPort 8797 `
  -State Listen `
  -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

## Local page does not open

Check in this order:

1. Confirm the process is listening on port 8797.
2. Open the health endpoint rather than the dashboard.
3. Start the app in a visible terminal to see the Python/Uvicorn error.
4. Confirm `.venv\Scripts\python.exe` exists.
5. Confirm another process is not using the port.

Port check:

```powershell
Get-NetTCPConnection -LocalPort 8797 -ErrorAction SilentlyContinue |
  Select-Object State, LocalAddress, LocalPort, OwningProcess
```

Process details:

```powershell
$pid = (Get-NetTCPConnection -LocalPort 8797 -State Listen).OwningProcess
Get-Process -Id $pid
```

## Wrong Python environment

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
& "$root\.venv\Scripts\python.exe" -c "import sys; print(sys.executable)"
```

Expected path:

```text
...\embodied-alife\.venv\Scripts\python.exe
```

If dependencies are missing:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
Set-Location $root
uv pip install --python .venv\Scripts\python.exe -e .
```

## Local LM Studio model is not active

### Expected LM Studio server

```text
http://127.0.0.1:1234/v1
```

Check the model server directly:

```powershell
Invoke-RestMethod "http://127.0.0.1:1234/v1/models"
```

If that fails:

- open LM Studio
- load a model
- open **Developer**
- start the local server
- confirm the server port is 1234

### Configure through the app

In **Local LLM brain**:

1. Keep the base URL at `http://127.0.0.1:1234/v1`.
2. Click **Discover models**.
3. Select the exact model ID returned by LM Studio.
4. Enable **Use local LLM**.
5. Click **Save and apply**.

The settings persist in:

```text
data\runtime\llm-settings.json
```

### Status remains `fallback`

Common causes:

- local LLM disabled
- no selected model
- selected model is no longer loaded
- LM Studio server stopped
- model returned malformed JSON
- model does not support the requested response format well
- request timed out

Inspect the dashboard's model status, especially:

- `last_error`
- `model`
- `base_url`
- `last_latency_ms`
- token counts

Request a manual decision and watch LM Studio's server log. If no request appears, the problem is connection/configuration. If a request appears and the app falls back, the problem is response quality, schema compatibility, or timeout.

### Qwen model is loaded but not listed

Use the exact ID from:

```powershell
(Invoke-RestMethod "http://127.0.0.1:1234/v1/models").data.id
```

Do not guess the ID from the display name or model filename.

### Context length note

The app's context-length field does not currently change LM Studio's loaded context window. Configure the actual context in LM Studio. The app value is presently stored as runtime configuration metadata.

## Tailscale remote access

### Canonical working setup

The app is served through Tailscale Serve:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
```

Expected status entry:

```text
https://ethan-pc.tailce5cf1.ts.net:8797 (tailnet only)
|-- / proxy http://127.0.0.1:8797
```

Check it:

```powershell
tailscale serve status
```

Remote URL:

```text
https://ethan-pc.tailce5cf1.ts.net:8797
```

Do not use public Tailscale Funnel. The application has no independent login and should remain tailnet-only.

### Phone works but laptop does not

If the phone opens the Serve URL, do not reconfigure the server first. The server and Serve mapping are proven functional.

On the laptop:

```powershell
tailscale status
tailscale ping ethan-pc
Resolve-DnsName ethan-pc.tailce5cf1.ts.net
```

Then check:

- correct Tailscale account and tailnet
- Tailscale client connected, not merely installed
- MagicDNS resolution
- laptop system time
- browser certificate warning
- another browser or private window
- VPN conflicts
- DNS filtering, NextDNS, antivirus, or endpoint protection
- stale browser HSTS/certificate state

The direct-IP test is not equivalent to Tailscale Serve. Serve uses the HTTPS MagicDNS hostname.

### Direct Tailscale IP works locally but not remotely

The desktop reaching its own `100.x.x.x` address only proves a local route. It does not prove another tailnet peer can connect.

The project previously attempted direct exposure with:

- `HOST=0.0.0.0`
- Windows Firewall rules for `100.64.0.0/10`

That path was unreliable in this setup. Prefer Tailscale Serve.

### `tailscale serve status` has no port 8797 entry

Run:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
tailscale serve status
```

### Remove only this Serve mapping

Check current Tailscale CLI help before removal because Serve syntax can vary by version:

```powershell
tailscale serve --help
```

Do not run a global reset unless you intend to remove the user's other existing Serve mappings.

## Update badge is wrong

The false always-visible badge was fixed in v0.2.1. The CSS must retain:

```css
[hidden] { display: none !important; }
```

If the badge appears while the update panel says current:

1. hard-refresh the browser
2. check `/api/update/status`
3. verify the running app version
4. confirm the updated `style.css` is installed

```powershell
Invoke-RestMethod "http://127.0.0.1:8797/api/update/status"
```

## In-app update fails or hangs

### First diagnostic files

```text
data\runtime\update-worker.log
data\runtime\update-state.json
data\runtime\updates\
data\runtime\update-backups\
```

View them:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
Get-Content "$root\data\runtime\update-worker.log" -Tail 200
Get-Content "$root\data\runtime\update-state.json"
```

### Server log shows `POST /api/update/install 200 OK`, then shutdown waits forever

This was the v0.2.0–v0.2.2 WebSocket shutdown bug. It was fixed in v0.2.3 by:

- closing the browser socket before install
- closing server sockets on a shutdown flag
- setting a five-second graceful-shutdown timeout

If a pre-v0.2.3 installation is stuck, use the installer recovery procedure below.

### Recovery installer

This preserves `.env`, `.venv`, and `data/`:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"

Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -like "*embodied-alife*" -and
    $_.CommandLine -like "*apply_update.py*"
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Get-NetTCPConnection `
  -LocalPort 8797 `
  -State Listen `
  -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
  }

$installer = "$env:TEMP\install-embodied-alife.ps1"
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/eWOOD29/embodied-alife/main/install-windows.ps1" `
  -OutFile $installer
PowerShell -ExecutionPolicy Bypass -File $installer
```

### Release has no installable asset

A valid release must contain:

```text
embodied-alife-update.zip
embodied-alife-update.zip.sha256
```

GitHub-generated source archives are not sufficient.

The release workflow is `.github/workflows/release.yml`. It is triggered when `pyproject.toml` or `app/version.py` changes on `main`.

### Checksum verification fails

Do not bypass verification. Confirm:

- ZIP and checksum came from the same workflow run
- release assets were replaced together
- proxy/security software did not replace the download
- the GitHub release does not contain stale assets

### Dependency synchronization fails

The updater should roll managed files back. Inspect the worker log for pip/uv output. Then verify:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
Set-Location $root
& .venv\Scripts\python.exe -m pip --version
uv pip install --python .venv\Scripts\python.exe -e .
```

### App does not restart after a successful update

Start it manually:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
Start-Process "$root\start-embodied-alife.bat" -WorkingDirectory $root
```

Then check `/health` and the update worker log. Defender or a process manager may have blocked detached restart even if file replacement succeeded.

## Installer fails package validation

Earlier installers failed because source-package validation rules were applied to an installed tree containing `.venv`, `__pycache__`, and runtime data. Current validation distinguishes source and installed mode.

If this reappears, inspect the exact paths listed by the validator. Do not blindly loosen source-package validation. Fix the lifecycle-specific mode or the files being generated before validation.

## CI release test fails on version string

Tests should import `app.version.__version__`; they should not assert a literal release version such as `0.2.0`.

Both files must match:

```text
pyproject.toml
app/version.py
```

Check:

```bash
python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
python -c "from app.version import __version__; print(__version__)"
```

## Release workflow fails package validation

CI runs tests and compilation before validation, so it must remove generated artifacts:

```text
__pycache__/
.pytest_cache/
.ruff_cache/
data/runtime/* except .gitkeep
```

Do not include `.venv`, databases, caches, ZIPs, or `.env` in a release package.

## Reset or recover simulation state

### Save a snapshot first

Use the dashboard's **Save snapshot** button before risky experiments.

### Persistent database

```text
data\runtime\embodied_alife.db
```

### Durable memories

```text
data\agent_memory\
```

### Complete reset

A complete reset destroys the current runtime history. Do not do this without explicit confirmation from the user.

Safer sequence:

1. stop the app
2. copy `data/` to a dated backup
3. reset through the dashboard or move only the intended runtime files
4. restart and verify

## Backup the entire persistent state

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$destination = "$env:USERPROFILE\Desktop\embodied-alife-data-$stamp"
Copy-Item "$root\data" $destination -Recurse
Write-Host "Backup created at $destination"
```

## Developer verification

From the repository root:

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py --output dist/embodied-alife-update.zip
.venv/Scripts/ruff.exe check app tests scripts
```

## Diagnostic bundle for a future session

When reporting a problem, provide only the relevant output from:

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"

Invoke-RestMethod "http://127.0.0.1:8797/health"
Get-NetTCPConnection -LocalPort 8797 -State Listen -ErrorAction SilentlyContinue
Get-Content "$root\data\runtime\update-state.json" -ErrorAction SilentlyContinue
Get-Content "$root\data\runtime\update-worker.log" -Tail 100 -ErrorAction SilentlyContinue
tailscale serve status
Invoke-RestMethod "http://127.0.0.1:1234/v1/models"
```

Do not share API keys, GitHub tokens, full `.env` contents, or private memory/database contents unless explicitly needed and redacted.
