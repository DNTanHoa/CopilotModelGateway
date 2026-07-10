from pathlib import Path

from fastapi.testclient import TestClient

from copilot_model_gateway.dashboard import create_dashboard_app
from copilot_model_gateway.settings import load_env_file, update_env_file


def _write_project(root: Path) -> None:
    (root / "config").mkdir()
    (root / "web").mkdir()
    (root / "web" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (root / ".env").write_text(
        "# local secrets\n"
        "GATEWAY_MASTER_KEY=sk-local-abcdefghijklmnopqrstuvwxyz\n"
        "GEMINI_API_KEY_1=\n",
        encoding="utf-8",
    )
    (root / "config" / "gateway.yaml").write_text(
        """gateway:
  host: 127.0.0.1
  port: 4000
  require_auth: true
  master_key_env: GATEWAY_MASTER_KEY
profiles:
  - id: gemini-primary
    label: Gemini
    enabled: true
    api_key_env: GEMINI_API_KEY_1
    models:
      - alias: gemini-test
        model: gemini/gemini-test
""",
        encoding="utf-8",
    )


def test_update_env_file_preserves_comments(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# heading\nA=old\n", encoding="utf-8")
    update_env_file(env_path, {"A": "new", "B": "value"})
    assert env_path.read_text(encoding="utf-8") == "# heading\nA=new\n\nB=value\n"


def test_dashboard_status_and_key_update(tmp_path: Path) -> None:
    _write_project(tmp_path)
    client = TestClient(create_dashboard_app(tmp_path))

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["profiles"][0]["key_configured"] is False

    saved = client.post(
        "/api/keys", json={"name": "GEMINI_API_KEY_1", "value": "secret-value"}
    )
    assert saved.status_code == 200
    assert load_env_file(tmp_path / ".env")["GEMINI_API_KEY_1"] == "secret-value"

    rejected = client.post("/api/keys", json={"name": "UNKNOWN_KEY", "value": "x"})
    assert rejected.status_code == 400
