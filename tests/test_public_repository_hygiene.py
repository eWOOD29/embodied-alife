from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from scripts.privacy_scan import scan_tree, string_findings, structured_findings, validate_appdock

ROOT = Path(__file__).resolve().parents[1]


def _synthetic_private_path(separator: str = "\\") -> str:
    return "".join(("C:", separator, "Users", separator, "SyntheticOperator", separator, "PrivateWorkspace", separator, "embodied-alife"))


def test_public_tree_contains_no_private_machine_configuration_or_decoded_values() -> None:
    assert scan_tree(ROOT, include_runtime=False) == []


def test_appdock_manifest_is_project_relative_and_structurally_private() -> None:
    value = json.loads((ROOT / "appdock.json").read_text(encoding="utf-8"))
    assert validate_appdock(value) == []
    assert value["projectDirectory"] == "."
    assert value["workingDirectoryPolicy"] == "projectDirectory"
    assert value["command"] == ".venv\\Scripts\\python.exe"
    assert value["arguments"] == ["-m", "app.serve"]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _synthetic_private_path("\\"),
        lambda: _synthetic_private_path("/"),
        lambda: _synthetic_private_path("\\").replace("\\", "\\\\"),
        lambda: quote(_synthetic_private_path("\\"), safe=""),
        lambda: json.dumps(_synthetic_private_path("\\")),
        lambda: "FILE:///" + _synthetic_private_path("/").lower(),
        lambda: "synthetic-device.synthetic-tailnet.ts.net",
        lambda: "https://" + "drive.google.com/drive/folders/" + "synthetic",
        lambda: "api_key=" + "synthetic-secret-value-1234567890",
    ],
)
def test_privacy_scanner_detects_raw_decoded_case_and_separator_variants(factory) -> None:
    assert string_findings(factory(), context="synthetic")


def test_privacy_scanner_recurses_nested_mappings_lists_and_json_encoded_strings() -> None:
    private_path = _synthetic_private_path("\\")
    value = {
        "outer": [
            {"nested": json.dumps({"path": private_path})},
            {"list": [quote(private_path, safe="")]},
        ]
    }
    assert structured_findings(value, context="synthetic")


def test_runtime_and_diagnostic_artifacts_are_not_tracked() -> None:
    forbidden_tracked_roots = [ROOT / "data" / "runtime", ROOT / "data" / "agent_memory", ROOT / "logs"]
    findings: list[str] = []
    for root in forbidden_tracked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.name != ".gitkeep":
                findings.append(str(path.relative_to(ROOT)))
    assert findings == []
