from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one occurrence, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")

    replace_once(
        "app/simulation/cognition.py",
        '    text = str(value).replace("\\n", " ").strip()\n',
        '    text = str(value).strip()\n',
    )
    replace_once(
        "app/simulation/perception.py",
        '                visible_tiles.append({"x": x - ax, "y": y - ay, "terrain": terrain})\n',
        '                visible_tiles.append({"offset_east": x - ax, "offset_south": y - ay, "terrain": terrain})\n',
    )
    replace_once(
        "app/simulation/perception.py",
        '        {"x": world_x - ax, "y": world_y - ay, "terrain": terrain}\n',
        '        {"offset_east": world_x - ax, "offset_south": world_y - ay, "terrain": terrain}\n',
    )

    run("git", "add", "app/simulation/cognition.py", "app/simulation/perception.py")
    run("git", "commit", "-m", "Preserve durable text and remove Ari-facing x-y keys")

    for relative in (
        "post2-runner-output.txt",
        "post2-repair-output.txt",
        ".github/workflows/post2-remediation.yml",
        "scripts/post2_remediation_applicator.py",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()

    run("python", "-m", "pytest", "-q", "tests/test_v040_remediation.py")
    run("python", "-m", "pytest", "-q")
    run("python", "-m", "compileall", "-q", "app", "tests", "scripts")
    run("python", "scripts/clean_generated.py")
    run("python", "scripts/validate_package.py", "--source")

    self_path = ROOT / "scripts/post2_repair_applicator.py"
    if self_path.exists():
        self_path.unlink()
    run("git", "add", "-A")
    run("git", "commit", "-m", "Remove temporary post2 remediation tooling")

    run("python", "scripts/build_release.py", "--output", "dist/embodied-alife-update.zip")
    run("git", "push", "origin", "HEAD:remediation/v0.4.0-post2")


if __name__ == "__main__":
    main()
