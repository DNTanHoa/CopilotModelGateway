from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from .settings import load_env_file, load_gateway_config, update_env_file


_BUILTIN_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "id": "minimax-primary",
        "label": "MiniMax API",
        "enabled": True,
        "api_key_env": "MINIMAX_API_KEY_1",
        "api_base": "https://api.minimax.io/v1",
        "models": [
            {
                "alias": "minimax-m3",
                "model": "openai/MiniMax-M3",
                "enabled": True,
            },
            {
                "alias": "minimax-m2.7-highspeed",
                "model": "openai/MiniMax-M2.7-highspeed",
                "enabled": True,
            },
        ],
    },
    {
        "id": "kimi-primary",
        "label": "Kimi API",
        "enabled": True,
        "api_key_env": "KIMI_API_KEY_1",
        "api_base": "https://api.moonshot.ai/v1",
        "models": [
            {
                "alias": "kimi-k2.7-code",
                "model": "openai/kimi-k2.7-code",
                "enabled": True,
            },
            {
                "alias": "kimi-k2.7-code-highspeed",
                "model": "openai/kimi-k2.7-code-highspeed",
                "enabled": True,
            },
            {
                "alias": "kimi-k2.6",
                "model": "openai/kimi-k2.6",
                "enabled": True,
            },
        ],
    },
)

_ENV_KEYS = {
    "MINIMAX_API_KEY_1": "",
    "KIMI_API_KEY_1": "",
}


def ensure_builtin_provider_profiles(root: Path) -> bool:
    """Append new built-in providers without overwriting existing local profiles."""

    root = root.resolve()
    config_path = root / "config" / "gateway.yaml"
    env_path = root / ".env"
    changed = False

    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("Top-level gateway configuration must be a mapping")
        profiles = raw.setdefault("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("profiles must be a list")
        existing_ids = {
            str(item.get("id", "")).strip()
            for item in profiles
            if isinstance(item, dict)
        }
        for profile in _BUILTIN_PROFILES:
            if profile["id"] not in existing_ids:
                profiles.append(copy.deepcopy(profile))
                changed = True
        if changed:
            config_path.write_text(
                yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    existing_env = load_env_file(env_path)
    missing_env = {name: value for name, value in _ENV_KEYS.items() if name not in existing_env}
    if missing_env:
        update_env_file(env_path, missing_env)
        changed = True

    return changed


def _provider_kind(profile_id: str, api_base: str | None, model_names: list[str]) -> str:
    host = urlparse(api_base or "").hostname or ""
    normalized_id = profile_id.lower()
    if host == "api.deepseek.com" or normalized_id.startswith("deepseek"):
        return "deepseek"
    if host == "api.moonshot.ai" or normalized_id.startswith("kimi"):
        return "kimi"
    if host == "api.minimax.io" or normalized_id.startswith("minimax"):
        return "minimax"
    if normalized_id.startswith("gemini") or any(name.startswith("gemini/") for name in model_names):
        return "gemini"
    if normalized_id.startswith("openai"):
        return "openai"
    return "openai-compatible"


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _deepseek_balance(api_base: str, api_key: str) -> dict[str, Any]:
    base = api_base.rstrip("/")
    if base.lower().endswith("/v1"):
        base = base[:-3]
    response = httpx.get(
        f"{base}/user/balance",
        headers=_bearer_headers(api_key),
        timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    balances = payload.get("balance_infos") or []
    metrics = []
    for balance in balances:
        if not isinstance(balance, dict):
            continue
        currency = str(balance.get("currency") or "").strip() or "Balance"
        metrics.append(
            {
                "label": currency,
                "value": str(balance.get("total_balance") or "0"),
                "detail": (
                    f"Granted {balance.get('granted_balance', '0')} · "
                    f"Top-up {balance.get('topped_up_balance', '0')}"
                ),
            }
        )
    available = bool(payload.get("is_available"))
    return {
        "status": "available" if available else "unavailable",
        "summary": "Balance available" if available else "Insufficient balance",
        "metrics": metrics,
        "note": "Live balance from DeepSeek /user/balance.",
    }


def _kimi_balance(api_base: str, api_key: str) -> dict[str, Any]:
    base = api_base.rstrip("/")
    if not base.lower().endswith("/v1"):
        base = f"{base}/v1"
    response = httpx.get(
        f"{base}/users/me/balance",
        headers=_bearer_headers(api_key),
        timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Kimi balance endpoint returned an unexpected response")
    available = float(data.get("available_balance") or 0)
    return {
        "status": "available" if available > 0 else "unavailable",
        "summary": "Balance available" if available > 0 else "No available balance",
        "metrics": [
            {
                "label": "Available",
                "value": str(data.get("available_balance", 0)),
                "detail": (
                    f"Cash {data.get('cash_balance', 0)} · "
                    f"Voucher {data.get('voucher_balance', 0)}"
                ),
            }
        ],
        "note": "Live balance from Kimi /v1/users/me/balance.",
    }


def _models_access(api_base: str, api_key: str, provider: str) -> dict[str, Any]:
    base = api_base.rstrip("/")
    if not base.lower().endswith("/v1"):
        base = f"{base}/v1"
    response = httpx.get(
        f"{base}/models",
        headers=_bearer_headers(api_key),
        timeout=12.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    count = len(data) if isinstance(data, list) else 0
    return {
        "status": "connected",
        "summary": f"{count} accessible model{'s' if count != 1 else ''}",
        "metrics": [{"label": "Models", "value": str(count), "detail": "API key verified"}],
        "note": (
            f"{provider} does not expose a public remaining-balance endpoint in its API docs; "
            "model access is verified instead."
        ),
    }


def _unsupported_quota(provider: str) -> dict[str, Any]:
    notes = {
        "gemini": "Gemini quota is managed in AI Studio / Google Cloud; an API key cannot read remaining quota directly.",
        "openai": "OpenAI usage and costs require a separate organization Admin key; a normal project key is not sufficient.",
        "openai-compatible": "This custom provider has no configured quota adapter.",
    }
    return {
        "status": "unsupported",
        "summary": "Quota API unavailable",
        "metrics": [],
        "note": notes.get(provider, "Quota API unavailable for this provider."),
    }


def collect_provider_quotas(root: Path) -> list[dict[str, Any]]:
    config = load_gateway_config(root / "config" / "gateway.yaml")
    env = load_env_file(root / ".env")
    items: list[dict[str, Any]] = []

    for profile in config.profiles:
        if not profile.enabled or not profile.api_key_env:
            continue
        api_key = env.get(profile.api_key_env, "").strip()
        model_names = [model.model for model in profile.models if model.enabled]
        provider = _provider_kind(profile.id, profile.api_base, model_names)
        item: dict[str, Any] = {
            "id": profile.id,
            "label": profile.label,
            "provider": provider,
            "key_configured": bool(api_key),
            "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if not api_key:
            item.update(
                {
                    "status": "missing_key",
                    "summary": "API key not configured",
                    "metrics": [],
                    "note": f"Set {profile.api_key_env} to enable this provider.",
                }
            )
            items.append(item)
            continue

        try:
            if provider == "deepseek":
                result = _deepseek_balance(profile.api_base or "https://api.deepseek.com", api_key)
            elif provider == "kimi":
                result = _kimi_balance(profile.api_base or "https://api.moonshot.ai/v1", api_key)
            elif provider == "minimax":
                result = _models_access(
                    profile.api_base or "https://api.minimax.io/v1",
                    api_key,
                    "MiniMax",
                )
            else:
                result = _unsupported_quota(provider)
            item.update(result)
        except (httpx.HTTPError, ValueError) as exc:
            item.update(
                {
                    "status": "error",
                    "summary": "Quota check failed",
                    "metrics": [],
                    "note": str(exc),
                }
            )
        items.append(item)

    return items


def install_dashboard_extensions() -> None:
    """Patch dashboard creation before the CLI imports run_dashboard."""

    from . import dashboard

    original_create_dashboard_app = dashboard.create_dashboard_app
    if getattr(original_create_dashboard_app, "_provider_extensions_installed", False):
        return

    def create_dashboard_app_with_provider_extensions(root: Path):
        ensure_builtin_provider_profiles(root)
        app = original_create_dashboard_app(root)

        @app.get("/api/provider-quotas")
        def provider_quotas() -> dict[str, Any]:
            try:
                return {
                    "items": collect_provider_quotas(root.resolve()),
                    "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            except (OSError, ValueError) as exc:
                return {"items": [], "error": str(exc)}

        return app

    create_dashboard_app_with_provider_extensions._provider_extensions_installed = True  # type: ignore[attr-defined]
    dashboard.create_dashboard_app = create_dashboard_app_with_provider_extensions
