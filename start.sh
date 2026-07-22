#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
unset PYTHONPATH || true
if [[ -f .venv/Scripts/python.exe ]]; then
  PY=.venv/Scripts/python.exe
elif [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  echo "Project virtual environment not found. Run: uv venv && uv pip install --python .venv/Scripts/python.exe -e '.[dev]'" >&2
  exit 1
fi
exec "$PY" -m app.serve
