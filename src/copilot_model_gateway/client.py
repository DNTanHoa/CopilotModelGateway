from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelTestResult:
    model: str
    ok: bool
    elapsed_ms: int
    message: str


def _request_json(
    url: str,
    *,
    method: str = "GET",
    api_key: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {payload}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc


def list_models(base_url: str, api_key: str | None) -> list[str]:
    payload = _request_json(f"{base_url.rstrip('/')}/v1/models", api_key=api_key)
    models = payload.get("data", [])
    return sorted(
        str(item["id"])
        for item in models
        if isinstance(item, dict) and item.get("id")
    )


def test_model(
    base_url: str,
    api_key: str | None,
    model: str,
    *,
    timeout: int = 60,
) -> ModelTestResult:
    started = time.perf_counter()
    try:
        payload = _request_json(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            method="POST",
            api_key=api_key,
            timeout=timeout,
            body={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Reply with one short sentence confirming the model is available."
                        ),
                    }
                ],
                "max_tokens": 80,
                "temperature": 0,
            },
        )
        message = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        return ModelTestResult(model=model, ok=True, elapsed_ms=elapsed, message=message)
    except Exception as exc:  # noqa: BLE001 - CLI should report provider errors cleanly
        elapsed = int((time.perf_counter() - started) * 1000)
        return ModelTestResult(model=model, ok=False, elapsed_ms=elapsed, message=str(exc))
