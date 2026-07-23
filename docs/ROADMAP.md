# Embodied Artificial Life — Roadmap

_Last updated: 2026-07-23_  
_Current planning baseline: **v0.3.4**_

This roadmap defines the order of work after the v0.2.9–v0.3.4 stabilization cycle. It is intentionally organized around dependency, learning value, and player-like experience rather than feature count.

The project is no longer trying to improve a reactive LLM action selector one local correction at a time. The next objective is to build a durable cognitive and survival architecture in which Ari can guide an open-ended adventure while the deterministic world remains physically authoritative.

## Product vision

Build a local, inspectable artificial-life and survival experience in which Ari:

- awakens without knowledge of the generated world;
- experiences a vulnerable body, partial perception, uncertainty, and consequences;
- chooses goals, takes risks, forms beliefs, makes mistakes, learns, and develops preferences;
- uses in-world cognitive tools such as a map, task journal, and notebook;
- can survive, stabilize, explore, understand, improve, and eventually thrive;
- remains meaningfully guided by the local language model rather than becoming a scripted survival bot.

The experience should feel closer to an unscripted single-character RPG or survival game than a benchmark loop, while remaining scientifically inspectable and reproducible.

## Non-negotiable design principles

1. **Ari leads the adventure.** Qwen chooses goals, priorities, interpretations, interruptions, risk tolerance, and personal projects.
2. **The world decides what physically happens.** The LLM cannot declare success, alter state directly, or bypass deterministic rules.
3. **Structure supports agency rather than replacing it.** Deterministic systems store goals, track progress, execute bounded movement, detect pathological repetition, and preserve continuity.
4. **Beliefs may be wrong.** Ari may form hypotheses or premature conclusions. Evidence can strengthen, weaken, contradict, or overturn them.
5. **Ari and the observer see different worlds.** Ari receives only partial, uncertain knowledge; the observer retains complete truth for auditing.
6. **Cognition is layered.** Immediate context, recent experience, notes, tasks, beliefs, maps, and sleep-consolidated memory have distinct roles and lifetimes.
7. **Sixteen thousand tokens is the minimum design target.** Larger contexts may improve performance, but ordinary decisions must remain viable within a 16k window.
8. **Failures should usually teach before they kill.** Early experimentation may cause injury, illness, lost time, or resource costs without routinely causing instant death.
9. **Public-source hygiene is mandatory.** No personal paths, private hostnames, credentials, runtime data, or internal-only handoff material belongs in the public repository.
10. **Every major behavior remains diagnosable.** Logs must distinguish perception, retrieved cognition, model proposal, policy transformation, controller execution, world outcome, and later learning.

## Current baseline

The v0.2.9–v0.3.4 sequence established:

- outcome-verified durable memory writes;
- clean experiment resets;
- stable run and world-generation identity;
- executable-action and reachability guidance;
- diagnostic bundles and soak-readiness reporting;
- public-repository cleanup and hygiene checks;
- resource-depletion and interaction-radius consistency;
- hunger-scale clarification and unnecessary-eating prevention;
- local loop detection for failed actions and stationary looking.

The current limitation is architectural: Ari can make locally valid decisions but does not yet preserve goals, measure task progress, manage attention, or use spatial and cognitive tools well enough to sustain an adventure.

---

# Phase 1 — Adventure foundation

## v0.4.0 — Awakening, key items, and cognitive state foundations

**Goal:** Establish Ari as a character with an in-world starting frame and durable external cognitive tools.

### Scope

- Add the agreed awakening narrative:

  > I wake beneath an unfamiliar sky with no memory of how I arrived. My body feels real, vulnerable, and entirely my responsibility. I do not know this land, what lives here, or whether anyone else is nearby.
  >
  > I have only a few possessions: a blank map, a task journal, and a field notebook. The journal contains a handful of basic survival reminders—find water, secure food, and establish somewhere safe to rest—but what I do beyond that is up to me.
  >
  > If I am going to survive here, and perhaps eventually build a life worth living, I should begin by understanding my situation. The map and task journal may be the best place to start.

- Add non-droppable key items:
  - blank field map;
  - task journal;
  - field notebook;
  - implied writing implement.
- Add starter tasks:
  - assess immediate surroundings;
  - find a reliable source of water;
  - secure enough food for the near future;
  - find or create a safe place to rest.
- Add structured schemas and persistence for:
  - notes;
  - tasks and subtasks;
  - map markers;
  - beliefs with epistemic status;
  - short-term episodic events.
- Preserve all new state across restart and snapshots.
- Clear all experiment-specific cognition on Reset seed.

### Acceptance criteria

- A clean reset creates the same starter key items and tasks but no prior-world cognition.
- Ari can view each key item through an action without receiving observer truth.
- Key items do not consume ordinary carrying capacity and cannot be accidentally dropped.
- The first model context makes viewing the map or journal naturally attractive without hard-coding the first action.
- Diagnostic export includes every cognitive store and its provenance.

## v0.4.1 — Hybrid goal and task layer

**Goal:** Give Ari persistent intentions without making the deterministic system choose Ari's life.

### Ari controls

- which goal matters;
- why it matters;
- task priority;
- risk tolerance;
- whether a discovery justifies interruption;
- whether to continue, suspend, branch, abandon, or complete a task;
- creation of personal goals beyond starter survival tasks.

### System controls

- persistent storage and task lifecycle;
- progress metrics;
- task-to-map and task-to-note links;
- interruption bookkeeping;
- protection against accidental plan replacement;
- bounded execution of a chosen task;
- non-progress and circular-route detection.

### Required task lifecycle

- proposed;
- active;
- suspended;
- blocked;
- completed;
- abandoned;
- superseded.

Each transition records the initiating model decision, reason, evidence, and timestamp.

### Acceptance criteria

- An active exploration task survives nearby low-relevance resource sightings.
- Qwen may deliberately suspend that task, but must choose an explicit interruption disposition.
- “Mark for later and continue” prevents the same object from repeatedly forcing deliberation.
- The controller reports progress without deciding the objective.
- Plans update the active task rather than silently replacing it every turn.

## v0.4.2 — Partial map and frontier exploration

**Goal:** Turn exploration into purposeful, Ari-guided navigation rather than repeated compass-direction selection.

### Scope

- Add Ari's partial map as structured in-world knowledge.
- Support uncertain markers, approximate locations, stale resource markers, confidence, notes, and named landmarks.
- Add actions:
  - view map;
  - add, rename, annotate, archive, or remove marker;
  - set or clear destination;
  - link marker to task or note.
- Compute deterministic exploration frontiers from Ari's known terrain.
- Let Qwen choose which frontier or destination matters.
- Allow the controller to execute bounded routes toward the chosen frontier and interrupt on meaningful changes.
- Track net displacement, new tiles, revisits, circular routes, and progress per active task.

### Acceptance criteria

- Ari can distinguish explored, uncertain, and unknown space.
- Exploration tasks select a destination or frontier instead of only “move north.”
- A completed route produces measurable new-map progress.
- Circular movement without new tiles triggers reflection or replanning.
- The map never exposes unobserved observer coordinates or hidden entities.

## v0.4.3 — Informative inspection and object characterization

**Goal:** Make inspection a real epistemic action and remove it when it cannot reveal anything new.

### Scope

- Define hidden and visible attributes for inspectable object classes.
- Make inspection return deterministic evidence such as appearance, smell, texture, tracks, damage, ripeness, animal feeding signs, material quality, or change since last observation.
- Track per-object and per-type characterization levels.
- Track known attributes, unresolved questions, conflicting evidence, and last inspection conditions.
- Remove `inspect` from affordances for already-characterized unchanged objects unless:
  - the object changed;
  - prior inspection was incomplete;
  - Ari gained a relevant tool or knowledge;
  - Ari deliberately rechecks a disputed belief.
- Separate evidence from Ari's interpretation.

### Acceptance criteria

- Inspection reveals information not already present in ordinary perception.
- Repeated inspection of an unchanged characterized object is not offered by default.
- Ari can form an incorrect interpretation from valid evidence.
- Observer diagnostics show hidden truth, evidence revealed, Ari's belief, and later contradictions separately.

---

# Phase 2 — Cognitive architecture

## v0.5.0 — Sixteen-k context budget and layered retrieval

**Goal:** Make ordinary cognition reliable within a 16k context window.

### Cognitive layers

1. Immediate working context
2. Short-term episodic buffer
3. Searchable field notes
4. Task journal and prospective memory
5. Beliefs and self-model
6. Sleep-consolidated long-term memory

### Scope

- Add a hard application-side token budget with configurable allocations.
- Target ordinary decision prompts of approximately 8k–12k tokens.
- Reserve output and emergency headroom within 16k.
- Compress local terrain into task-relevant summaries rather than sending raw large tile lists.
- Retrieve a small, attributable set from each relevant cognitive store.
- Record why each item was included or excluded.
- Dynamically shift budget by decision type: danger, exploration, planning, crafting, social, or reflection.

### Acceptance criteria

- Ordinary decisions remain below the configured 16k limit.
- No prompt silently exceeds the budget.
- Diagnostics show token allocation by section and retrieval rationale.
- Larger configured contexts improve breadth without being required for correctness.

## v0.5.1 — Notes and short-term episodic memory

**Goal:** Give Ari reliable recent continuity and intentional waking external memory.

### Scope

- Maintain a compact recent-experience buffer of meaningful events, interruptions, discoveries, decisions, and unfinished intentions.
- Automatically summarize older short-term events while preserving source links.
- Add notebook actions to create, edit, search, tag, link, archive, and delete notes.
- Allow promotion from note to task, map marker, belief evidence, or sleep-consolidation candidate.
- Keep notes searchable but out of ordinary context unless relevant.

### Acceptance criteria

- Ari can answer why they came to a location or what they were doing before interruption.
- Notes survive restart and snapshots within an experiment.
- Search returns relevant notes without dumping the entire notebook.
- Temporary details do not automatically become permanent memory.

## v0.5.2 — Belief lifecycle and learning from contradiction

**Goal:** Allow uncertain, false, and evolving beliefs without confusing them with world truth.

### Scope

Beliefs include:

- claim;
- confidence;
- basis;
- status: hypothesis, working, confirmed, disputed, rejected;
- first formed and last tested times;
- supporting and contradicting evidence;
- source type: perception, inference, memory, note, testimony, or bodily consequence.

Qwen may create unsupported hypotheses. The system does not forbid them; it preserves provenance and presents later evidence.

### Acceptance criteria

- Ari may believe an unproven berry is safe.
- Later illness can contradict and weaken that belief.
- Belief revision is model-guided, not silently imposed by observer truth.
- The dashboard clearly separates truth, evidence, and belief.

## v0.5.3 — Sleep consolidation and long-term memory

**Goal:** Make sleep the primary gateway to durable autobiographical and semantic memory.

### Scope

- Waking experiences enter episodic memory, notes, beliefs, and protected consolidation candidates.
- Sleep reflection selects important episodes, lessons, questions, commitments, and self-model changes.
- Consolidation can merge duplicates, strengthen or weaken beliefs, preserve contradictions, and create next-day tasks.
- Critical events may receive protected pending status while awake but do not become ordinary durable memory until consolidation.
- Long-term storage persists indefinitely within the experiment, while retrieval remains selective.

### Acceptance criteria

- Ordinary waking actions no longer write long-term memory directly.
- Important experiences survive until the next sleep.
- Sleep produces a small number of high-value memories rather than event summaries.
- Reset seed clears all experiment-specific long-term memory.
- Restart and snapshot restore the entire consolidation state.

## v0.5.4 — Emerging personality and self-model

**Goal:** Let Ari's personality develop from experience rather than remain a fixed prompt costume.

### Scope

Track inspectable tendencies such as:

- curiosity;
- risk tolerance;
- persistence;
- novelty seeking;
- resource conservatism;
- attachment to places;
- trust;
- comfort with uncertainty;
- social preference.

The model may also form explicit self-beliefs. Structured tendencies summarize repeated behavior and reflection but do not dictate individual choices.

### Acceptance criteria

- Personality changes require repeated evidence or explicit reflection.
- One isolated action cannot silently rewrite identity.
- Ari can disagree with or revise their own self-beliefs.
- Observer diagnostics distinguish measured tendencies from Ari's self-narrative.

---

# Phase 3 — Richer survival world

## v0.6.0 — Plant diversity, uncertain edibility, and poisoning

**Goal:** Create meaningful ecological uncertainty and recoverable learning.

### Initial plant set

- safe berry bush;
- visually similar poisonous berry bush;
- edible leafy plant;
- irritating or mildly toxic plant;
- medicinal herb;
- fibrous crafting plant;
- thorny bush;
- uncertain mushroom;
- nut-bearing shrub or tree;
- distinctive flowering landmark plant.

### Scope

- Give related safe and unsafe species overlapping but distinguishable clues.
- Add delayed, graded poisoning with nausea, pain, energy penalty, hydration drain, and slow health loss.
- Track suspected cause and symptom timeline without revealing certainty to Ari.
- Allow recovery through time, safe food, water, rest, sleep, shelter, and medicinal resources.
- Avoid routine instant death from one reasonable experiment.

### Acceptance criteria

- Ari cannot identify every plant from ordinary perception.
- Inspection reveals clues but not always certainty.
- Eating a toxic plant produces delayed, auditable symptoms.
- Ari has time to form hypotheses and respond.
- Repeated reckless exposure can still become fatal.

## v0.6.1 — Recovery, rest, and bodily consequences

**Goal:** Make injury and recovery strategically meaningful.

### Scope

- Safe food restores a small amount of health.
- Rest restores more health when hydration, nutrition, temperature, and safety permit.
- Sleep in shelter provides the strongest ordinary recovery.
- Poisoning, exposure, dehydration, starvation, pain, and activity reduce healing.
- Add qualitative model-facing symptoms while retaining exact observer values.

### Acceptance criteria

- Health can recover without resetting.
- Shelter and stabilization materially improve recovery.
- Exact game-like values remain observer-facing; Ari receives embodied descriptions.
- Recovery is slow enough that mistakes matter.

## v0.6.2 — Expanded animal ecology

**Goal:** Make animals sources of danger, opportunity, and environmental evidence rather than moving resource icons.

### Initial ecological roles

- harmless small animal;
- prey animal;
- scavenger;
- territorial animal;
- predator;
- birds or insects that provide environmental cues.

### Scope

- Add routines, territoriality, migration, fleeing, stalking, scavenging, and resource competition.
- Let tracks, feeding behavior, calls, and flight behavior reveal clues.
- Preserve seeded reproducibility.
- Avoid exposing exact animal intent to Ari.

### Acceptance criteria

- Animal behavior can inform plant safety, nearby water, danger, or environmental change.
- Ari can form beliefs about animal patterns from evidence.
- Different species create materially different decisions.

---

# Phase 4 — Stabilization, tools, and thriving

## v0.7.x — Shelter, crafting, storage, and routine

Planned systems:

- richer shelter choices and repair;
- containers and food storage;
- tools;
- fire;
- water collection and purification;
- food preparation;
- clothing and insulation;
- spoilage and material quality;
- repeatable routines and home-base attachment.

These systems should be introduced only after goal persistence, mapping, inspection, and layered memory are reliable.

## v0.8.x — Social world and relationships

Do not begin multi-agent work until single-agent cognition and long-duration testing are stable.

Potential scope:

- multiple separately embodied agents;
- communication limited by distance and conditions;
- individual recognition;
- trust and reputation;
- cooperation, conflict, promises, and deception;
- social memory;
- shared or conflicting maps and knowledge;
- emergent groups, norms, and culture.

---

# Cross-cutting engineering work

These items may be delivered alongside the relevant feature releases rather than as separate product versions.

## Evaluation and observability

- deterministic experiment harness;
- prompt, schema, and policy versioning;
- decision inspector;
- action, task, map, belief, note, and memory provenance;
- loop and non-progress metrics;
- context-budget telemetry;
- fixed-seed model comparisons;
- richer soak tests and scenario coverage.

## Model and runtime support

- non-mutating Test model workflow;
- named local-model profiles;
- compatibility modes for OpenAI-compatible servers;
- app-side context budgeting;
- latency and token telemetry;
- fallback-mode parity where feasible.

## Operations and public quality

- updater integration testing;
- documentation consistency checks;
- public-repository hygiene tests;
- migrations and rollback for cognitive-state schema changes;
- portable installation and remote-access guidance.

---

# Explicitly out of scope for the next development cycle

Until Phase 1 and Phase 2 are validated, do not prioritize:

- multiple LLM agents;
- procedural story quests authored by the system;
- combat-heavy mechanics;
- large crafting trees;
- seasons or large-scale climate simulation;
- persistent identity across Reset seed;
- cloud-hosted multiplayer;
- hidden monetization or service dependencies;
- direct host-file, shell, browser, or arbitrary-code access for Ari.

---

# Release planning rule

Before implementation begins for a milestone:

1. break the milestone into explicit tasks and migrations;
2. define acceptance tests and diagnostic additions;
3. verify the change fits the 16k minimum context target;
4. identify Ari-versus-observer knowledge boundaries;
5. define what Qwen chooses and what the deterministic layer enforces;
6. preserve clean experiment-reset semantics;
7. keep each release independently installable and auditable.

The immediate next action is **document review only**. Implementation remains paused until the project owner reviews and approves this roadmap and the canonical scope/architecture note.