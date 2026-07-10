from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from collections import Counter, deque
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .client import list_models, test_model
from .generator import build_litellm_config, render_runtime_config
from .process import (
    find_litellm_executable,
    gateway_process_status,
    start_litellm_background,
    stop_litellm_background,
)
from .settings import ConfigurationError, load_env_file, load_gateway_config, update_env_file


class KeyUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(default="", max_length=4096)


class ModelTestRequest(BaseModel):
    model: str = Field(min_length=1, max_length=256)


class DashboardState:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.lock = threading.RLock()

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def config_path(self) -> Path:
        return self.root / "config" / "gateway.yaml"

    @property
    def runtime_path(self) -> Path:
        return self.root / ".runtime" / "litellm.yaml"

    @property
    def log_path(self) -> Path:
        return self.root / ".runtime" / "gateway.log"

    @property
    def pid_path(self) -> Path:
        return self.root / ".runtime" / "gateway.pid.json"

    def load(self):
        config = load_gateway_config(self.config_path)
        env = load_env_file(self.env_path)
        env.update(os.environ)
        return config, env

    def allowed_secret_names(self) -> set[str]:
        config = load_gateway_config(self.config_path)
        names = {config.master_key_env}
        names.update(profile.api_key_env for profile in config.profiles if profile.api_key_env)
        return {name for name in names if name}


def _is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    connect_host = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if ":" in connect_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((connect_host, port)) == 0
    except OSError:
        return False


def _wait_for_port_state(
    host: str,
    port: int,
    *,
    expected_open: bool,
    timeout: float,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_open(host, port) is expected_open:
            return True
        time.sleep(0.2)
    return _is_port_open(host, port) is expected_open


def _tail_text(path: Path, max_lines: int) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=max_lines))
    except OSError as exc:
        return f"Unable to read log: {exc}\n"


def _start_managed_gateway(
    state: DashboardState,
    config: Any,
    env: dict[str, str],
) -> dict[str, Any]:
    result = render_runtime_config(config, env, state.runtime_path)
    executable = find_litellm_executable(state.root)
    if not executable:
        raise HTTPException(
            status_code=400,
            detail="LiteLLM executable not found. Run gateway.bat setup.",
        )

    process = start_litellm_background(
        executable,
        result.path,
        config.host,
        config.port,
        state.log_path,
        state.pid_path,
    )

    deadline = time.time() + 25
    while time.time() < deadline:
        if _is_port_open(config.host, config.port):
            return {
                "ok": True,
                "pid": process.pid,
                "warnings": list(result.warnings),
                "deployments": len(result.deployments),
            }
        if process.poll() is not None:
            break
        time.sleep(0.3)

    log_tail = _tail_text(state.log_path, 35).strip()
    detail = "Gateway did not become ready."
    if process.poll() is not None:
        detail += f" LiteLLM exited with code {process.returncode}."
    if log_tail:
        detail += f"\n\nLast gateway log lines:\n{log_tail}"
    raise HTTPException(status_code=500, detail=detail)


def _build_status(state: DashboardState) -> dict[str, Any]:
    initialized = state.env_path.exists() and state.config_path.exists()
    result: dict[str, Any] = {
        "initialized": initialized,
        "root": str(state.root),
        "errors": [],
        "warnings": [],
        "profiles": [],
        "deployments": [],
        "aliases": [],
        "gateway": {
            "host": None,
            "port": None,
            "url": None,
            "online": False,
            "managed_process": gateway_process_status(state.pid_path),
        },
    }
    if not initialized:
        result["errors"].append("Run gateway.bat init or gateway.bat setup first.")
        return result

    try:
        config, env = state.load()
        rendered, deployments, warnings = build_litellm_config(config, env)
        _ = rendered
        result["warnings"] = list(warnings)
        result["gateway"].update(
            {
                "host": config.host,
                "port": config.port,
                "url": f"http://{config.host}:{config.port}",
                "online": _is_port_open(config.host, config.port),
                "auth_enabled": config.require_auth,
                "master_key_env": config.master_key_env,
                "master_key_configured": bool(env.get(config.master_key_env, "").strip()),
            }
        )

        for profile in config.profiles:
            key_name = profile.api_key_env
            key_configured = True if not key_name else bool(env.get(key_name, "").strip())
            result["profiles"].append(
                {
                    "id": profile.id,
                    "label": profile.label,
                    "enabled": profile.enabled,
                    "api_key_env": key_name,
                    "key_configured": key_configured,
                    "api_base": profile.api_base,
                    "models": [
                        {
                            "alias": model.alias,
                            "provider_model": model.model,
                            "enabled": model.enabled,
                        }
                        for model in profile.models
                    ],
                }
            )

        result["deployments"] = [
            {
                "alias": item.alias,
                "profile_id": item.profile_id,
                "profile_label": item.profile_label,
                "provider_model": item.provider_model,
            }
            for item in deployments
        ]
        alias_counts = Counter(item.alias for item in deployments)
        result["aliases"] = [
            {"name": alias, "deployments": count, "loaded": None}
            for alias, count in sorted(alias_counts.items())
        ]

        if result["gateway"]["online"]:
            api_key = env.get(config.master_key_env) if config.require_auth else None
            try:
                visible_models = list_models(result["gateway"]["url"], api_key)
                result["gateway"]["visible_models"] = visible_models
                visible_model_set = set(visible_models)
                for alias in result["aliases"]:
                    alias["loaded"] = alias["name"] in visible_model_set
            except RuntimeError as exc:
                result["gateway"]["probe_error"] = str(exc)
    except (ConfigurationError, FileNotFoundError, ValueError) as exc:
        result["errors"].append(str(exc))
    return result


def create_dashboard_app(root: Path) -> FastAPI:
    state = DashboardState(root)
    app = FastAPI(title="Copilot Model Gateway Dashboard", docs_url=None, redoc_url=None)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "::1", "testserver"],
    )

    web_root = state.root / "web"
    if web_root.exists():
        app.mount("/assets", StaticFiles(directory=web_root), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        index_path = web_root / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=500, detail="Dashboard web assets are missing")
        return FileResponse(index_path, headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    def status() -> JSONResponse:
        with state.lock:
            return JSONResponse(_build_status(state), headers={"Cache-Control": "no-store"})

    @app.post("/api/keys")
    def save_key(payload: KeyUpdate) -> dict[str, Any]:
        with state.lock:
            try:
                allowed = state.allowed_secret_names()
            except (ConfigurationError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if payload.name not in allowed:
                raise HTTPException(status_code=400, detail="Unknown secret name")
            update_env_file(state.env_path, {payload.name: payload.value.strip()})
            return {"ok": True, "name": payload.name, "configured": bool(payload.value.strip())}

    @app.get("/api/master-key")
    def master_key() -> dict[str, str]:
        with state.lock:
            try:
                config, env = state.load()
            except (ConfigurationError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            value = env.get(config.master_key_env, "").strip()
            if not value:
                raise HTTPException(status_code=404, detail="Gateway master key is not configured")
            return {"value": value}

    @app.post("/api/render")
    def render() -> dict[str, Any]:
        with state.lock:
            try:
                config, env = state.load()
                result = render_runtime_config(config, env, state.runtime_path)
                return {
                    "ok": True,
                    "path": str(result.path),
                    "deployments": len(result.deployments),
                    "warnings": list(result.warnings),
                }
            except (ConfigurationError, FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gateway/start")
    def start_gateway() -> dict[str, Any]:
        with state.lock:
            try:
                config, env = state.load()
                if _is_port_open(config.host, config.port):
                    managed = gateway_process_status(state.pid_path)
                    return {
                        "ok": True,
                        "already_running": True,
                        "managed": bool(managed.get("running")),
                    }
                return _start_managed_gateway(state, config, env)
            except (ConfigurationError, FileNotFoundError, ValueError, OSError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gateway/restart")
    def restart_gateway() -> dict[str, Any]:
        with state.lock:
            try:
                config, env = state.load()
                managed = gateway_process_status(state.pid_path)
                port_open = _is_port_open(config.host, config.port)

                if port_open and not managed.get("running"):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Port {config.port} is used by a process not started by this dashboard. "
                            "Stop that process before restarting the gateway."
                        ),
                    )

                if managed.get("running"):
                    if not stop_litellm_background(state.pid_path):
                        raise HTTPException(
                            status_code=500,
                            detail="Could not stop the managed LiteLLM process.",
                        )
                    if not _wait_for_port_state(
                        config.host,
                        config.port,
                        expected_open=False,
                        timeout=10,
                    ):
                        raise HTTPException(
                            status_code=500,
                            detail=f"Port {config.port} did not close after stopping LiteLLM.",
                        )

                return _start_managed_gateway(state, config, env)
            except HTTPException:
                raise
            except (ConfigurationError, FileNotFoundError, ValueError, OSError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gateway/stop")
    def stop_gateway() -> dict[str, Any]:
        with state.lock:
            stopped = stop_litellm_background(state.pid_path)
            return {"ok": stopped}

    @app.post("/api/test")
    def test(payload: ModelTestRequest) -> dict[str, Any]:
        with state.lock:
            try:
                config, env = state.load()
            except (ConfigurationError, FileNotFoundError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            base_url = f"http://{config.host}:{config.port}"
            api_key = env.get(config.master_key_env) if config.require_auth else None
        result = test_model(base_url, api_key, payload.model)
        return {
            "model": result.model,
            "ok": result.ok,
            "elapsed_ms": result.elapsed_ms,
            "message": result.message,
        }

    @app.get("/api/logs")
    def logs(lines: Annotated[int, Query(ge=20, le=1000)] = 160) -> dict[str, str]:
        return {"text": _tail_text(state.log_path, lines)}

    return app


def run_dashboard(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 4100,
    *,
    open_browser: bool = True,
) -> int:
    normalized = host.strip().lower()
    if normalized not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Dashboard may only bind to a loopback address")
    app = create_dashboard_app(root)
    url = f"http://{host}:{port}"
    print(f"Dashboard: {url}")
    print("Press Ctrl+C to stop the dashboard. The model gateway can keep running separately.")
    if open_browser:
        timer = threading.Timer(0.8, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
        return 0
    except KeyboardInterrupt:
        return 130
