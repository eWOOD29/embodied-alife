from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

PROTECTED_ROOTS = {".env", ".venv", "data", ".git"}


class ApplyUpdateError(RuntimeError):
    pass


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def _safe_relative(relative: str) -> str:
    if not isinstance(relative, str) or not relative:
        raise ApplyUpdateError("managed paths must be non-empty strings")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ApplyUpdateError(f"unsafe managed path: {relative}")
    if "\\" in relative or ":" in path.parts[0]:
        raise ApplyUpdateError(f"unsafe managed path: {relative}")
    normalized = path.as_posix()
    if path.parts[0] in PROTECTED_ROOTS:
        raise ApplyUpdateError(f"refusing to manage protected path: {normalized}")
    return normalized


def _within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def wait_for_process(pid: int, timeout_seconds: float = 180.0) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    if os.name == "nt":
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
            if result == 0x00000102:
                raise ApplyUpdateError("timed out waiting for the application to stop")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(0.25)
    raise ApplyUpdateError("timed out waiting for the application to stop")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.update-tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def apply_update(
    *,
    project_root: Path,
    staged_path: Path,
    manifest: dict[str, Any],
    python_executable: str,
    uv_executable: str | None,
    run_dependency_sync: bool = True,
) -> Path:
    project_root = project_root.resolve()
    staged_path = staged_path.resolve()
    runtime_dir = project_root / "data" / "runtime"
    version = str(manifest["version"])
    log_path = runtime_dir / "update-worker.log"
    backup_root = runtime_dir / "update-backups" / f"before-{version}-{int(time.time())}"
    backup_root.mkdir(parents=True, exist_ok=True)

    new_paths = {_safe_relative(str(path)) for path in manifest.get("managed_paths", [])}
    installed_manifest_path = runtime_dir / "installed-update-manifest.json"
    old_manifest = _read_json(installed_manifest_path, {})
    old_paths = {_safe_relative(str(path)) for path in old_manifest.get("managed_paths", [])}
    touched_paths = sorted(new_paths | old_paths)
    preexisting: set[str] = set()

    _log(log_path, f"Applying update {version} from {staged_path}")
    for relative in touched_paths:
        current = project_root / relative
        if not _within(project_root, current):
            raise ApplyUpdateError(f"managed path escapes project root: {relative}")
        if current.is_file():
            preexisting.add(relative)
            _copy_file(current, backup_root / relative)
        elif current.exists() and not current.is_dir():
            raise ApplyUpdateError(f"unsupported existing path type: {relative}")

    try:
        for relative in sorted(old_paths - new_paths, reverse=True):
            target = project_root / relative
            if target.is_file():
                target.unlink()
                _remove_empty_parents(target.parent, project_root)
        for relative in sorted(new_paths):
            source = staged_path / relative
            if not _within(staged_path, source):
                raise ApplyUpdateError(f"staged path escapes update root: {relative}")
            if not source.is_file():
                raise ApplyUpdateError(f"staged update file is missing: {relative}")
            _copy_file(source, project_root / relative)
        if run_dependency_sync:
            _sync_dependencies(
                project_root=project_root,
                python_executable=python_executable,
                uv_executable=uv_executable,
                log_path=log_path,
            )
        installed = dict(manifest)
        installed["installed_at"] = datetime.now(UTC).isoformat()
        installed_manifest_path.write_text(json.dumps(installed, indent=2), encoding="utf-8")
        state_path = runtime_dir / "update-state.json"
        state = _read_json(state_path, {})
        state.update(
            {
                "current_version": version,
                "state": "installed",
                "installing": False,
                "update_available": False,
                "can_install": False,
                "last_installed_version": version,
                "last_install_result": "success",
                "error": None,
            }
        )
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        _log(log_path, f"Update {version} applied successfully")
        return backup_root
    except Exception as exc:
        _log(log_path, f"Update failed; rolling back: {exc}")
        _rollback(
            project_root=project_root,
            backup_root=backup_root,
            touched_paths=touched_paths,
            preexisting=preexisting,
        )
        state_path = runtime_dir / "update-state.json"
        state = _read_json(state_path, {})
        state.update(
            {
                "state": "error",
                "installing": False,
                "can_install": True,
                "last_install_result": f"failed: {exc}",
                "error": f"Update installation failed: {exc}",
            }
        )
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        raise


def _sync_dependencies(
    *,
    project_root: Path,
    python_executable: str,
    uv_executable: str | None,
    log_path: Path,
) -> None:
    if uv_executable:
        command = [uv_executable, "pip", "install", "--python", python_executable, "-e", "."]
    else:
        command = [python_executable, "-m", "pip", "install", "-e", "."]
    _log(log_path, f"Synchronizing dependencies: {' '.join(command)}")
    result = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    with log_path.open("a", encoding="utf-8") as handle:
        if result.stdout:
            handle.write(result.stdout)
        if result.stderr:
            handle.write(result.stderr)
    if result.returncode != 0:
        raise ApplyUpdateError(f"dependency synchronization exited with code {result.returncode}")


def _rollback(
    *,
    project_root: Path,
    backup_root: Path,
    touched_paths: list[str],
    preexisting: set[str],
) -> None:
    for relative in reversed(touched_paths):
        target = project_root / relative
        backup = backup_root / relative
        if relative in preexisting and backup.is_file():
            _copy_file(backup, target)
        elif target.is_file():
            target.unlink()
            _remove_empty_parents(target.parent, project_root)


def _remove_empty_parents(path: Path, stop: Path) -> None:
    while path != stop and path.is_dir():
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def restart_app(project_root: Path, python_executable: str, log_path: Path) -> None:
    command = [python_executable, "-m", "app.serve"]
    creationflags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    output = log_path.open("a", encoding="utf-8")
    try:
        subprocess.Popen(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
    finally:
        output.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a staged Embodied Artificial Life update")
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    project_root = Path(request["project_root"]).resolve()
    log_path = project_root / "data" / "runtime" / "update-worker.log"
    try:
        wait_for_process(int(request["parent_pid"]))
        apply_update(
            project_root=project_root,
            staged_path=Path(request["staged_path"]),
            manifest=request["manifest"],
            python_executable=str(request["python_executable"]),
            uv_executable=request.get("uv_executable"),
            run_dependency_sync=True,
        )
        if request.get("restart", True):
            restart_app(project_root, str(request["python_executable"]), log_path)
        return 0
    except Exception as exc:
        _log(log_path, f"Updater terminated with an error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
