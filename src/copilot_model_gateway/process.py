from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


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


def start_litellm(
    executable: Path,
    runtime_config: Path,
    host: str,
    port: int,
) -> int:
    command = [
        str(executable),
        "--config",
        str(runtime_config),
        "--host",
        host,
        "--port",
        str(port),
    ]
    print(f"Starting gateway at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        print("\nGateway stopped.")
        return 130
    except OSError as exc:
        print(f"Failed to start LiteLLM: {exc}", file=sys.stderr)
        return 1
