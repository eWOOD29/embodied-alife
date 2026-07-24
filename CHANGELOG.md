# Changelog

## [0.4.0.post5] — 2026-07-24

### Fixed

- Replaced forgeable Ari-facing provenance labels with locally keyed, content- and identity-bound creation-path validation for cognitive records, recent outcomes, perceived knowledge, and durable memories.
- Made forged, mutated, copied, conflicting, missing, malformed, and legacy-unverified records fail closed for Ari while preserving complete observer-side state.
- Replaced the machine-specific AppDock project directory with a portable project-relative contract and added recursive decoded structured-file privacy validation.
- Normalized malformed needs, coordinates, inventory, resources, actions, observer state, diagnostics, REST, WebSocket, and fallback-decision inputs before active operations.
- Preserved unknown coordinate semantics instead of clamping malformed positions into plausible world locations.
- Bounded serializer source traversal and temporary work as well as emitted output, including deterministic handling of oversized unordered containers.
- Made AgentState and world loading type-aware, allowlisted, forward-safe, present-empty preserving, and non-destructive on malformed persisted state.
- Kept perception, prompts, diagnostics, and view actions read-only with respect to malformed source collections.
- Added adversarial provenance, source-access, malformed-state, privacy, restart, snapshot, and real production-chain scale coverage.

### Operational

- Ari provenance keys and durable-memory proof ledgers are generated locally under the preserved `data/runtime/` root and are not shipped in release packages.
- Existing states with provenance proofs but a missing key fail closed rather than silently re-signing unverified records.
- After post5 is published and audited, the contaminated downloadable assets from post4 are removed while its immutable tag and historical source remain unchanged.

## [0.4.0.post4] — 2026-07-23

### Fixed

- Preserved bounded, Ari-safe map, task-journal, and notebook results through the authoritative event path into the next decision prompt, with deterministic expiry after the next completed action.
- Replaced text-only record filtering with explicit Ari-facing provenance and origin eligibility while retaining narrow secondary redaction for credentials, private paths, Drive URLs, and private tailnet hostnames.
- Applied normalized finite coordinates consistently through perception and active action-controller distance, direction, lookup, and indexing paths.
- Added deterministic bounded JSON-safe normalization at persistence, observer, diagnostics, API, WebSocket, event, action-result, agent-state, and prompt boundaries.
- Added positive continuity, provenance, malformed-state, serialization, persistence/restart, and 10/100/1,000-record scale coverage.

## [0.4.0.post3] — 2026-07-23

### Fixed

- Computed satiety exclusively from normalized hunger input so malformed persisted or directly mutated hunger cannot crash perception construction.
- Replaced raw task and note record serialization with explicit bounded Ari-facing projections while retaining complete subjective records for persistence and observer diagnostics.
- Added deterministic fixed limits and useful totals to map, task-journal, and notebook action results.
- Added direct-mutation, exact-field sentinel, non-finite JSON, and 10/100/1,000-record boundary tests.

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
