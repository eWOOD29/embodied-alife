# New-session bootstrap prompt

Use the prompt below when beginning a new ChatGPT session about this project. It is intentionally explicit so the new session can continue without reconstructing the installation and debugging history.

## Full prompt

```text
We are continuing development of my public GitHub repository:

eWOOD29/embodied-alife

This is Embodied Artificial Life, a local, persistent artificial-life simulation in which Ari is an embodied language-model agent. The deterministic world, body, and action controller are authoritative. The LLM receives partial perception and may propose a structured action, plan, belief updates, and memory write, but it must never directly mutate the world, database, or host system.

Before responding or changing code, use the connected GitHub tools to read these files from main:

1. docs/PROJECT_HANDOFF.md
2. docs/ROADMAP.md
3. docs/TROUBLESHOOTING.md
4. CHANGELOG.md
5. README.md
6. app/version.py
7. pyproject.toml

Also inspect recent commits on main so you do not assume the handoff is newer than the code.

Current state at the original handoff on July 22, 2026:

- Current working release was v0.2.3.
- Windows installation path:
  C:\Users\ethan\workspace\local-apps\embodied-alife
- Local URL:
  http://127.0.0.1:8797/
- Health endpoint:
  http://127.0.0.1:8797/health
- LM Studio server:
  http://127.0.0.1:1234/v1
- I had Qwen3-14B loaded in LM Studio, but always discover and use the exact model ID returned by /v1/models.
- The app has an in-dashboard Local LLM brain panel that discovers models and saves runtime settings under data/runtime/llm-settings.json. Do not tell me to edit .env merely to change models.
- Working remote access uses Tailscale Serve:
  tailscale serve --bg --https=8797 http://127.0.0.1:8797
- Working remote URL:
  https://ethan-pc.tailce5cf1.ts.net:8797
- The phone could access that URL. The laptop could not at the time of handoff, so treat that as a client-specific unresolved issue unless new diagnostics prove otherwise.
- Do not recommend public port forwarding or Tailscale Funnel; the app has no independent authentication.

Important history:

- GitHub-generated source ZIPs are not valid updater packages. Releases require embodied-alife-update.zip and embodied-alife-update.zip.sha256.
- Source validation and installed validation have different rules. Installed trees contain .venv, caches, and runtime data.
- The project .env is authoritative over inherited Windows environment variables.
- The false always-visible Update available badge was caused by CSS overriding hidden and was fixed with [hidden] { display: none !important; }.
- v0.2.2 added live LM Studio settings and automatic releases from version bumps.
- Pre-v0.2.3 updates could stage successfully but hang during shutdown because the open dashboard WebSocket blocked Uvicorn. v0.2.3 closes browser/server sockets and uses a five-second graceful-shutdown ceiling.

My workflow preference:

- When I ask for repository changes, inspect, implement, test, and push them through the connected GitHub tools on your end.
- Do not repeatedly ask me to run git pull, tag, commit, or push commands that you can handle.
- Ask me to run commands only for local-machine validation that you cannot perform, such as LM Studio, Windows, browser, GPU, Tailscale, or hardware-specific tests.
- Keep me updated during longer work.
- Use direct commits to main for the current workflow unless a change is risky enough that you recommend a branch/PR first.
- Do not bump the application version until a coherent release is ready. Both pyproject.toml and app/version.py must match. Changing those files on main triggers the automatic release workflow.
- Documentation-only changes should not trigger a release.

Safety and persistence requirements:

- Preserve .env, .venv, data/, and .git during updates.
- Treat data/runtime/embodied_alife.db, data/agent_memory/, snapshots, and llm-settings.json as valuable user state.
- Never delete or reset persistent data without explicit confirmation.
- Do not expose API keys, GitHub tokens, .env contents, database contents, or private memories.
- Preserve the deterministic-world/structured-action boundary.
- Do not leak observer-only world truth into Ari's LLM prompt.

When diagnosing problems, distinguish these layers instead of conflating them:

- application process and port binding
- browser/WebSocket behavior
- Windows Firewall
- Tailscale peer policy
- Tailscale Serve mapping
- LM Studio server connectivity
- selected-model availability
- model schema compliance
- updater staging
- updater worker handoff
- dependency synchronization/restart

The next recommended priorities in the original roadmap were:

1. Verify Qwen3-14B end to end through the UI.
2. Add a Test model button that makes a non-mutating schema-constrained request.
3. Improve readable LLM failure/status telemetry.
4. Clarify or implement context-length semantics.
5. Add a first-class Tailscale Serve helper/status panel.
6. Add an end-to-end updater integration test.
7. Build deterministic experiment and model-comparison tooling.

Please first summarize the current repository state you found, note any differences from this handoff, and then continue with my request.
```

## Compact prompt

Use this when context is limited:

```text
Continue my repo eWOOD29/embodied-alife. First read docs/PROJECT_HANDOFF.md, docs/ROADMAP.md, docs/TROUBLESHOOTING.md, CHANGELOG.md, README.md, app/version.py, pyproject.toml, and recent main commits through connected GitHub tools.

Preserve the deterministic-world/structured-action boundary and all persistent state under data/. The working setup at the July 22, 2026 handoff was Windows at C:\Users\ethan\workspace\local-apps\embodied-alife, local http://127.0.0.1:8797, LM Studio http://127.0.0.1:1234/v1, and Tailscale Serve at https://ethan-pc.tailce5cf1.ts.net:8797. Model choice is configured in the app UI and persisted in data/runtime/llm-settings.json.

Implement/test/push requested repo changes on your end; do not make me perform routine Git operations. Only ask me for local Windows/LM Studio/Tailscale/hardware validation. Version bumps in pyproject.toml and app/version.py trigger releases, so bump only when a coherent release is ready.
```

## Maintenance instruction

Whenever the architecture, working setup, current release, known issues, or development workflow changes, update this prompt together with `PROJECT_HANDOFF.md`.
