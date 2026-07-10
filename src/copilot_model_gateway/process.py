from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


def find_litellm_executable(root: Path) -> Path | None:
    candidates = [
        root / ".venv" / "Scripts" / "litellm.exe",
        root / ".venv" / "bin" / "litellm",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    discovered = shutil.which("litellm")
    return Path(discovered) if discovered else None


def _command(executable: Path, runtime_config: Path, host: str, port: int) -> list[str]:
    return [
        str(executable),
        "--config",
        str(runtime_config),
        "--host",
        host,
        "--port",
        str(port),
    ]


def _child_environment() -> dict[str, str]:
    """Return a UTF-8 environment for LiteLLM child processes.

    Windows commonly inherits a legacy cp1252 console encoding. LiteLLM prints a
    Unicode banner during startup, which can otherwise raise UnicodeEncodeError
    when stdout is redirected to the dashboard log file.
    """
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def start_litellm(
    executable: Path,
    runtime_config: Path,
    host: str,
    port: int,
) -> int:
    command = _command(executable, runtime_config, host, port)
    print(f"Starting gateway at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        return subprocess.call(command, env=_child_environment())
    except KeyboardInterrupt:
        print("\nGateway stopped.")
        return 130
    except OSError as exc:
        print(f"Failed to start LiteLLM: {exc}", file=sys.stderr)
        return 1


def start_litellm_background(
    executable: Path,
    runtime_config: Path,
    host: str,
    port: int,
    log_path: Path,
    pid_path: Path,
) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = _command(executable, runtime_config, host, port)
    log_handle = log_path.open("a", encoding="utf-8", errors="replace")
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        popen_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=_child_environment(),
            **popen_kwargs,
        )
    finally:
        log_handle.close()
    pid_path.write_text(
        json.dumps({"pid": process.pid, "host": host, "port": port}),
        encoding="utf-8",
    )
    return process


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def gateway_process_status(pid_path: Path) -> dict[str, Any]:
    if not pid_path.exists():
        return {"known": False, "running": False}
    try:
        payload = json.loads(pid_path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"known": False, "running": False}
    running = _pid_alive(pid)
    if not running:
        try:
            pid_path.unlink()
        except OSError:
            pass
    return {"known": True, "running": running, "pid": pid}


def stop_litellm_background(pid_path: Path) -> bool:
    status = gateway_process_status(pid_path)
    if not status.get("running"):
        return False
    pid = int(status["pid"])
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
            stopped = result.returncode == 0
        else:
            os.killpg(pid, signal.SIGTERM)
            stopped = True
    except OSError:
        stopped = False
    if stopped:
        try:
            pid_path.unlink()
        except OSError:
            pass
    return stopped
