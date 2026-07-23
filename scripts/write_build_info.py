from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("commit")
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, default=Path("app/build_info.py"))
    args = parser.parse_args()

    text = (
        "from __future__ import annotations\n\n"
        f"BUILD_COMMIT = {args.commit!r}\n"
        f"BUILD_TIME_UTC = {datetime.now(UTC).isoformat()!r}\n"
        f"BUILD_VERSION = {args.version!r}\n"
    )
    args.output.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
