from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigurationError(ValueError):
    """Raised when gateway configuration is invalid."""


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    model: str
    enabled: bool = True
    api_base: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileConfig:
    id: str
    label: str
    enabled: bool
    api_key_env: str | None
    api_base: str | None
    models: tuple[ModelConfig, ...]


@dataclass(frozen=True)
class GatewayConfig:
    host: str
    port: int
    require_auth: bool
    master_key_env: str
    routing_strategy: str
    request_timeout_seconds: int
    profiles: tuple[ProfileConfig, ...]


def parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigurationError(f"Expected a boolean value, got {value!r}")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigurationError(f"Invalid .env line {line_number}: missing '='")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigurationError(f"Invalid .env line {line_number}: empty key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def update_env_file(path: Path, updates: Mapping[str, str]) -> None:
    """Update selected .env keys atomically while preserving comments and ordering."""
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for raw_line in original:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in raw_line:
            key = raw_line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(raw_line)
    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.extend(f"{key}={value}" for key, value in remaining.items())

    content = "\n".join(output).rstrip("\n") + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _required_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def load_gateway_config(path: Path) -> GatewayConfig:
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigurationError("Top-level YAML value must be a mapping")

    gateway = raw.get("gateway") or {}
    if not isinstance(gateway, dict):
        raise ConfigurationError("gateway must be a mapping")

    host = str(gateway.get("host", "127.0.0.1")).strip()
    port = int(gateway.get("port", 4000))
    if not 1 <= port <= 65535:
        raise ConfigurationError("gateway.port must be between 1 and 65535")

    require_auth = parse_bool(gateway.get("require_auth"), default=True)
    master_key_env = str(gateway.get("master_key_env", "GATEWAY_MASTER_KEY")).strip()
    routing_strategy = str(gateway.get("routing_strategy", "simple-shuffle")).strip()
    timeout = int(gateway.get("request_timeout_seconds", 120))
    if timeout <= 0:
        raise ConfigurationError("gateway.request_timeout_seconds must be positive")

    raw_profiles = raw.get("profiles") or []
    if not isinstance(raw_profiles, list):
        raise ConfigurationError("profiles must be a list")

    profiles: list[ProfileConfig] = []
    seen_profile_ids: set[str] = set()
    for profile_index, raw_profile in enumerate(raw_profiles, start=1):
        context = f"profiles[{profile_index}]"
        if not isinstance(raw_profile, dict):
            raise ConfigurationError(f"{context} must be a mapping")

        profile_id = _required_text(raw_profile, "id", context)
        if profile_id in seen_profile_ids:
            raise ConfigurationError(f"Duplicate profile id: {profile_id}")
        seen_profile_ids.add(profile_id)

        label = str(raw_profile.get("label", profile_id)).strip() or profile_id
        enabled = parse_bool(raw_profile.get("enabled"), default=True)
        api_key_env_value = raw_profile.get("api_key_env")
        api_key_env = str(api_key_env_value).strip() if api_key_env_value else None
        api_base_value = raw_profile.get("api_base")
        api_base = str(api_base_value).strip() if api_base_value else None

        raw_models = raw_profile.get("models") or []
        if not isinstance(raw_models, list):
            raise ConfigurationError(f"{context}.models must be a list")

        models: list[ModelConfig] = []
        for model_index, raw_model in enumerate(raw_models, start=1):
            model_context = f"{context}.models[{model_index}]"
            if not isinstance(raw_model, dict):
                raise ConfigurationError(f"{model_context} must be a mapping")
            alias = _required_text(raw_model, "alias", model_context)
            provider_model = _required_text(raw_model, "model", model_context)
            model_enabled = parse_bool(raw_model.get("enabled"), default=True)
            model_api_base_value = raw_model.get("api_base")
            model_api_base = str(model_api_base_value).strip() if model_api_base_value else None
            params = raw_model.get("params") or {}
            if not isinstance(params, dict):
                raise ConfigurationError(f"{model_context}.params must be a mapping")
            models.append(
                ModelConfig(
                    alias=alias,
                    model=provider_model,
                    enabled=model_enabled,
                    api_base=model_api_base,
                    params=dict(params),
                )
            )

        profiles.append(
            ProfileConfig(
                id=profile_id,
                label=label,
                enabled=enabled,
                api_key_env=api_key_env,
                api_base=api_base,
                models=tuple(models),
            )
        )

    return GatewayConfig(
        host=host,
        port=port,
        require_auth=require_auth,
        master_key_env=master_key_env,
        routing_strategy=routing_strategy,
        request_timeout_seconds=timeout,
        profiles=tuple(profiles),
    )
