# Cognitive-State Foundations

Version 0.4.0 establishes Ari's experiment-scoped cognitive state without implementing the later goal-management, map-editing, notebook-editing, contradiction-learning, or layered-retrieval systems.

## Awakening and key items

A clean experiment begins with a one-time awakening context and three protected key items:

- Blank Field Map
- Task Journal
- Field Notebook

Key items are stored separately from quantity-based inventory. They do not consume carrying capacity and cannot be dropped, consumed, duplicated, or lost in v0.4.0.

The Task Journal begins with four broad, non-omniscient reminders: assess the immediate surroundings, find reliable water, secure near-term food, and find or create a safe place to rest. They begin in `proposed` state and do not force an order or action.

## Structured stores

Agent state now contains versioned, provenance-bearing stores for:

- tasks and subtasks;
- notes;
- subjective map markers;
- beliefs with epistemic status;
- short-term episodic events;
- awakening presentation state.

Beliefs remain subjective. They may be hypotheses, uncertain, or wrong, and are never treated as observer truth merely because Ari recorded them.

## View actions

Ari can use `view_map`, `view_task_journal`, and `view_notebook`. These actions return only Ari-known content. The map view uses perceived terrain and Ari-authored or inferred markers; it never exposes the observer's complete world map, hidden entities, resources, or exact unlearned coordinates.

Routine viewing cannot request a durable memory write automatically.

## Persistence and reset

The new stores serialize through current state and snapshots. Pre-v0.4.0 state loads with safe defaults, and legacy belief dictionaries migrate into structured subjective beliefs with migration provenance.

Restarting the application resumes the same experiment without duplicating starter items or tasks or replaying the awakening. Reset seed clears experiment-specific notes, markers, non-starter beliefs, episodes, snapshots, events, model responses, and awakening presentation state, then creates a fresh world with exactly one starter set.

## Context restraint

Ordinary decision prompts receive compact cognitive counts and starter summaries rather than complete note, task, marker, belief, or episode stores. Full in-world contents are retrieved through the view actions. The hard 16k allocator and layered retrieval policy remain future work.
