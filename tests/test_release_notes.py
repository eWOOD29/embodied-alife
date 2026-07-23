from __future__ import annotations

import pytest

from scripts.release_notes import extract_release_notes


def test_extract_release_notes_returns_only_requested_version() -> None:
    changelog = """# Changelog

## [0.3.0] — 2026-07-23

### Added
- Better cognition.

### Fixed
- One bug.

## [0.2.9] — 2026-07-23

### Fixed
- Integrity.
"""
    notes = extract_release_notes(changelog, "0.3.0")
    assert "Better cognition" in notes
    assert "One bug" in notes
    assert "Integrity" not in notes


def test_extract_release_notes_requires_version_section() -> None:
    with pytest.raises(ValueError):
        extract_release_notes("# Changelog\n", "9.9.9")
