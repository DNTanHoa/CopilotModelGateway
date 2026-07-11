from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from .ollama_bridge import (
    OllamaBridgeState,
    _port_open,
    _resolve_model,
    create_ollama_bridge_app,
)


async def _close_upstream(response: httpx.Response, client: httpx.AsyncClient) -> None:
    await response.aclose()
    await client.aclose()


def _openai_model_record(model: str) -> dict[str, Any]:
    return {
        "id": model,
        "object": "model",
        "created": 0,
        "owned_by": "copilot-model-gateway",
    }


def _normalize_provider_payload(payload: dict[str, Any], model: str) -> None:
    """Apply provider constraints that Visual Studio cannot configure itself."""

    if model.startswith("kimi-k2.7-code"):
        payload["temperature"] = 1.0
        payload["top_p"] = 0.95
        payload["n"] = 1
        payload["presence_penalty"] = 0.0
        payload["frequency_penalty"] = 0.0
        tool_choice = payload.get("tool_choice")
        if tool_choice not in {None, "auto", "none"}:
            payload["tool_choice"] = "auto"


def create_visual_studio_bridge_app(root: Path) -> FastAPI:
    """Extend the Ollama bridge with the OpenAI chat routes used by Visual Studio."""

    app = create_ollama_bridge_app(root)
    state = OllamaBridgeState(root)

    def models_payload() -> dict[str, Any]:
        try:
            _, _, aliases = state.load()
        except Exception as exc:  # noqa: BLE001 - expose local configuration errors
            return {"object": "list", "data": [], "error": str(exc)}
        return {
            "object": "list",
            "data": [_openai_model_record(alias) for alias in aliases],
        }

    @app.get("/v1/models")
    @app.get("/models")
    def openai_models() -> dict[str, Any]:
        return models_payload()

    async def proxy_chat_completion(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                return JSONResponse(
                    {"error": {"message": "request body must be an object"}},
                    status_code=400,
                )

            base_url, api_key, aliases = state.gateway_connection()
            requested = str(payload.get("model") or "")
            model = _resolve_model(requested, aliases)
            if not model:
                return JSONResponse(
                    {"error": {"message": f"model '{requested}' not found"}},
                    status_code=404,
                )

            payload["model"] = model
            _normalize_provider_payload(payload, model)
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            client = httpx.AsyncClient(timeout=None)
            upstream_request = client.build_request(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers=headers,
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            upstream = await client.send(upstream_request, stream=True)
        except Exception as exc:  # noqa: BLE001 - return useful local bridge errors
            return JSONResponse(
                {"error": {"message": str(exc)}},
                status_code=500,
            )

        media_type = upstream.headers.get("content-type", "application/json").split(";", 1)[0]
        if payload.get("stream"):
            return StreamingResponse(
                upstream.aiter_raw(),
                status_code=upstream.status_code,
                media_type=media_type,
                background=BackgroundTask(_close_upstream, upstream, client),
            )

        content = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=media_type,
        )

    app.add_api_route(
        "/v1/chat/completions",
        proxy_chat_completion,
        methods=["POST"],
    )
    app.add_api_route(
        "/chat/completions",
        proxy_chat_completion,
        methods=["POST"],
    )

    return app


def start_ollama_bridge_thread(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 11434,
) -> threading.Thread:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Visual Studio bridge may only bind to localhost")
    if _port_open(host, port):
        raise ValueError(
            f"Visual Studio bridge port {port} is already in use. Stop the Ollama service first."
        )

    app = create_visual_studio_bridge_app(root)

    def run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=run, name="cmg-visual-studio-bridge", daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        if _port_open(host, port):
            print(f"Visual Studio compatibility endpoint: http://{host}:{port}")
            return thread
        if not thread.is_alive():
            break
        time.sleep(0.1)
    raise RuntimeError(f"Visual Studio bridge failed to start on {host}:{port}")
