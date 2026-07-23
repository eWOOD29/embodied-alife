from __future__ import annotations

from typing import Any

from app.simulation.cognition import BeliefRecord, BeliefStatus, Provenance, migrate_legacy_beliefs


class BeliefValue(dict[str, Any]):
    """JSON-native structured belief with attribute-style access."""

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        if name == "provenance" and isinstance(value, dict):
            return Provenance.from_dict(value)
        return value

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class BeliefStore(dict[str, BeliefValue]):
    """Compatibility mapping that upgrades legacy string belief writes in place."""

    def __init__(self, value: Any = None) -> None:
        super().__init__()
        for key, record in migrate_legacy_beliefs(value).items():
            self[key] = record

    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(value, BeliefValue):
            structured = value
        elif isinstance(value, BeliefRecord):
            structured = BeliefValue(value.to_dict())
        elif isinstance(value, dict) and "claim" in value:
            structured = BeliefValue(BeliefRecord.from_dict({"belief_id": str(value.get("belief_id") or key), **value}).to_dict())
        else:
            structured = BeliefValue(BeliefRecord(
                belief_id=str(key),
                claim=str(value),
                confidence=0.5,
                basis="Subjective model belief update; not observer truth.",
                status=BeliefStatus.WORKING.value,
                first_formed_at=0.0,
                last_tested_at=None,
                source_type="inference",
                provenance=Provenance("model_belief_update", source_id=str(key)),
            ).to_dict())
        dict.__setitem__(self, str(key), structured)
