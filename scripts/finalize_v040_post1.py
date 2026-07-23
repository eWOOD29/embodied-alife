from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "398ccf981bd7d3d018e8e40977fb3f6936a48772"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


baseline_changelog = subprocess.check_output(
    ["git", "show", f"{BASELINE}:CHANGELOG.md"], cwd=ROOT, text=True, encoding="utf-8"
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
changelog = baseline_changelog.replace("## [Unreleased]\n\n", "## [Unreleased]\n\n" + post1, 1)
changelog = changelog.replace(
    "- Normal decision context includes compact cognitive-tool summaries rather than complete cognitive stores.\n",
    "- v0.4.0 intended to use compact cognitive-tool summaries; independent review found complete belief injection, corrected in v0.4.0.post1.\n",
)
changelog = changelog.replace(
    "- Ari-facing map, journal, notebook, belief, and prompt paths remain separated from hidden observer truth.\n",
    "- v0.4.0 intended to separate Ari-facing and observer state; independent review found absolute map-coordinate leakage, corrected in v0.4.0.post1.\n",
)
changelog = changelog.replace(
    "- Added coverage for initialization, non-capacity key items, non-droppability, migration idempotence, unsupported hypotheses, view-action truth boundaries, snapshot/restart fidelity, clean reset, and prompt restraint.\n",
    "- Added initial coverage for these areas; independent review found semantic gaps in A4, A7, and A10, corrected by v0.4.0.post1.\n",
)
write("CHANGELOG.md", changelog)

doc = read("docs/COGNITIVE_STATE.md")
doc = doc.replace("Version 0.4.0 establishes", "Version 0.4.0, corrected by the 0.4.0.post1 remediation, establishes", 1)
doc = doc.replace(
    "The map view uses perceived terrain and Ari-authored or inferred markers; it never exposes the observer's complete world map, hidden entities, resources, or exact unlearned coordinates.",
    "The map view converts internally stored known terrain into offsets, directions, and distances relative to Ari's current subjective origin. Ari-authored or inferred markers are sanitized the same way; the view never returns raw absolute tile keys, the observer's complete world map, hidden entities, hidden resources, cave truth, or recipes.",
)
doc = doc.replace(
    "Pre-v0.4.0 state loads with safe defaults, and legacy belief dictionaries migrate into structured subjective beliefs with migration provenance.",
    "Pre-v0.4.0 state loads with safe defaults, and legacy belief dictionaries migrate into structured subjective beliefs with migration provenance. An absent `key_items` or `tasks` field receives legacy starter defaults; a field explicitly present as `{}` remains empty.",
)
doc = doc.replace(
    "The new stores serialize through current state and snapshots.",
    "The new stores serialize through current state and snapshots. Loading a snapshot restores the complete saved experiment payload without adding a snapshot-load event; load observability is stored outside that payload.",
)
doc = doc.replace(
    "Ordinary decision prompts receive compact cognitive counts and starter summaries rather than complete note, task, marker, belief, or episode stores.",
    "Ordinary decision prompts receive compact cognitive counts and bounded summaries rather than complete note, task, marker, belief, or episode stores. Belief summaries contain counts by epistemic status and at most six deterministically selected, truncated claim/basis entries.",
)
write("docs/COGNITIVE_STATE.md", doc)

write("pyproject.toml", read("pyproject.toml").replace('version = "0.4.0"', 'version = "0.4.0.post1"', 1))
write("app/version.py", read("app/version.py").replace('__version__ = "0.4.0"', '__version__ = "0.4.0.post1"', 1))

print("Finalized changelog, public cognition documentation, and synchronized post-release versions")
