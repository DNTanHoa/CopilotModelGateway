from copilot_model_gateway.generator import build_litellm_config
from copilot_model_gateway.settings import GatewayConfig, ModelConfig, ProfileConfig


def make_config(*, require_auth: bool = True) -> GatewayConfig:
    profiles = (
        ProfileConfig(
            id="key-one",
            label="Key one",
            enabled=True,
            api_key_env="PROVIDER_KEY_1",
            api_base="https://example.test/v1",
            models=(ModelConfig(alias="coding", model="openai/model-a"),),
        ),
        ProfileConfig(
            id="key-two",
            label="Key two",
            enabled=True,
            api_key_env="PROVIDER_KEY_2",
            api_base="https://example.test/v1",
            models=(ModelConfig(alias="coding", model="openai/model-a"),),
        ),
    )
    return GatewayConfig(
        host="127.0.0.1",
        port=4000,
        require_auth=require_auth,
        master_key_env="GATEWAY_MASTER_KEY",
        routing_strategy="simple-shuffle",
        request_timeout_seconds=120,
        profiles=profiles,
    )


def test_multiple_keys_create_multiple_deployments() -> None:
    rendered, deployments, warnings = build_litellm_config(
        make_config(),
        {
            "PROVIDER_KEY_1": "provider-key-one",
            "PROVIDER_KEY_2": "provider-key-two",
            "GATEWAY_MASTER_KEY": "gateway-master-key-for-tests-123456",
        },
    )
    assert not warnings
    assert len(deployments) == 2
    assert [item["model_name"] for item in rendered["model_list"]] == ["coding", "coding"]
    keys = [item["litellm_params"]["api_key"] for item in rendered["model_list"]]
    assert keys == ["provider-key-one", "provider-key-two"]


def test_missing_key_skips_only_that_profile() -> None:
    _, deployments, warnings = build_litellm_config(
        make_config(),
        {
            "PROVIDER_KEY_1": "provider-key-one",
            "GATEWAY_MASTER_KEY": "gateway-master-key-for-tests-123456",
        },
    )
    assert len(deployments) == 1
    assert any("PROVIDER_KEY_2" in warning for warning in warnings)


def test_remote_bind_without_auth_is_rejected() -> None:
    try:
        build_litellm_config(make_config(require_auth=False), {}, host_override="0.0.0.0")
    except ValueError as exc:
        assert "non-loopback" in str(exc)
    else:
        raise AssertionError("Expected unsafe bind to be rejected")
