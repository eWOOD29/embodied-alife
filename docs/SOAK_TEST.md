# Embodied Artificial Life Multi-Day Soak Test

Use this procedure after installing v0.3.2 or later. The purpose is to exercise long-horizon behavior, persistence, cognition, memory integrity, environmental hazards, and updater continuity in one clean experiment.

## Before starting

1. Confirm the dashboard version is v0.3.2 or later.
2. Confirm LM Studio shows the intended model as loaded and the dashboard model status is `mode: llm`, `available: true`.
3. Click **Reset seed** and choose either a recorded integer seed or leave it blank for a random seed.
4. Confirm the reset response states that a clean experiment was created.
5. Do not change models, prompts, or runtime settings during the primary run.

A reset clears world-specific events, model responses, snapshots, and active memories. It also creates new `run_id` and `world_generation_id` values.

## Primary run

1. Run at **1× or 10×**. Use 1× when actively observing and 10× for unattended progress. Do not use 100× for the primary audit because it can compress decision opportunities and obscure timing behavior.
2. Continue through at least **three complete simulated days** and at least **100 decisions**.
3. After day 1, save a named snapshot such as `soak-day-1`.
4. Restart the application once after saving the snapshot. Confirm the same run resumes and the event timeline records a restored runtime state.
5. Continue the same experiment after restart. Do not press Reset seed again.
6. Periodically open `/api/validation/readiness` to see which scenarios remain uncovered. This endpoint does not modify the simulation.

## Desired scenario coverage

The readiness report tracks:

- sleep and waking;
- memory consolidation;
- multiple day/night cycles;
- weather transitions and storm exposure;
- temperature stress;
- wolf or danger encounters;
- action interruptions;
- shelter construction and degradation;
- resource regeneration;
- snapshot activity;
- restart/restore continuity;
- verified memory commits;
- safe memory filtering or rejection;
- updater continuity.

The death path is reported separately and is not required for a healthy primary run. A later targeted test can cover death and post-death behavior.

## Quality gates

The diagnostic readiness report checks for:

- world day 3 or later;
- at least 100 decisions;
- at least 95% LLM decision success;
- at least 80% final action success;
- no duplicate engine or restore anomalies;
- no unresolved pending-memory candidate;
- Ari alive at export time.

These are audit thresholds, not claims that every lower result is a defect. A missed threshold should be interpreted with the event evidence in the diagnostic bundle.

## Finishing the run

1. Pause the simulation.
2. Open `/api/validation/readiness` and note any missing scenarios.
3. Click **Download diagnostic logs**.
4. Attach the resulting JSON file to the next ChatGPT project session.
5. Include any visible symptoms that occurred outside the export, such as browser disconnects, LM Studio crashes, or Windows restart behavior.

Do not edit the JSON before attaching it. The export excludes API keys, raw `.env` contents, authorization headers, and raw prompts.
