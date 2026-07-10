# Copilot Model Gateway

A secure local model gateway for connecting **GitHub Copilot / Bring Your Own Model** clients to your own AI providers through LiteLLM.

The project is intentionally provider-neutral. It generates a temporary LiteLLM configuration at runtime from a clean gateway configuration and secrets stored in `.env`.

## Why this project exists

Many BYOK examples work, but become difficult to maintain when you add more providers or multiple API keys. Copilot Model Gateway separates concerns:

- `config/gateway.yaml` describes providers, deployments and public model aliases.
- `.env` contains secrets only.
- `.runtime/litellm.yaml` is generated automatically and is never committed.
- Repeating the same model alias across profiles creates multiple LiteLLM deployments for routing/load balancing.
- Missing API keys are skipped instead of breaking unrelated providers.
- Authentication is enabled by default.
- Binding outside loopback without authentication is blocked.

## Architecture

```text
Visual Studio / OpenAI-compatible client
                |
                |  http://127.0.0.1:4000/v1
                v
       Copilot Model Gateway
       (runtime config generator)
                |
                v
            LiteLLM Proxy
       /          |           \
 DeepSeek      Gemini      OpenAI/custom
```

## Repository layout

```text
config/
  gateway.example.yaml   Configuration template committed to Git
  gateway.yaml           Your active configuration, ignored by Git
src/copilot_model_gateway/
  cli.py                  CLI commands
  settings.py             Configuration and .env loader
  generator.py            Safe LiteLLM runtime config generator
  process.py              LiteLLM process discovery/startup
  client.py               Gateway test client
scripts/
  setup.ps1               Windows setup helper
  publish-to-github.ps1   One-command GitHub publishing helper
```

## Requirements

- Windows PowerShell 5.1+ or PowerShell 7+
- Python 3.10+
- Visual Studio with a Bring Your Own Model/OpenAI-compatible endpoint option

## Quick start on Windows

```powershell
# First-time setup
.\gateway.ps1 setup

# Edit secrets and provider configuration
notepad .env
notepad config\gateway.yaml

# Validate everything before starting
.\gateway.ps1 doctor

# Start the local gateway
.\gateway.ps1 start
```

Or double-click/use the batch wrapper:

```bat
gateway.bat setup
gateway.bat doctor
gateway.bat start
```

The default endpoint is:

```text
http://127.0.0.1:4000/v1
```

Use the generated `GATEWAY_MASTER_KEY` from `.env` as the API key in the client.

## Visual Studio BYOM values

For each alias printed by:

```powershell
.\gateway.ps1 models
```

add a model in Visual Studio using values similar to:

| Field | Value |
|---|---|
| Display name | Any friendly name |
| Model ID | The alias from `gateway.ps1 models` |
| Resource endpoint | `http://127.0.0.1:4000` |
| API key | `GATEWAY_MASTER_KEY` from `.env` |
| Tool calling | Enable only when the selected provider/model supports it |

Some Visual Studio builds may label this feature **Bring Your Own Model**, **BYOM**, or **OpenAI-compatible model**.

## Configure providers

The committed template uses model IDs verified against provider documentation on July 10, 2026. Provider catalogs change, so treat them as editable defaults and run `doctor`/`test` after upgrades.

After setup, edit `config/gateway.yaml`:

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

Then put the secret in `.env`:

```ini
DEEPSEEK_API_KEY_1=sk-...
```

### Multiple keys for one model

Add another profile using the **same alias** but a different environment variable:

```yaml
  - id: deepseek-secondary
    label: DeepSeek secondary key
    enabled: true
    api_key_env: DEEPSEEK_API_KEY_2
    api_base: https://api.deepseek.com
    models:
      - alias: deepseek-v4-flash
        model: deepseek/deepseek-v4-flash
```

This produces two deployments behind the public model ID `deepseek-v4-flash`. LiteLLM can route requests between them. Unlike scripts that repeatedly assign one environment variable, the keys do not overwrite each other.

## Commands

```powershell
.\gateway.ps1 setup                  # Create venv, install packages, initialize config
.\gateway.ps1 init                   # Create missing .env/config files only
.\gateway.ps1 doctor                 # Validate configuration and security
.\gateway.ps1 models                 # Show active public aliases and deployments
.\gateway.ps1 render                 # Generate .runtime/litellm.yaml
.\gateway.ps1 start                  # Start LiteLLM proxy
.\gateway.ps1 test                   # Test every visible model
.\gateway.ps1 test --model deepseek-v4-flash
```

Override host and port at startup:

```powershell
.\gateway.ps1 start --host 127.0.0.1 --port 4100
```

## Security

- `.env`, `config/gateway.yaml`, and `.runtime/` are ignored by Git.
- Proxy authentication is enabled by default.
- The CLI refuses a non-loopback host when authentication is disabled.
- Generated runtime configuration can contain provider keys, so it is stored under `.runtime/` with restricted file permissions where supported.
- Do not expose the gateway to a LAN or the internet without TLS, firewall rules, authentication, and an explicit threat review.
- Source code/prompts sent through the gateway still reach the provider selected for that model.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Publish this repository

The included publisher creates a private `DNTanHoa/CopilotModelGateway` repository and pushes the current folder. The easiest option is to double-click:

```text
publish.bat
```

Or run the configurable PowerShell command:

```powershell
.\scripts\publish-to-github.ps1 `
  -Owner DNTanHoa `
  -Repository CopilotModelGateway `
  -Visibility private
```

It uses GitHub CLI when available. Otherwise it securely prompts for a GitHub Personal Access Token with repository creation/push permission.

## License

MIT
