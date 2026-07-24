from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for relative in ("app/diagnostics.py",):
    path = ROOT / relative
    data = path.read_bytes()
    if b"\x00" in data:
        data = data.replace(b"\x00", b"\\x00")
        path.write_bytes(data)

print("post5 phase6 applied")
