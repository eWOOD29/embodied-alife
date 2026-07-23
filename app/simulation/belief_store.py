from __future__ import annotations

from typing import Any

from app.simulation.cognition import BeliefRecord, BeliefStatus, Provenance, migrate_legacy_beliefs


class BeliefStore(dict[str, BeliefRecord]):
    """Compatibility mapping that upgrades legacy string belief writes in place."""

    def __init__(self, value: Any = None) -> None:
        super().__init__()
        for key, record in migrate_legacy_beliefs(value).items():
            dict.__setitem__(self, key, record)

    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(value, BeliefRecord):
            record = value
        elif isinstance(value, dict) and "claim" in value:
            record = BeliefRecord.from_dict({"belief_id": str(value.get("belief_id") or key), **value})
        else:
            record = BeliefRecord(
                belief_id=str(key),
                claim=str(value),
                confidence=0.5,
                basis="Subjective model belief update; not observer truth.",
                status=BeliefStatus.WORKING.value,
                first_formed_at=0.0,
                last_tested_at=None,
                source_type="inference",
                provenance=Provenance("model_belief_update", source_id=str(key)),
            )
        dict.__setitem__(self, str(key), record)
