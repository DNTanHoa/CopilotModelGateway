from pathlib import Path

import pytest

from copilot_model_gateway.settings import ConfigurationError, load_env_file, load_gateway_config


def test_load_env_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\nB='two words'\n# ignored\n", encoding="utf-8")
    assert load_env_file(path) == {"A": "1", "B": "two words"}


def test_load_gateway_config_rejects_duplicate_profile_ids(tmp_path: Path) -> None:
    path = tmp_path / "gateway.yaml"
    path.write_text(
        """
profiles:
  - id: duplicate
    models: []
  - id: duplicate
    models: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="Duplicate profile id"):
        load_gateway_config(path)
