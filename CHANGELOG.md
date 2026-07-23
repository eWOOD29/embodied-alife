# Changelog

All notable changes to Embodied Artificial Life are documented here.

The project uses semantic versioning pragmatically while it is still in early development. The GitHub release workflow is triggered when both `pyproject.toml` and `app/version.py` are updated on `main`.

## [Unreleased]

## [0.4.0.post1] — 2026-07-23

This post-release remediation corrects functional acceptance defects discovered by independent review after v0.4.0 was published. The historical v0.4.0 tag and Release remain unchanged.

### Fixed

- Replaced raw absolute `known_terrain` keys in `view_map` with an Ari-relative, subjective map representation and removed the misleading self-declared observer-safety flag.
- Replaced complete ordinary-prompt belief injection with deterministic counts and at most six bounded claim/basis summaries; capped repeated nearby known-terrain and known-location context.
- Made snapshot loading restore the saved experiment payload exactly. Snapshot-load observability is now external metadata and does not append to restored experiment history.
- Distinguished absent cognitive collection fields from present empty dictionaries. Absent legacy `key_items` and `tasks` receive starter defaults; present empty collections remain empty across serialization, restart, and snapshots.
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
- Added `view_map`, `view_task_journal`, and `view_notebook` actions.
- Added backward-compatible v0.3.4 state migration plus snapshot, restart, reset, privacy, and context acceptance tests.
- Added public cognitive-state architecture documentation.

### Changed

- Agent state and snapshots persist every foundational cognitive store.
- Legacy belief dictionaries migrate into structured subjective beliefs without becoming observer truth.
- Reset seed clears prior-world cognition and awakening presentation state before recreating exactly one starter set.
- Package secret scanning identifies plausible API-key tokens without flagging ordinary hyphenated words.

### Known post-publication acceptance defects

- Independent functional review found that the published v0.4.0 implementation exposed absolute known-terrain coordinates through `view_map`, injected complete beliefs into ordinary prompts, mutated restored snapshot history on load, and did not preserve present-empty task or key-item collections. Those defects are corrected by v0.4.0.post1; v0.4.0 itself did not pass independent functional review.

### Security

- The intended boundary is that Ari-facing map, journal, notebook, belief, and prompt paths remain separated from hidden observer truth.
- Public package validation continues to reject secrets, private runtime artifacts, and generated local state.

### Tests

- Added initial coverage for initialization, non-capacity key items, non-droppability, migration idempotence, unsupported hypotheses, view actions, snapshot/restart, clean reset, and prompt restraint. Independent review later found semantic gaps in the A4, A7, and A10 tests; v0.4.0.post1 replaces or strengthens those checks.

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

See the repository history for earlier release details.
