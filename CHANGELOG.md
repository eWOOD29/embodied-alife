# Changelog

## [0.4.0.post2] — 2026-07-23

### Fixed

- Replaced recursive marker-dictionary sanitation with an explicit Ari-safe `view_map` projection. Unknown marker fields, observer metadata, absolute locations, provenance details, and private operational data cannot cross the cognition boundary.
- Added final fixed count and text bounds to every ordinary decision-context source, including key items, tasks, personality traits, active plans, memories, outcomes, known locations, events, beliefs, and malformed extension data.
- Added controlled finite numeric projection for malformed beliefs, locations, markers, episodes, events, and schema timestamps.
- Normalized all linked-ID and evidence lists through one stable bounded policy so scalar strings never become character arrays.
- Changed release packaging to include tracked files only, preventing untracked root-level reports from entering release archives.
- Reworked the repository-only privacy test so it remains packageable without embedding literal private-machine sentinels in the public archive.

### Tests

- Added exact-branch nested sentinels for the previously vulnerable `map_markers[*].believed_location` path and recursively checked action results, first and normal prompts, fallback context, and observer-diagnostic preservation.
- Added 10/100/1,000-record growth tests across every ordinary prompt source.
- Added direct-mutation and legacy-load malformed numeric tests plus repeated linked-list load/save stability checks.

All notable changes to Embodied Artificial Life are documented here.

The project uses semantic versioning pragmatically while it is still in early development. The GitHub release workflow is triggered when both `pyproject.toml` and `app/version.py` are updated on `main`.

## [Unreleased]

## [0.4.0.post1] — 2026-07-23

This post-release remediation corrects functional acceptance defects discovered by independent review after v0.4.0 was published. The historical v0.4.0 tag and Release remain unchanged.

### Fixed

- Replaced raw absolute `known_terrain` keys in `view_map` with an Ari-relative, subjective map representation and removed the misleading self-declared observer-safety flag.
- Replaced complete ordinary-prompt belief injection with deterministic counts and at most six bounded claim/basis summaries; capped repeated nearby known-terrain and known-location context.
- Made snapshot loading restore the saved experiment payload exactly. Snapshot-load observability is external metadata and does not append to restored experiment history.
- Distinguished absent cognitive collection fields from present empty dictionaries across serialization, restart, and snapshots.
- Hardened legacy cognitive-state normalization for malformed collection types, mixed legacy beliefs, missing record IDs, invalid statuses, and out-of-range confidence or salience values without converting subjective claims into observer truth.

### Tests

- Added adversarial hidden-information and absolute-coordinate sentinels with recursive Ari-facing payload checks.
- Added complete normalized snapshot-payload equality and repeated-load idempotence checks.
- Added realistic prior-version and malformed-state fixtures.
- Replaced the loose prompt-size assertion with all-store sentinel tests and explicit bounded-growth checks for first and ordinary decisions.

## [0.4.0] — 2026-07-23

### Added

- Added the approved one-time awakening context for clean experiments.
- Added protected Blank Field Map, Task Journal, and Field Notebook key items outside ordinary carrying capacity.
- Added four stable starter tasks as broad proposed reminders rather than mandatory quests.
- Added versioned, provenance-bearing schemas for tasks, notes, subjective map markers, epistemic beliefs, short-term episodes, and awakening state.
- Added `view_map`, `view_task_journal`, and `view_notebook` actions that return only Ari-known information.
- Added backward-compatible v0.3.4 state migration plus snapshot, restart, reset, privacy, and compact-context acceptance tests.
- Added public cognitive-state architecture documentation.

### Changed

- Agent state and snapshots now persist every foundational cognitive store.
- Legacy belief dictionaries migrate into structured subjective beliefs without becoming observer truth.
- v0.4.0 intended to use compact cognitive-tool summaries; independent review found complete belief injection, corrected in v0.4.0.post1.
- Reset seed clears prior-world cognition and awakening presentation state before recreating exactly one starter set.
- Package secret scanning now identifies plausible API-key tokens without flagging ordinary hyphenated words.

### Security

- v0.4.0 intended to separate Ari-facing and observer state; independent review found absolute map-coordinate leakage, corrected in v0.4.0.post1.
- Public package validation continues to reject secrets, private runtime artifacts, and generated local state.

### Tests

- Added initial coverage for these areas; independent review found semantic gaps in A4, A7, and A10, corrected by v0.4.0.post1.

## [0.3.4] — 2026-07-23

### Added

- Added explicit model-facing `hunger_deficit` and `satiety` values with unambiguous scale definitions.
- Added food-policy metadata distinguishing immediate eating need from maintaining a small inventory reserve.
- Added pre-execution policy corrections for unnecessary eating, excess food gathering, and consecutive stationary `look` actions.
- Added regression coverage for fully-fed hunger semantics, eating thresholds, consecutive-look correction, and prompt wording.

### Changed

- Eating is now recommended and executable only when hunger deficit reaches the configured threshold; low hunger values correctly mean Ari is well-fed.
- Body perception now labels health, energy, and hydration as reserves while hunger, sleep pressure, and pain are explicitly identified as deficits or pressures.
- The decision prompt now states that `look` is stationary and cannot be used repeatedly as exploration without movement or a meaningful state change.
- Repeated stationary observation is converted into directional movement before execution while preserving the raw model response for diagnostics.

### Fixed

- Fixed Qwen interpreting “low hunger” as an urgent need to eat when Ari was nearly fully satiated.
- Fixed repeated berry consumption while hunger deficit was near zero.
- Fixed indefinite successful `look` loops that produced no new spatial information.

## [0.3.3] — 2026-07-23

### Added

- Added deterministic decision correction before execution for stale targets, unavailable target actions, no-op approaches, and repeatedly failing action/target pairs.
- Added `decision_corrected` timeline events that preserve both the model proposal and the action actually executed by the controller.
- Added recent authoritative action outcomes and blocked failures to the LLM decision context so successful intermediate actions cannot hide repeated failures.
- Added resource quantity, depletion, portability, edibility, and per-action approach requirements to the executable-action map.
- Added regression coverage for interaction-range consistency, stale-target correction, required approaches, repeated failure loops, authoritative soak evidence, and public-repository hygiene.
- Added public architecture documentation and explicit repository privacy boundaries.

### Changed

- Standardized inspect, gather, and eat interactions on one deterministic 2.2-meter interaction radius so `move_to` cannot report success while leaving Ari unable to interact.
- Soak-test protocol v2 now counts weather, storms, temperature stress, danger encounters, regeneration, and other scenarios only from authoritative event types rather than words appearing in model decisions.
- Windows installation now defaults to `%LOCALAPPDATA%\EmbodiedArtificialLife` and all public instructions use environment variables or generic placeholder paths.
- README, Windows setup, and troubleshooting documentation were rewritten for a general public audience.

### Fixed

- Fixed a loop in which Ari repeatedly approached, inspected, and attempted to eat from the same unavailable berry bush.
- Prevented stale or depleted resource IDs from being executed as valid target-specific actions.
- Prevented repeated failed action/target pairs from continuing indefinitely without reassessment.
- Prevented decision text such as `danger_detected` or references to storms from falsely satisfying soak-test scenario coverage.

### Privacy

- Removed personal Windows usernames, absolute home-directory paths, private Tailnet hostnames, device-specific troubleshooting history, and internal assistant bootstrap material from the current public tree.
- Removed internal project-handoff documentation from the public repository; canonical project state remains in the private Google Drive Project Hub.
- Added an automated test that rejects known private machine markers and tracked runtime or diagnostic artifacts.

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
