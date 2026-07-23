from __future__ import annotations

import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = subprocess.check_output(
    ["git", "show", "398ccf981bd7d3d018e8e40977fb3f6936a48772:CHANGELOG.md"],
    cwd=root,
    text=True,
    encoding="utf-8",
)
post1 = '''## [0.4.0.post1] — 2026-07-23

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

'''
text = base.replace("## [Unreleased]\n\n", "## [Unreleased]\n\n" + post1, 1)
text = text.replace(
    "- Normal decision context includes compact cognitive-tool summaries rather than complete cognitive stores.\n",
    "- v0.4.0 intended to use compact cognitive-tool summaries; independent review found complete belief injection, corrected in v0.4.0.post1.\n",
)
text = text.replace(
    "- Ari-facing map, journal, notebook, belief, and prompt paths remain separated from hidden observer truth.\n",
    "- v0.4.0 intended to separate Ari-facing and observer state; independent review found absolute map-coordinate leakage, corrected in v0.4.0.post1.\n",
)
text = text.replace(
    "- Added coverage for initialization, non-capacity key items, non-droppability, migration idempotence, unsupported hypotheses, view-action truth boundaries, snapshot/restart fidelity, clean reset, and prompt restraint.\n",
    "- Added initial coverage for these areas; independent review found semantic gaps in A4, A7, and A10, corrected by v0.4.0.post1.\n",
)
(root / "CHANGELOG.md").write_text(text, encoding="utf-8")
