# Windows setup

Target directory:

```text
C:\Users\ethan\workspace\local-apps\embodied-alife
```

## Recommended: install the latest GitHub Release

This method becomes available after `eWOOD29/embodied-alife` has a published release containing the generated update assets.

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
- verifies `embodied-alife-update.zip` with SHA-256
- installs directly into the target directory
- creates `.venv` with `uv`
- installs dependencies into that project-local environment
- creates `.env` only when one does not already exist
- preserves `data/`, `.env`, `.venv`, and `.git`
- runs package validation
- launches the app

For a private repository, use a fine-grained GitHub token with read-only **Contents** access:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\install-windows.ps1 `
  -Repository "eWOOD29/embodied-alife" `
  -GitHubToken "<read-only token>"
```

Do not place the token in Git, screenshots, logs, or shell-history exports. For ongoing private-repository update checks, place it only in the local `.env` as `UPDATE_GITHUB_TOKEN`.

## Alternative: install the downloaded ZIP in Git Bash

```bash
mkdir -p /c/Users/ethan/workspace/local-apps
cd /c/Users/ethan/workspace/local-apps

unzip /c/Users/ethan/Downloads/embodied-alife-v0.2.0.zip
cd embodied-alife

uv venv --python 3.11
unset PYTHONPATH
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'

cp .env.example .env

unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/smoke_simulation.py
```

The commands install only into:

```text
C:\Users\ethan\workspace\local-apps\embodied-alife\.venv
```

They do not install into system Python, Hermes, or another project.

## Configure fallback mode first

Edit `.env`:

```text
NO_LLM=true
LLM_MODEL=
```

Keep:

```text
HOST=0.0.0.0
PORT=8797
```

Start with:

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m app.serve
```

Or double-click:

```text
start-embodied-alife.bat
```

Open locally:

```text
http://127.0.0.1:8797/
```

Health endpoint:

```text
http://127.0.0.1:8797/health
```

Use `app.serve` rather than raw Uvicorn. The managed launcher is needed for graceful one-click updates.

## Configure automatic updates

The defaults in `.env.example` are:

```text
UPDATE_ENABLED=true
UPDATE_REPOSITORY=eWOOD29/embodied-alife
UPDATE_CHANNEL=stable
UPDATE_ASSET_NAME=embodied-alife-update.zip
UPDATE_CHECK_ON_STARTUP=true
UPDATE_STARTUP_DELAY_SECONDS=5
UPDATE_CHECK_INTERVAL_HOURS=6
UPDATE_TIMEOUT_SECONDS=30
UPDATE_AUTO_RESTART=true
UPDATE_GITHUB_TOKEN=
```

For a public repository, leave `UPDATE_GITHUB_TOKEN` empty.

For a private repository, set a read-only fine-grained token:

```text
UPDATE_GITHUB_TOKEN=<token>
```

Restart the app. In the dashboard's **Application updates** panel:

1. Click **Check now**.
2. Confirm the installed/latest version result.
3. When a newer version appears, click **Install v…**.
4. Confirm the prompt.
5. Keep the browser open while the app stops, updates, restarts, and reconnects.

Local state is preserved automatically:

```text
.env
.venv/
data/
.git/
```

If an update fails, inspect:

```text
data\runtime\update-worker.log
data\runtime\update-state.json
data\runtime\update-backups\
```

A file rollback is automatic when copying or dependency synchronization fails. Do not delete the backup until the updated app has run successfully.

## Configure LM Studio

A practical initial target for the RTX 5080's 16 GB VRAM is **Qwen3-14B Q4_K_M or an equivalent strong Q4 quant**.

1. Load the model in LM Studio.
2. Set model context to **16,384 tokens**.
3. Start LM Studio's OpenAI-compatible server at `127.0.0.1:1234`.
4. In Git Bash:

```bash
curl http://127.0.0.1:1234/v1/models
```

5. Edit `.env`:

```text
NO_LLM=false
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_API_KEY=***
LLM_MODEL=<exact model ID returned by /v1/models>
LLM_CONTEXT_LENGTH=16384
LLM_TIMEOUT_SECONDS=60
```

6. Restart. The dashboard's model status should change from `fallback` to `llm` after a successful decision.

## Allow restricted Tailscale access

Open PowerShell **as Administrator**:

```powershell
cd C:\Users\ethan\workspace\local-apps\embodied-alife
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\enable-tailscale-access.ps1
```

Find the desktop's Tailscale address:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" status
& "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
```

From another permitted tailnet device:

```text
http://<desktop-tailscale-ip>:8797/
```

With MagicDNS enabled:

```text
http://<desktop-machine-name>:8797/
```

Do not create a router port-forward. The app has no independent login, so permit only trusted tailnet identities/devices.

Remove the firewall rules with:

```powershell
.\scripts\disable-tailscale-access.ps1
```

## AppDock

The manifest expects:

```text
Project directory: C:\Users\ethan\workspace\local-apps\embodied-alife
Command: .venv\Scripts\python.exe
Arguments: -m app.serve
Health URL: http://127.0.0.1:8797/health
Local URL: http://127.0.0.1:8797/
Startup: manual
Automatic startup: disabled
```

After manual launch succeeds:

1. Import or discover `appdock.json`.
2. Confirm the command and arguments are exactly as above.
3. Start the app.
4. Verify `/health` includes `"status":"ok"` and the expected `version`.
5. Use the update panel to verify that an AppDock-launched instance can stop and restart.
6. Confirm AppDock's displayed process state after the updater restarts the app directly.

The final two behaviors require local verification because AppDock is not available in the sandbox.

## Publishing the first release

After the GitHub repository exists and this project has been pushed:

```bash
cd /c/Users/ethan/workspace/local-apps/embodied-alife

git status
git add -A
git commit -m "Add verified automatic updates"
git push -u origin main

git tag v0.2.0
git push origin v0.2.0
```

The release workflow should create:

```text
embodied-alife-update.zip
embodied-alife-update.zip.sha256
```

Check the repository's **Actions** and **Releases** pages. The application updater will not report v0.2.0 until the release workflow has finished and the release is published.

## Local verification checklist

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests scripts
.venv/Scripts/python.exe scripts/validate_package.py
.venv/Scripts/python.exe scripts/build_release.py
.venv/Scripts/ruff.exe check app tests scripts
```

Then verify:

- fallback simulation runs
- dashboard and WebSocket update
- local and Tailscale URLs open
- LM Studio changes the model mode to `llm`
- **Check now** reaches the correct GitHub repository
- a later test release is detected
- one-click update preserves `.env`, the SQLite database, snapshots, and Markdown memories
- the app restarts at the new version
- AppDock's state remains usable after the updater-managed restart

## Troubleshooting

### `No published GitHub release was found`

Confirm `UPDATE_REPOSITORY` is correct and the repository has a non-draft release. A pushed commit or tag alone is not enough. For a private repository, confirm `UPDATE_GITHUB_TOKEN` has read-only Contents access.

### `Release … does not contain embodied-alife-update.zip`

The release was created manually or its workflow failed before uploading assets. Rerun/fix `.github/workflows/release.yml` or publish the two assets generated by:

```bash
.venv/Scripts/python.exe scripts/build_release.py
```

### Update installation fails

Inspect:

```bash
cat data/runtime/update-worker.log
cat data/runtime/update-state.json
```

The previous managed files should be under `data/runtime/update-backups/`. Local `.env`, `.venv`, database, snapshots, and memories should remain untouched.

### The page does not reconnect after updating

From Git Bash:

```bash
.venv/Scripts/python.exe -m app.serve
```

Then inspect the update log. Dependency synchronization may have succeeded even if automatic restart was blocked by Defender or another process manager.

### Port 8797 is already in use

```bash
netstat -ano | grep 8797
```

Stop the conflicting process or change `PORT` in `.env`.

### Wrong Python environment

```bash
unset PYTHONPATH
.venv/Scripts/python.exe -c "import sys; print(sys.executable)"
```

The path should end in:

```text
embodied-alife\.venv\Scripts\python.exe
```
