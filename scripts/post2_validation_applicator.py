from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "post2-validation-output.txt"


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    with OUTPUT.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n")
        handle.write(result.stdout)
        handle.write(result.stderr)
        handle.write(f"\nexit={result.returncode}\n\n")
    if result.returncode:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
        subprocess.run(["git", "add", "post2-validation-output.txt"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", "Capture post2 validation failure"], cwd=ROOT, check=True)
        subprocess.run(["git", "push", "origin", "HEAD:remediation/v0.4.0-post2"], cwd=ROOT, check=True)
        raise SystemExit(result.returncode)


def main() -> None:
    if OUTPUT.exists():
        OUTPUT.unlink()
    run(["python", "-m", "pytest", "-q", "tests/test_v040_remediation.py"])
    run(["python", "-m", "pytest", "-q"])
    run(["python", "-m", "compileall", "-q", "app", "tests", "scripts"])
    run(["python", "scripts/clean_generated.py"])
    run(["python", "scripts/validate_package.py", "--source"])

    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    for relative in ("post2-validation-output.txt", "scripts/post2_repair_applicator.py", "scripts/post2_validation_applicator.py"):
        path = ROOT / relative
        if path.exists():
            path.unlink()
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", "Finalize post2 remediation validation cleanup"], cwd=ROOT, check=True)
    run(["python", "scripts/build_release.py", "--output", "dist/embodied-alife-update.zip"])
    subprocess.run(["git", "push", "origin", "HEAD:remediation/v0.4.0-post2"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
