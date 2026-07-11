from pathlib import Path

import yaml

from copilot_model_gateway.provider_extensions import ensure_builtin_provider_profiles
from copilot_model_gateway.settings import load_env_file, load_gateway_config
from copilot_model_gateway.visual_studio_bridge import _normalize_provider_payload


def _write_minimal_project(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "gateway.yaml").write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 4000,
                    "require_auth": True,
                    "master_key_env": "GATEWAY_MASTER_KEY",
                },
                "profiles": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / ".env").write_text(
        "GATEWAY_MASTER_KEY=gateway-master-key-for-tests-123456\n",
        encoding="utf-8",
    )


def test_builtin_provider_migration_is_idempotent(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    assert ensure_builtin_provider_profiles(tmp_path)
    assert not ensure_builtin_provider_profiles(tmp_path)

    config = load_gateway_config(tmp_path / "config" / "gateway.yaml")
    profile_ids = {profile.id for profile in config.profiles}
    assert {"minimax-primary", "kimi-primary"} <= profile_ids

    env = load_env_file(tmp_path / ".env")
    assert "MINIMAX_API_KEY_1" in env
    assert "KIMI_API_KEY_1" in env


def test_kimi_coding_payload_is_normalized() -> None:
    payload = {
        "temperature": 0.2,
        "top_p": 0.8,
        "n": 2,
        "presence_penalty": 1,
        "frequency_penalty": 1,
        "tool_choice": "required",
    }

    _normalize_provider_payload(payload, "kimi-k2.7-code")

    assert payload["temperature"] == 1.0
    assert payload["top_p"] == 0.95
    assert payload["n"] == 1
    assert payload["presence_penalty"] == 0.0
    assert payload["frequency_penalty"] == 0.0
    assert payload["tool_choice"] == "auto"
