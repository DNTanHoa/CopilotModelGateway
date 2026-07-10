# Copilot Model Gateway

A secure local model gateway for connecting **GitHub Copilot / Bring Your Own Model** clients to your own AI providers through LiteLLM. It includes a localhost-only web dashboard for managing provider keys, runtime state, model tests and Visual Studio connection values.

## What it provides

- Multi-provider routing for DeepSeek, Gemini, OpenAI and OpenAI-compatible endpoints.
- Multiple independent keys behind the same public model alias.
- Secrets stored only in local `.env`; generated runtime config stays under `.runtime/`.
- Gateway authentication enabled by default.
- Local dashboard bound only to loopback.
- Start/stop controls, live status, model tests and gateway logs.
- CLI commands for automation and troubleshooting.

## Architecture

```text
Visual Studio / OpenAI-compatible client
                |
                | http://127.0.0.1:4000/v1
                v
        LiteLLM model gateway
         /        |        \
   DeepSeek    Gemini    OpenAI/custom
                ^
                |
Local dashboard http://127.0.0.1:4100
```

## Requirements

- Windows PowerShell 5.1+ or PowerShell 7+
- Python 3.10+
- Visual Studio with a Bring Your Own Model/OpenAI-compatible endpoint option

## Quick start

```powershell
cd D:\projects\model-gateway\CopilotModelGateway

# Install/update dependencies and initialize local files
.\gateway.bat setup

# Open the web dashboard
.\gateway.bat ui
```

The browser opens automatically at:

```text
http://127.0.0.1:4100
```

From the dashboard:

1. Enter at least one provider API key.
2. Click **Start gateway**.
3. Copy the endpoint and gateway key.
4. Add one of the active model aliases to Visual Studio BYOM.

The model API remains at:

```text
http://127.0.0.1:4000/v1
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

Do not use port `4000` for the dashboard because that port belongs to the LiteLLM gateway.

## Visual Studio BYOM values

| Field | Value |
|---|---|
| Display name | Any friendly name |
| Model ID | An active alias shown on the dashboard |
| Resource endpoint | `http://127.0.0.1:4000` |
| API key | `GATEWAY_MASTER_KEY`, available through **Copy gateway key** |
| Tool calling | Enable only when the selected provider/model supports it |

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
.\gateway.bat ui                     # Open the local dashboard
.\gateway.bat doctor                 # Validate configuration and runtime
.\gateway.bat models                 # Show active aliases and deployments
.\gateway.bat render                 # Generate .runtime/litellm.yaml
.\gateway.bat start                  # Run LiteLLM in the foreground
.\gateway.bat test                   # Test all visible models
.\gateway.bat test --model MODEL_ID  # Test one alias
```

## Security

- `.env`, `config/gateway.yaml`, `.runtime/` and logs are ignored by Git.
- The dashboard binds to loopback only and has trusted-host validation.
- Provider secrets are accepted only for environment variable names declared in the gateway config.
- The gateway API uses its own master key and is authenticated by default.
- Generated runtime configuration contains provider keys and must remain local.
- Prompts and source code still reach whichever external provider serves the selected model.
- Do not expose either port to LAN or internet without TLS, firewall rules and an explicit security review.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m compileall -q src
```

## License

MIT
