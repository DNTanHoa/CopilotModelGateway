from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def build_litellm_config(
    config: GatewayConfig,
    env: Mapping[str, str],
    *,
    host_override: str | None = None,
    port_override: int | None = None,
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

        for model in profile.models:
            if not model.enabled:
                continue

            litellm_params: dict[str, Any] = {
                "model": model.model,
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
                    provider_model=model.model,
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
