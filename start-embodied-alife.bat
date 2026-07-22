@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=
if not exist ".venv\Scripts\python.exe" (
  echo Project virtual environment not found.
  echo Run: uv venv
  echo Then: uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
  exit /b 1
)
".venv\Scripts\python.exe" -m app.serve
endlocal
