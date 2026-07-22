# Windows setup

_Last updated: 2026-07-22_  
_Current release at update: **v0.2.3**_

Target directory:

```text
C:\Users\ethan\workspace\local-apps\embodied-alife
```

For deeper diagnostics, see [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md). For architecture and project history, see [`docs/PROJECT_HANDOFF.md`](docs/PROJECT_HANDOFF.md).

## Install or repair the latest release

Open PowerShell:

```powershell
$installer = "$env:TEMP\install-embodied-alife.ps1"
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/eWOOD29/embodied-alife/main/install-windows.ps1" `
  -OutFile $installer
PowerShell -ExecutionPolicy Bypass -File $installer
```

The installer:

- downloads the latest published GitHub Release
- requires the custom `embodied-alife-update.zip` asset
- verifies SHA-256
- installs into the target directory
- creates or reuses the project-local `.venv`
- installs dependencies into that environment
- creates `.env` only if it does not exist
- preserves `.env`, `.venv`, `data/`, and `.git`
- validates the installed package
- launches the app

Running the installer again is the supported repair path when an old updater cannot complete its own upgrade.

For a private repository, use a fine-grained read-only token:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\install-windows.ps1 `
  -Repository "eWOOD29/embodied-alife" `
  -GitHubToken "<read-only token>"
```

Do not place tokens in Git, screenshots, exported terminal history, or documentation.

## Run locally

Double-click:

```text
start-embodied-alife.bat
```

Or use Git Bash:

```bash
cd /c/Users/ethan/workspace/local-apps/embodied-alife
unset PYTHONPATH
.venv/Scripts/python.exe -m app.serve
```

Use `app.serve`, not raw `uvicorn app.main:app`. The managed launcher provides the graceful-shutdown callback needed by one-click updates.

Local URL:

```text
http://127.0.0.1:8797/
```

Health endpoint:

```text
http://127.0.0.1:8797/health
```

PowerShell health check:

```powershell
Invoke-RestMethod "http://127.0.0.1:8797/health"
```

## Configure LM Studio through the dashboard

LM Studio's expected default server is:

```text
http://127.0.0.1:1234/v1
```

1. Load a model in LM Studio.
2. Open LM Studio's **Developer** area.
3. Start the OpenAI-compatible server on port 1234.
4. Open Embodied Artificial Life.
5. Find **Local LLM brain**.
6. Keep the base URL at `http://127.0.0.1:1234/v1`.
7. Click **Discover models**.
8. Select the exact model ID returned by LM Studio.
9. Enable **Use local LLM**.
10. Click **Save and apply**.

No `.env` edit or app restart is required when changing models.

Runtime LLM choices persist at:

```text
data\runtime\llm-settings.json
```

Direct model-server check:

```powershell
(Invoke-RestMethod "http://127.0.0.1:1234/v1/models").data.id
```

The user currently has Qwen3-14B available in LM Studio, but always use the exact model ID returned by `/v1/models`.

### Context-length note

The actual loaded context window is configured in LM Studio. The app currently stores its context-length field as runtime metadata/prompt-budget intent; it does not reconfigure the LM Studio model.

## Configure Tailscale Serve

The proven remote-access configuration is Tailscale Serve proxying the localhost app.

Open PowerShell as Administrator:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
tailscale serve status
```

Expected status:

```text
https://ethan-pc.tailce5cf1.ts.net:8797 (tailnet only)
|-- / proxy http://127.0.0.1:8797
```

Remote URL:

```text
https://ethan-pc.tailce5cf1.ts.net:8797
```

This has been confirmed working from the user's phone.

Do not use a router port-forward or public Tailscale Funnel. The app has no independent login and should remain limited to trusted tailnet devices.

### Important distinction

`0.0.0.0` is a server bind address, not a browser URL. Direct binding and Windows Firewall rules are not the same as creating a Tailscale Serve mapping. The user's other remote local applications work because they appear explicitly in `tailscale serve status`.

The earlier `scripts/enable-tailscale-access.ps1` direct-IP approach is not the recommended setup for this machine.

### Laptop-specific issue

At the time of this update, the phone could open the Serve URL but the laptop could not. Since the phone works, first diagnose the laptop's Tailscale connection, MagicDNS, browser/TLS, VPN, DNS filtering, or endpoint protection rather than changing the server.

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md#phone-works-but-laptop-does-not).

## Use in-app updates

The updater checks GitHub Releases shortly after startup and periodically afterward.

In **Application updates**:

1. Click **Check now**.
2. Confirm the latest version.
3. Click **Install v…** when available.
4. Confirm the prompt.
5. The dashboard socket closes, the app stops, files update, and the page reconnects after restart.

The updater preserves:

```text
.env
.venv/
data/
.git/
```

Update diagnostics:

```text
data\runtime\update-worker.log
data\runtime\update-state.json
data\runtime\update-backups\
```

v0.2.3 fixed an issue where a successfully staged update could hang because the live dashboard WebSocket prevented Uvicorn from finishing shutdown.

## Recover from a stuck pre-v0.2.3 update

Close open app pages, then run PowerShell as Administrator:

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

This repair preserves the world database, memories, snapshots, runtime model settings, `.env`, and `.venv`.

## AppDock

Suggested manifest/runtime values:

```text
Project directory: C:\Users\ethan\workspace\local-apps\embodied-alife
Command: .venv\Scripts\python.exe
Arguments: -m app.serve
Health URL: http://127.0.0.1:8797/health
Local URL: http://127.0.0.1:8797/
Startup: manual
Automatic startup: disabled until verified
```

The updater restarts the app directly. If AppDock is used, verify that AppDock's process status remains coherent after an updater-managed restart.

## Developer setup from a source checkout

```bash
cd /c/Users/ethan/workspace/local-apps/embodied-alife
uv venv --python 3.11
unset PYTHONPATH
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
cp .env.example .env
```

Verification:

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py --output dist/embodied-alife-update.zip
.venv/Scripts/ruff.exe check app tests scripts
```

## Release workflow

Normal releases are automatic.

When a coherent release is ready, update both:

```text
pyproject.toml
app/version.py
```

After those matching version changes reach `main`, `.github/workflows/release.yml`:

1. installs dependencies
2. verifies versions match
3. runs tests
4. compiles source
5. validates the package
6. builds the custom ZIP and checksum
7. creates the version tag
8. publishes or updates the GitHub Release

Do not manually create routine release tags. Do not bump versions for documentation-only commits.

A valid release contains:

```text
embodied-alife-update.zip
embodied-alife-update.zip.sha256
```

GitHub-generated source archives are not accepted by the application updater.

## Persistent state backup

```powershell
$root = "$env:USERPROFILE\workspace\local-apps\embodied-alife"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$destination = "$env:USERPROFILE\Desktop\embodied-alife-data-$stamp"
Copy-Item "$root\data" $destination -Recurse
Write-Host "Backup created at $destination"
```

Never delete `data/`, `.env`, or `.venv` as a generic troubleshooting step without understanding the consequence and receiving explicit confirmation.
