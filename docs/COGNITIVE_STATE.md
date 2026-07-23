# Cognitive-State Foundations

Version 0.4.0, corrected by the 0.4.0.post1 remediation, establishes Ari's experiment-scoped cognitive state without implementing the later goal-management, map-editing, notebook-editing, contradiction-learning, or layered-retrieval systems.

## Awakening and key items

A clean experiment begins with a one-time awakening context and three protected key items:

- Blank Field Map
- Task Journal
- Field Notebook

Key items are stored separately from quantity-based inventory. They do not consume carrying capacity and cannot be dropped, consumed, duplicated, or lost in this release line.

The Task Journal begins with four broad, non-omniscient reminders: assess the immediate surroundings, find reliable water, secure near-term food, and find or create a safe place to rest. They begin in `proposed` state and do not force an order or action.

## Structured stores

Agent state contains versioned, provenance-bearing stores for:

- tasks and subtasks;
- notes;
- subjective map markers;
- beliefs with epistemic status;
- short-term episodic events;
- awakening presentation state.

Beliefs remain subjective. They may be hypotheses, uncertain, or wrong, and are never treated as observer truth merely because Ari recorded them.

## View actions

Ari can use `view_map`, `view_task_journal`, and `view_notebook`. The map view converts internally stored known terrain into offsets, directions, and distances relative to Ari's current subjective origin. Ari-authored or inferred markers are sanitized the same way. It never returns raw absolute tile keys, the observer's complete world map, hidden entities, hidden resources, observer-only cave truth, or hidden recipes.

Routine viewing cannot request a durable memory write automatically.

## Persistence and reset

The stores serialize through current state and snapshots. Loading a snapshot restores the complete saved experiment payload without adding a snapshot-load event; load observability is stored outside that payload.

Pre-v0.4.0 state loads with safe defaults, and legacy belief dictionaries migrate into structured subjective beliefs with migration provenance. An absent `key_items` or `tasks` field receives legacy starter defaults; a field explicitly present as `{}` remains empty.

Restarting the application resumes the same experiment without duplicating populated starter items or tasks or replaying the awakening. Reset seed clears experiment-specific cognition and creates a fresh world with exactly one starter set.

## Context restraint

Ordinary decision prompts receive compact cognitive counts and bounded summaries rather than complete note, task, marker, belief, or episode stores. Belief summaries contain counts by epistemic status and at most six deterministically selected, truncated claim/basis entries. Nearby known terrain and known-location summaries are also capped.

Full in-world journal and notebook contents are retrieved through their view actions. The hard 16k allocator and layered retrieval policy remain future work.
