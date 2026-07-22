# Embodied Artificial Life — Roadmap

_Last updated: 2026-07-22_  
_Current release at roadmap creation: **v0.2.3**_

This roadmap is intentionally ordered by dependency and learning value. The goal is not to add the largest number of features; it is to improve the quality, inspectability, and scientific usefulness of embodied behavior without weakening the deterministic world boundary.

## Guiding objective

Build a persistent artificial-life environment in which a local language model can develop behavior, beliefs, memories, plans, relationships, and eventually culture through constrained embodiment and real consequences.

The project should remain:

- local-first
- inspectable
- deterministic where possible
- persistent
- model-agnostic
- useful in fallback mode
- safe from arbitrary model-side execution
- capable of controlled comparison across models, prompts, seeds, and versions

## Priority legend

- **P0 — Stabilize now:** required before expanding scope
- **P1 — High value:** next major product/research improvements
- **P2 — Medium term:** meaningful expansion after core observability is solid
- **P3 — Long term:** ambitious ALife capabilities

---

## Phase 0 — Stabilize the local-model and operations layer

### P0.1 End-to-end Qwen3-14B verification

**Goal:** Confirm the current loaded Qwen3-14B model can reliably serve as Ari's decision brain.

Tasks:

- discover the exact LM Studio model ID through the UI
- save and apply the model
- request a decision without advancing unrelated simulation time
- verify LM Studio receives the request
- verify the response validates against `ActionDecision`
- confirm the dashboard reports `mode: llm`
- record latency, prompt tokens, completion tokens, and fallback behavior
- test at least several distinct world states, including danger and urgent bodily needs

Acceptance criteria:

- at least 20 requested decisions complete without crashing the app
- schema-valid response rate is measured
- fallback reasons are visible when validation fails
- simulation behavior remains deterministic after the model's action is accepted

### P0.2 Add a **Test model** workflow

**Goal:** Separate model connectivity/schema testing from simulation decisions.

The UI should offer a button that:

1. checks `/v1/models`
2. confirms the selected model is loaded
3. sends a minimal schema-constrained test request
4. validates the response
5. reports:
   - success/failure
   - total latency
   - prompt/completion tokens
   - HTTP status
   - validation error
   - cleaned JSON
   - whether fallback would have occurred

The test must not mutate Ari or advance the world.

Acceptance criteria:

- users can distinguish “server is reachable” from “model can produce valid decisions”
- raw model text is available behind an expandable diagnostic view
- secrets are never included in the diagnostic output

### P0.3 Improve model status and failure observability

Replace the raw-only status presentation with a readable summary:

- active model
- base URL
- connection state
- last decision source
- last latency
- prompt/completion tokens
- last failure category
- retry count
- fallback reason
- timestamp of last successful LLM response

Keep raw JSON available for debugging.

### P0.4 Resolve context-length semantics

Current behavior stores `context_length` but does not change LM Studio's loaded context window.

Choose one of these designs:

- rename it to **Expected model context** and use it only for prompt budgeting
- query a server capability endpoint if LM Studio exposes one
- remove it from the UI until it has an operational effect
- use it to enforce an app-side prompt budget even though LM Studio remains authoritative

Acceptance criteria:

- UI wording accurately reflects what the setting controls
- prompt construction cannot silently exceed the configured app-side budget

### P0.5 First-class Tailscale Serve support

The current working remote-access method is:

```powershell
tailscale serve --bg --https=8797 http://127.0.0.1:8797
```

Add a supported helper such as:

```text
scripts/configure-tailscale-serve.ps1
scripts/remove-tailscale-serve.ps1
```

The helper should:

- detect Tailscale installation
- verify the daemon is connected
- configure the exact Serve mapping
- print the resulting MagicDNS URL
- show `tailscale serve status`
- avoid public Funnel exposure
- leave unrelated Serve mappings untouched

Optional UI status:

- Serve configured/not configured
- current HTTPS URL
- local proxy target

### P0.6 End-to-end updater integration test

Unit tests caught many issues, but the v0.2.3 bug required a real server, live WebSocket, process shutdown, and detached worker.

Build a Windows-oriented or cross-platform integration harness that:

- launches the managed server in a temporary project
- opens a WebSocket
- stages a known test update
- requests install
- confirms the socket closes
- confirms the server exits within the shutdown ceiling
- confirms the worker begins after parent exit
- confirms managed files are replaced
- confirms protected paths survive
- confirms the new process starts

At minimum, add a CI-safe simulation of the process handoff and keep a local Windows checklist for the full path.

### P0.7 Documentation consistency checks

Add a lightweight test or maintenance checklist to prevent instructions from drifting:

- README current version-neutral language
- no manual-tag instructions after automatic releases
- LM Studio guidance points to the UI
- Tailscale guidance points to Serve
- protected update paths remain consistent across docs and code

---

## Phase 1 — Make cognition measurable and comparable

### P1.1 Deterministic experiment harness

Create a reproducible evaluation runner that can compare:

- fallback brain
- different local models
- different quantizations
- different prompts
- different temperatures
- different memory configurations

The harness should run fixed seeds and scenarios and export structured results.

Suggested metrics:

- survival time
- hydration/hunger crises
- action validity rate
- unreachable/illegal target rate
- repeated-action loops
- exploration coverage
- resource efficiency
- shelter completion
- dangerous-NPC avoidance
- memory retrieval usefulness
- schema-valid response rate
- average latency and token usage
- fallback rate

Outputs:

```text
data/experiments/<run-id>/config.json
data/experiments/<run-id>/events.jsonl
data/experiments/<run-id>/metrics.json
data/experiments/<run-id>/summary.md
```

### P1.2 Prompt and schema versioning

Record with every model response:

- app version
- prompt template version/hash
- schema version
- model ID
- runtime model settings
- world seed
- simulation time
- retrieved memory IDs

This makes behavioral changes attributable rather than anecdotal.

### P1.3 Decision inspector

Add a dashboard view for each decision showing:

- permitted perception supplied to the model
- retrieved memories
- active plan
- model output
- parsed decision
- controller validation
- action execution timeline
- final result
- belief updates
- memory-write request and validation outcome

The inspector should make it obvious where a poor outcome originated:

- perception limitation
- model reasoning/action choice
- schema conversion
- controller rejection
- environmental consequence
- stale or misleading memory

### P1.4 Named model profiles

Allow users to save profiles such as:

```text
Qwen3-14B Balanced
Qwen3-14B Fast
Qwen3.6-27B Remote
Fallback Only
```

Each profile can include:

- base URL
- model ID
- temperature
- max output tokens
- timeout
- prompt-budget target
- response-format compatibility flags

Do not duplicate secrets unnecessarily.

### P1.5 Model compatibility modes

Some OpenAI-compatible servers/models may not support `response_format` or may use different model-list semantics.

Add capability flags or automatic fallback strategies:

- JSON response format supported
- plain prompt-only JSON mode
- model field required/ignored
- usage fields available/unavailable
- reasoning content separated from final content

### P1.6 Cost/performance telemetry for local inference

Track:

- request frequency
- tokens per simulated hour/day
- average and percentile latency
- GPU/model availability gaps
- invalid-output retries
- time spent waiting on inference versus simulation

This will help tune whether every decision should invoke the LLM or whether more behavior should be handled by lower-level policies.

---

## Phase 2 — Deepen embodiment and world interaction

### P2.1 Hierarchical action system

Separate cognition into levels:

```text
long-term goal
  → plan
    → task
      → validated atomic action
```

The LLM should not need to repeatedly micromanage every movement tile. The controller can execute bounded tasks and interrupt when perception, danger, needs, or feasibility changes.

### P2.2 Richer resource and crafting graph

Expand beyond basic gathering and shelter building:

- tools
- containers
- fire
- food preparation
- water collection/purification
- clothing
- repair
- storage
- material quality
- resource spoilage

Keep every recipe and physical requirement deterministic and inspectable.

### P2.3 More realistic bodily systems

Potential additions:

- injury location and severity
- infection risk
- fatigue versus sleep pressure
- thermoregulation and insulation
- food macronutrients and digestion timing
- thirst and water quality
- carrying capacity
- movement speed and injury penalties

Avoid adding complexity without corresponding decisions and observable consequences.

### P2.4 Environmental hazards and seasons

- terrain traversal costs
- storms and shelter exposure
- heat/cold waves
- flooding/drought
- seasonal resource changes
- fire spread
- darkness and visibility

### P2.5 Better spatial knowledge

Ari should maintain an imperfect internal map rather than receiving unexplained coordinates.

Add:

- landmarks
- uncertain location estimates
- route memory
- map confidence
- forgotten or outdated locations
- discovered paths
- navigation errors under stress or darkness

### P2.6 Expanded NPC ecology

- prey and predator routines
- territorial behavior
- resource competition
- injury and death
- migration
- communication cues
- individual recognition

NPC behavior should remain deterministic or seed-controlled enough for reproducible experiments.

---

## Phase 3 — Memory, learning, and identity

### P2/P3.1 Memory taxonomy

Split durable memory into clearer categories:

- episodic — what happened
- semantic — learned world facts
- procedural — how to do something
- social — knowledge about individuals
- goals/commitments — promises and plans
- self-model — beliefs about abilities, needs, and identity

### P2/P3.2 Provenance and confidence

Every belief/memory should optionally include:

- source event or observation
- confidence
- first-seen time
- last-confirmed time
- contradiction links
- whether it was directly perceived, inferred, or told by another agent

This enables false beliefs without losing observer auditability.

### P2/P3.3 Forgetting and interference

Add controlled forgetting rather than unlimited accumulation:

- salience decay
- retrieval strengthening
- interference between similar memories
- sleep consolidation
- emotional/need-based weighting
- preservation of identity-defining memories

### P2/P3.4 Learning from outcomes

Ari should update procedural expectations after success or failure:

- “this route was blocked”
- “these berries caused illness”
- “the wolf is active near this landmark at night”
- “a shelter of this material failed in a storm”

The world remains authoritative; learning changes future choice, not physical laws.

### P3.5 Persistent identity development

Explore whether Ari develops stable:

- preferences
- habits
- risk tolerance
- routines
- attachment to places/objects
- self-narrative
- values

Make these inspectable and distinguish them from prompt-imposed personality.

---

## Phase 4 — Social and multi-agent artificial life

Do not begin this phase until single-agent cognition, persistence, and evaluation are reliable.

### P3.1 Multiple embodied agents

Each agent should have:

- separate partial perception
- separate body and inventory
- separate memory vault
- individual model/profile or fallback policy
- independent beliefs about others

### P3.2 Communication as action

Speech should be:

- range-limited
- interruptible
- recorded as an event
- perceived imperfectly where appropriate
- distinguishable from truth

Agents should be able to lie, misunderstand, forget, and form beliefs based on testimony.

### P3.3 Cooperation and conflict

- resource sharing
- trade
- task division
- promises
- reputation
- theft
- territorial conflict
- rescue
- coalition formation

### P3.4 Culture and institutions

Long-term research targets:

- shared conventions
- teaching
- rituals
- norms
- leadership
- role specialization
- symbolic artifacts
- intergenerational knowledge

### P3.5 Reproduction, inheritance, and evolution

Only after ethical and technical design work:

- bounded reproduction rules
- inherited traits or policies
- mutation/variation
- selection pressures
- lifespan and generations
- cultural versus genetic inheritance

This phase should be treated as a research project, not a quick gameplay feature.

---

## Phase 5 — User experience and visualization

### P1/P2.1 Dashboard information architecture

The current dashboard is functional but dense. Improve it with:

- collapsible panels
- responsive mobile layout
- readable model status
- selected-agent focus
- timeline filters
- decision inspector
- memory browser/search
- snapshot management
- experiment comparison

### P2.2 Time controls

- step one tick
- step until next decision
- step until action completion
- run until a condition
- pause on danger, injury, death, memory write, or model fallback

### P2.3 Map inspection tools

- zoom/pan
- hover details
- perception overlay
- known-versus-unknown overlay
- path and planned-route overlay
- event markers
- resource history
- observer-only debug layers

### P2.4 Replay and branching

Use snapshots and deterministic seeds to support:

- replay from a prior point
- compare two model decisions from the same state
- fork worlds with different prompts/models
- side-by-side outcome timelines

### P2.5 Exportable reports

Generate experiment summaries suitable for sharing:

- run configuration
- key events
- survival/behavior metrics
- model performance
- representative decisions
- failure analysis
- charts

---

## Phase 6 — Reliability, security, and packaging

### P1.1 Application authentication

Before exposing beyond a trusted tailnet:

- add an application token or local login
- protect mutation endpoints
- add CSRF/origin protections where appropriate
- separate observer/read-only access from control access

### P1.2 Secure secret storage

Move API keys from plaintext runtime JSON to:

- Windows Credential Manager
- DPAPI-encrypted storage
- or an external secret provider

### P1.3 Process management

Evaluate:

- Windows service mode
- AppDock integration
- tray application
- startup-at-login option
- health supervision
- clean log rotation

### P1.4 Backup and migration

Add supported commands for:

- exporting all persistent state
- importing on another machine
- schema migration
- restoring a pre-update backup
- validating database and memory integrity

### P2.5 Signed releases

Current updates use SHA-256 from GitHub release metadata/assets. Future hardening could add:

- release signing
- pinned signing key
- signed manifests
- reproducible build metadata

### P2.6 Cross-platform packaging

Possible later targets:

- Linux installer/service
- macOS launcher
- containerized server mode

Preserve local GPU/model-server interoperability.

---

## Recommended next release sequence

### v0.2.4 — Model verification and documentation polish

Candidate scope:

- Test model button
- improved readable model status
- context-length wording fix
- Tailscale Serve helper script
- laptop/client troubleshooting guidance
- updater integration-test scaffolding

### v0.3.0 — Experiment and decision observability

Candidate scope:

- decision inspector
- prompt/schema version metadata
- deterministic scenario runner
- metrics export
- named model profiles

### v0.4.0 — Richer embodiment

Candidate scope:

- hierarchical tasks
- expanded crafting/resources
- injuries and environmental exposure
- improved spatial memory

### v0.5.0 — Deeper learning and memory

Candidate scope:

- memory taxonomy
- confidence/provenance
- forgetting/interference
- procedural learning from outcomes

### v0.6.0+ — Multi-agent foundation

Begin only after robust single-agent evaluation and persistence.

---

## Definition of success for the next major milestone

The next major milestone is reached when a user can load two different local models, run the same deterministic scenario, and clearly answer:

- what each model perceived
- what memories each model received
- what each model chose
- whether the choice was valid
- what the deterministic world did
- why a fallback occurred
- how the behavioral outcomes differed
- how much latency and token use each model required

That capability will turn the project from a compelling interactive prototype into a practical embodied-agent research environment.
