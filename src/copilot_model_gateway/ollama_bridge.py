from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .generator import build_litellm_config
from .settings import load_env_file, load_gateway_config


class OllamaBridgeState:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def config_path(self) -> Path:
        return self.root / "config" / "gateway.yaml"

    def load(self):
        config = load_gateway_config(self.config_path)
        env = load_env_file(self.env_path)
        env.update(os.environ)
        _, deployments, _ = build_litellm_config(config, env)
        aliases = sorted({item.alias for item in deployments})
        return config, env, aliases

    def gateway_connection(self) -> tuple[str, str | None, list[str]]:
        config, env, aliases = self.load()
        base_url = f"http://{config.host}:{config.port}"
        api_key = env.get(config.master_key_env) if config.require_auth else None
        return base_url, api_key, aliases


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest(model: str) -> str:
    return hashlib.sha256(model.encode("utf-8")).hexdigest()


def _model_record(model: str) -> dict[str, Any]:
    return {
        "name": model,
        "model": model,
        "modified_at": _now_iso(),
        "size": 0,
        "digest": _digest(model),
        "details": {
            "parent_model": "",
            "format": "cloud",
            "family": "deepseek" if "deepseek" in model.lower() else "gateway",
            "families": ["deepseek" if "deepseek" in model.lower() else "gateway"],
            "parameter_size": "remote",
            "quantization_level": "none",
        },
    }


def _resolve_model(requested: str, aliases: list[str]) -> str | None:
    requested = requested.strip()
    if requested in aliases:
        return requested
    if requested.endswith(":latest") and requested[:-7] in aliases:
        return requested[:-7]
    return None


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _openai_chat_body(payload: dict[str, Any], model: str) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages must be an array")
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": bool(payload.get("stream", True)),
    }
    options = payload.get("options")
    if isinstance(options, dict):
        mapping = {
            "temperature": "temperature",
            "top_p": "top_p",
            "seed": "seed",
            "stop": "stop",
            "num_predict": "max_tokens",
        }
        for source, target in mapping.items():
            if source in options:
                body[target] = options[source]
    if "tools" in payload:
        body["tools"] = payload["tools"]
    if "format" in payload and payload["format"] == "json":
        body["response_format"] = {"type": "json_object"}
    return body


def _ollama_message(openai_message: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": openai_message.get("role") or "assistant",
        "content": openai_message.get("content") or "",
    }
    if openai_message.get("tool_calls"):
        message["tool_calls"] = openai_message["tool_calls"]
    return message


async def _chat_non_stream(
    base_url: str,
    api_key: str | None,
    model: str,
    body: dict[str, Any],
) -> JSONResponse:
    started = time.perf_counter_ns()
    request_body = dict(body)
    request_body["stream"] = False
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers=_headers(api_key),
            json=request_body,
        )
    if response.is_error:
        return _error(f"Gateway HTTP {response.status_code}: {response.text}", response.status_code)
    payload = response.json()
    choice = (payload.get("choices") or [{}])[0]
    usage = payload.get("usage") or {}
    return JSONResponse(
        {
            "model": model,
            "created_at": _now_iso(),
            "message": _ollama_message(choice.get("message") or {}),
            "done": True,
            "done_reason": choice.get("finish_reason") or "stop",
            "total_duration": time.perf_counter_ns() - started,
            "load_duration": 0,
            "prompt_eval_count": usage.get("prompt_tokens", 0),
            "eval_count": usage.get("completion_tokens", 0),
        }
    )


async def _chat_stream(
    base_url: str,
    api_key: str | None,
    model: str,
    body: dict[str, Any],
) -> AsyncIterator[bytes]:
    started = time.perf_counter_ns()
    request_body = dict(body)
    request_body["stream"] = True
    finish_reason = "stop"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=_headers(api_key),
            json=request_body,
        ) as response:
            if response.is_error:
                raw = (await response.aread()).decode("utf-8", errors="replace")
                error_item = {"error": f"Gateway HTTP {response.status_code}: {raw}"}
                yield (json.dumps(error_item) + "\n").encode()
                return
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                message = _ollama_message(delta)
                if not message.get("content") and not message.get("tool_calls"):
                    continue
                item = {
                    "model": model,
                    "created_at": _now_iso(),
                    "message": message,
                    "done": False,
                }
                yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
    final_item = {
        "model": model,
        "created_at": _now_iso(),
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": finish_reason,
        "total_duration": time.perf_counter_ns() - started,
        "load_duration": 0,
        "prompt_eval_count": 0,
        "eval_count": 0,
    }
    yield (json.dumps(final_item, ensure_ascii=False) + "\n").encode("utf-8")


async def _generate_non_stream(
    base_url: str,
    api_key: str | None,
    model: str,
    prompt: str,
    system: str,
    options: dict[str, Any],
) -> JSONResponse:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = _openai_chat_body(
        {"messages": messages, "stream": False, "options": options}, model
    )
    response = await _chat_non_stream(base_url, api_key, model, body)
    raw = json.loads(response.body)
    if response.status_code >= 400:
        return response
    message = raw.pop("message", {})
    raw["response"] = message.get("content", "")
    return JSONResponse(raw)


def create_ollama_bridge_app(root: Path) -> FastAPI:
    state = OllamaBridgeState(root)
    app = FastAPI(title="Copilot Model Gateway Ollama Bridge", docs_url=None, redoc_url=None)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "::1", "testserver"],
    )

    @app.get("/", include_in_schema=False)
    def root_status() -> PlainTextResponse:
        return PlainTextResponse("Ollama is running (Copilot Model Gateway bridge)")

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"version": "0.6.0-cmg"}

    @app.get("/api/tags")
    def tags() -> dict[str, list[dict[str, Any]]]:
        try:
            _, _, aliases = state.load()
        except Exception as exc:  # noqa: BLE001 - expose local configuration errors
            return {"models": [], "error": str(exc)}
        return {"models": [_model_record(alias) for alias in aliases]}

    @app.get("/api/ps")
    def running_models() -> dict[str, list[dict[str, Any]]]:
        try:
            _, _, aliases = state.load()
        except Exception:
            aliases = []
        return {"models": [_model_record(alias) for alias in aliases]}

    @app.post("/api/show")
    async def show(request: Request) -> JSONResponse:
        payload = await request.json()
        requested = str(payload.get("model") or payload.get("name") or "")
        try:
            _, _, aliases = state.load()
        except Exception as exc:  # noqa: BLE001
            return _error(str(exc), 500)
        model = _resolve_model(requested, aliases)
        if not model:
            return _error(f"model '{requested}' not found", 404)
        record = _model_record(model)
        return JSONResponse(
            {
                "license": "",
                "modelfile": "# Routed by Copilot Model Gateway",
                "parameters": "",
                "template": "{{ .Prompt }}",
                "details": record["details"],
                "model_info": {},
                "capabilities": ["completion", "tools"],
            }
        )

    @app.post("/api/chat")
    async def chat(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error("request body must be an object")
            base_url, api_key, aliases = state.gateway_connection()
            requested = str(payload.get("model") or "")
            model = _resolve_model(requested, aliases)
            if not model:
                return _error(f"model '{requested}' not found", 404)
            body = _openai_chat_body(payload, model)
        except Exception as exc:  # noqa: BLE001
            return _error(str(exc), 400)
        if body["stream"]:
            return StreamingResponse(
                _chat_stream(base_url, api_key, model, body),
                media_type="application/x-ndjson",
            )
        return await _chat_non_stream(base_url, api_key, model, body)

    @app.post("/api/generate")
    async def generate(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                return _error("request body must be an object")
            base_url, api_key, aliases = state.gateway_connection()
            requested = str(payload.get("model") or "")
            model = _resolve_model(requested, aliases)
            if not model:
                return _error(f"model '{requested}' not found", 404)
            prompt = str(payload.get("prompt") or "")
            system = str(payload.get("system") or "")
            options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        except Exception as exc:  # noqa: BLE001
            return _error(str(exc), 400)
        if payload.get("stream", True):
            messages: list[dict[str, str]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            body = _openai_chat_body(
                {"messages": messages, "stream": True, "options": options}, model
            )

            async def generate_stream() -> AsyncIterator[bytes]:
                async for chunk in _chat_stream(base_url, api_key, model, body):
                    item = json.loads(chunk)
                    if "error" in item:
                        yield chunk
                        continue
                    message = item.pop("message", {})
                    item["response"] = message.get("content", "")
                    yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")

            return StreamingResponse(generate_stream(), media_type="application/x-ndjson")
        return await _generate_non_stream(
            base_url, api_key, model, prompt, system, options
        )

    @app.post("/api/pull")
    async def pull(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return {
            "status": "success",
            "model": payload.get("model") or payload.get("name"),
        }

    return app


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def start_ollama_bridge_thread(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 11434,
) -> threading.Thread:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Ollama bridge may only bind to localhost")
    if _port_open(host, port):
        raise ValueError(
            f"Ollama bridge port {port} is already in use. Stop the Ollama service first."
        )
    app = create_ollama_bridge_app(root)

    def run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=run, name="cmg-ollama-bridge", daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        if _port_open(host, port):
            print(f"Ollama compatibility endpoint: http://{host}:{port}")
            return thread
        if not thread.is_alive():
            break
        time.sleep(0.1)
    raise RuntimeError(f"Ollama bridge failed to start on {host}:{port}")
