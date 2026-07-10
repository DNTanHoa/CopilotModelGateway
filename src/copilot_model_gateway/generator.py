from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from .settings import GatewayConfig


@dataclass(frozen=True)
class Deployment:
    alias: str
    profile_id: str
    profile_label: str
    provider_model: str


@dataclass(frozen=True)
class RenderResult:
    path: Path
    deployments: tuple[Deployment, ...]
    warnings: tuple[str, ...]


# DeepSeek documents the legacy names as compatibility aliases for V4 Flash:
# deepseek-chat = non-thinking mode, deepseek-reasoner = thinking mode.
# V4 Pro does not have a documented legacy compatibility alias.
_DEEPSEEK_COMPATIBILITY_MODELS: dict[str, tuple[str, ...]] = {
    "deepseek-v4-flash": ("deepseek-chat", "deepseek-reasoner"),
    "deepseek-chat": ("deepseek-v4-flash",),
    "deepseek-reasoner": ("deepseek-v4-flash",),
}


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _is_official_deepseek_profile(api_base: str | None) -> bool:
    if not api_base:
        return False
    normalized = api_base.strip().lower().rstrip("/")
    return normalized in {
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
    }


def _deepseek_models_url(api_base: str) -> str:
    normalized = api_base.strip().rstrip("/")
    if normalized.lower().endswith("/v1"):
        return f"{normalized}/models"
    return f"{normalized}/v1/models"


def _fetch_deepseek_model_ids(api_base: str, api_key: str) -> set[str]:
    response = httpx.get(
        _deepseek_models_url(api_base),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("DeepSeek /models returned an unexpected response")
    return {
        str(item.get("id", "")).strip()
        for item in items
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }


def _resolve_deepseek_provider_model(
    provider_model: str,
    available_models: set[str],
) -> str | None:
    if not provider_model.startswith("deepseek/"):
        return provider_model

    requested = provider_model.split("/", 1)[1]
    if requested in available_models:
        return provider_model

    for compatible in _DEEPSEEK_COMPATIBILITY_MODELS.get(requested, ()):
        if compatible in available_models:
            return f"deepseek/{compatible}"
    return None


def build_litellm_config(
    config: GatewayConfig,
    env: Mapping[str, str],
    *,
    host_override: str | None = None,
    port_override: int | None = None,
    resolve_provider_models: bool = False,
) -> tuple[dict[str, Any], tuple[Deployment, ...], tuple[str, ...]]:
    host = host_override or config.host
    _ = port_override or config.port

    if not config.require_auth and not is_loopback_host(host):
        raise ValueError(
            "Refusing to bind to a non-loopback host while authentication is disabled"
        )

    warnings: list[str] = []
    model_list: list[dict[str, Any]] = []
    deployments: list[Deployment] = []

    for profile in config.profiles:
        if not profile.enabled:
            continue

        api_key: str | None = None
        if profile.api_key_env:
            api_key = env.get(profile.api_key_env, "").strip()
            if not api_key:
                warnings.append(
                    f"Skipping profile '{profile.id}': {profile.api_key_env} is not set"
                )
                continue

        available_deepseek_models: set[str] | None = None
        if (
            resolve_provider_models
            and api_key
            and _is_official_deepseek_profile(profile.api_base)
        ):
            try:
                available_deepseek_models = _fetch_deepseek_model_ids(
                    profile.api_base or "https://api.deepseek.com",
                    api_key,
                )
                if not available_deepseek_models:
                    warnings.append(
                        f"DeepSeek profile '{profile.id}' returned no available models"
                    )
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(
                    f"Could not discover DeepSeek models for profile '{profile.id}': {exc}. "
                    "Using configured model IDs."
                )

        for model in profile.models:
            if not model.enabled:
                continue

            provider_model = model.model
            if available_deepseek_models is not None:
                resolved_model = _resolve_deepseek_provider_model(
                    provider_model,
                    available_deepseek_models,
                )
                if resolved_model is None:
                    requested = provider_model.split("/", 1)[-1]
                    warnings.append(
                        f"Skipping model alias '{model.alias}' for profile '{profile.id}': "
                        f"DeepSeek model '{requested}' is not available for this API key"
                    )
                    continue
                if resolved_model != provider_model:
                    warnings.append(
                        f"DeepSeek profile '{profile.id}': alias '{model.alias}' mapped "
                        f"from '{provider_model}' to compatible model '{resolved_model}'"
                    )
                    provider_model = resolved_model

            litellm_params: dict[str, Any] = {
                "model": provider_model,
                "timeout": config.request_timeout_seconds,
            }
            if api_key:
                litellm_params["api_key"] = api_key
            effective_api_base = model.api_base or profile.api_base
            if effective_api_base:
                litellm_params["api_base"] = effective_api_base
            litellm_params.update(model.params)

            model_list.append(
                {
                    "model_name": model.alias,
                    "litellm_params": litellm_params,
                    "model_info": {
                        "id": f"{profile.id}:{model.alias}",
                        "description": profile.label,
                    },
                }
            )
            deployments.append(
                Deployment(
                    alias=model.alias,
                    profile_id=profile.id,
                    profile_label=profile.label,
                    provider_model=provider_model,
                )
            )

    rendered: dict[str, Any] = {
        "model_list": model_list,
        "router_settings": {"routing_strategy": config.routing_strategy},
        "litellm_settings": {"drop_params": True, "set_verbose": False},
    }

    if config.require_auth:
        master_key = env.get(config.master_key_env, "").strip()
        if not master_key:
            raise ValueError(
                f"Authentication is enabled but {config.master_key_env} is empty"
            )
        if len(master_key) < 24:
            raise ValueError(
                f"{config.master_key_env} is too short; use at least 24 characters"
            )
        rendered["general_settings"] = {"master_key": master_key}

    return rendered, tuple(deployments), tuple(warnings)


def render_runtime_config(
    config: GatewayConfig,
    env: Mapping[str, str],
    output_path: Path,
    *,
    host_override: str | None = None,
    port_override: int | None = None,
) -> RenderResult:
    rendered, deployments, warnings = build_litellm_config(
        config,
        env,
        host_override=host_override,
        port_override=port_override,
        resolve_provider_models=True,
    )
    if not deployments:
        raise ValueError("No active deployments. Add at least one provider API key.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(rendered, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    try:
        os.chmod(output_path, 0o600)
    except OSError:
        pass

    return RenderResult(path=output_path, deployments=deployments, warnings=warnings)
