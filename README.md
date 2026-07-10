# Copilot Model Gateway

A secure local model gateway for connecting **GitHub Copilot / Bring Your Own Model** clients to your own AI providers through LiteLLM. It includes a localhost-only dashboard and an Ollama-compatible bridge for Visual Studio builds that do not allow a custom OpenAI host.

## What it provides

- Multi-provider routing for DeepSeek, Gemini, OpenAI and OpenAI-compatible endpoints.
- Ollama-compatible API on `http://127.0.0.1:11434` for Visual Studio BYOM.
- Multiple independent keys behind the same public model alias.
- Secrets stored only in local `.env`; generated runtime config stays under `.runtime/`.
- Gateway authentication enabled by default.
- Local dashboard bound only to loopback.
- Start/stop controls, live status, model tests and gateway logs.
- CLI commands for automation and troubleshooting.

## Architecture

```text
Visual Studio BYOM
     |
     | Ollama provider
     v
Ollama bridge http://127.0.0.1:11434
     |
     | OpenAI-compatible request with local gateway key
     v
LiteLLM gateway http://127.0.0.1:4000/v1
     |
     +---- DeepSeek
     +---- Gemini
     +---- OpenAI/custom

Dashboard http://127.0.0.1:4100
```

The Ollama bridge does not run a local DeepSeek model. It only translates Ollama requests from Visual Studio into requests for the configured cloud provider.

## Requirements

- Windows PowerShell 5.1+ or PowerShell 7+
- Python 3.10+
- Visual Studio with a Bring Your Own Model / Ollama provider option

## Quick start

```powershell
cd D:\projects\model-gateway\CopilotModelGateway

# Install/update dependencies and initialize local files
.\gateway.bat setup

# Open dashboard and start the Ollama compatibility bridge
.\gateway.bat ui
```

The browser opens automatically at:

```text
http://127.0.0.1:4100
```

The same process also opens:

```text
http://127.0.0.1:11434
```

for Visual Studio's Ollama provider.

From the dashboard:

1. Enter `DEEPSEEK_API_KEY_1` or another provider key.
2. Click **Start gateway**.
3. Confirm the gateway is **Online**.
4. Test the DeepSeek alias in **Active model aliases**.
5. In Visual Studio BYOM, choose **Ollama** and select that alias.

The internal OpenAI-compatible model API remains at:

```text
http://127.0.0.1:4000/v1
```

## Visual Studio BYOM with DeepSeek

Do not choose the **OpenAI** provider when that Visual Studio build does not expose a custom host field. Choose **Ollama** instead.

The bridge exposes the active gateway aliases through Ollama's model discovery endpoint:

```text
GET http://127.0.0.1:11434/api/tags
```

Visual Studio should list aliases such as:

```text
deepseek-v4-flash
deepseek-v4-pro
```

Use the exact alias shown by the dashboard. The model is still served by DeepSeek cloud through `DEEPSEEK_API_KEY_1`; it is not downloaded by Ollama.

### Port 11434 is already in use

If Ollama Desktop or `ollama serve` is already running, stop it before launching the gateway UI because both services use port `11434`.

Windows Command Prompt:

```bat
taskkill /IM ollama.exe /F
gateway.bat ui
```

PowerShell:

```powershell
Stop-Process -Name ollama -Force -ErrorAction SilentlyContinue
.\gateway.bat ui
```

Verify the bridge:

```powershell
curl.exe http://127.0.0.1:11434/api/tags
```

## Dashboard features

- Provider cards show which API keys are configured or missing.
- Existing secrets are never displayed in provider fields.
- **Copy gateway key** reads the local master key only when clicked.
- **Render config** regenerates `.runtime/litellm.yaml`.
- **Start gateway** launches LiteLLM in the background and writes logs to `.runtime/gateway.log`.
- **Stop gateway** stops only the process started by this dashboard.
- Active aliases can be tested individually.
- The dashboard refuses non-loopback bind addresses and validates the HTTP Host header.

Use a different dashboard port when required:

```powershell
.\gateway.bat ui --port 4200
```

Use a different Ollama bridge port only when the client allows a custom Ollama address:

```powershell
.\gateway.bat ui --ollama-port 11435
```

Disable the bridge when you only need the dashboard:

```powershell
.\gateway.bat ui --no-ollama-bridge
```

## Configuration

`config/gateway.yaml` describes profiles and public aliases. `.env` contains secrets only.

```yaml
profiles:
  - id: deepseek-primary
    label: DeepSeek primary key
    enabled: true
    api_key_env: DEEPSEEK_API_KEY_1
    api_base: https://api.deepseek.com
    models:
      - alias: deepseek-v4-flash
        model: deepseek/deepseek-v4-flash
```

```ini
DEEPSEEK_API_KEY_1=sk-...
```

To use two keys for the same public model, add a second profile with a different `api_key_env` and repeat the same alias. LiteLLM sees them as separate deployments and can route between them.

## Commands

```powershell
.\gateway.bat setup                  # Install/update dependencies and initialize files
.\gateway.bat init                   # Create missing .env/config files
.\gateway.bat ui                     # Dashboard + Ollama bridge on 11434
.\gateway.bat doctor                 # Validate configuration and runtime
.\gateway.bat models                 # Show active aliases and deployments
.\gateway.bat render                 # Generate .runtime/litellm.yaml
.\gateway.bat start                  # Run LiteLLM in the foreground
.\gateway.bat test                   # Test all visible models
.\gateway.bat test --model MODEL_ID  # Test one alias
```

## Security

- `.env`, `config/gateway.yaml`, `.runtime/` and logs are ignored by Git.
- Dashboard, gateway and Ollama bridge bind to loopback by default.
- Provider secrets are accepted only for environment variable names declared in gateway config.
- The gateway API uses its own master key and is authenticated by default.
- The Ollama bridge has no external authentication and must remain localhost-only.
- Generated runtime configuration contains provider keys and must remain local.
- Prompts and source code still reach whichever external provider serves the selected model.
- Do not expose any port to LAN or internet without TLS, firewall rules and an explicit security review.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m compileall -q src
```

## License

MIT
