from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
from collections import Counter
from pathlib import Path

from .client import list_models, test_model
from .dashboard import run_dashboard
from .generator import build_litellm_config, render_runtime_config
from .process import find_litellm_executable, start_litellm
from .settings import ConfigurationError, load_env_file, load_gateway_config


def _paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / ".env",
        root / "config" / "gateway.yaml",
        root / ".runtime" / "litellm.yaml",
    )


def _merged_env(env_file: Path) -> dict[str, str]:
    merged = load_env_file(env_file)
    merged.update(os.environ)
    return merged


def _initialize(root: Path) -> int:
    env_path, config_path, _ = _paths(root)
    env_example = root / ".env.example"
    config_example = root / "config" / "gateway.example.yaml"

    if not env_example.exists() or not config_example.exists():
        raise FileNotFoundError("Repository templates are missing")

    if not env_path.exists():
        env_path.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Created {env_path.relative_to(root)}")

    lines = env_path.read_text(encoding="utf-8").splitlines()
    found_master_key = False
    updated_lines: list[str] = []
    for line in lines:
        if line.startswith("GATEWAY_MASTER_KEY="):
            found_master_key = True
            current = line.split("=", 1)[1].strip()
            if not current:
                line = f"GATEWAY_MASTER_KEY=sk-local-{secrets.token_urlsafe(32)}"
        updated_lines.append(line)
    if not found_master_key:
        updated_lines.insert(0, f"GATEWAY_MASTER_KEY=sk-local-{secrets.token_urlsafe(32)}")
    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Created {config_path.relative_to(root)}")

    print("Initialization complete. Secrets remain in .env and are ignored by Git.")
    return 0


def _load(root: Path):
    env_path, config_path, runtime_path = _paths(root)
    config = load_gateway_config(config_path)
    env = _merged_env(env_path)
    return config, env, runtime_path


def _port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host == "localhost" else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


def _doctor(root: Path, host: str | None, port: int | None, skip_runtime: bool) -> int:
    config, env, _ = _load(root)
    effective_host = host or config.host
    effective_port = port or config.port

    print("Copilot Model Gateway doctor")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Root   : {root}")
    print(f"  Listen : {effective_host}:{effective_port}")
    print(f"  Auth   : {'enabled' if config.require_auth else 'disabled'}")

    rendered, deployments, warnings = build_litellm_config(
        config, env, host_override=effective_host, port_override=effective_port
    )
    _ = rendered
    for warning in warnings:
        print(f"  WARN   : {warning}")

    if not deployments:
        print("  ERROR  : No active deployments. Add a provider API key.")
        return 1

    aliases = Counter(item.alias for item in deployments)
    print(f"  Models : {len(aliases)} alias(es), {len(deployments)} deployment(s)")
    for alias, count in sorted(aliases.items()):
        print(f"           - {alias} ({count} deployment{'s' if count != 1 else ''})")

    if not _port_available(effective_host, effective_port):
        print(f"  ERROR  : Port {effective_port} is already in use or cannot be bound.")
        return 1

    if not skip_runtime:
        executable = find_litellm_executable(root)
        if not executable:
            print("  ERROR  : LiteLLM executable not found. Run gateway.ps1 setup.")
            return 1
        print(f"  LiteLLM: {executable}")

    print("Doctor result: OK")
    return 0


def _models(root: Path) -> int:
    config, env, _ = _load(root)
    _, deployments, warnings = build_litellm_config(config, env)
    for warning in warnings:
        print(f"WARN: {warning}")
    if not deployments:
        print("No active deployments.")
        return 1

    print(f"{'ALIAS':24} {'PROFILE':24} PROVIDER MODEL")
    print("-" * 86)
    for item in deployments:
        print(f"{item.alias:24} {item.profile_id:24} {item.provider_model}")
    return 0


def _render(root: Path, host: str | None, port: int | None) -> int:
    config, env, runtime_path = _load(root)
    result = render_runtime_config(config, env, runtime_path, host_override=host, port_override=port)
    for warning in result.warnings:
        print(f"WARN: {warning}")
    print(f"Generated {result.path}")
    print(f"Deployments: {len(result.deployments)}")
    return 0


def _start(root: Path, host: str | None, port: int | None) -> int:
    config, env, runtime_path = _load(root)
    effective_host = host or config.host
    effective_port = port or config.port
    result = render_runtime_config(
        config, env, runtime_path, host_override=effective_host, port_override=effective_port
    )
    for warning in result.warnings:
        print(f"WARN: {warning}")

    executable = find_litellm_executable(root)
    if not executable:
        print("LiteLLM executable not found. Run gateway.ps1 setup.", file=sys.stderr)
        return 1
    return start_litellm(executable, result.path, effective_host, effective_port)


def _test(root: Path, host: str | None, port: int | None, model: str | None) -> int:
    config, env, _ = _load(root)
    effective_host = host or config.host
    effective_port = port or config.port
    base_url = f"http://{effective_host}:{effective_port}"
    api_key = env.get(config.master_key_env) if config.require_auth else None

    try:
        models = list_models(base_url, api_key)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        print("Start the gateway first with: .\\gateway.ps1 start", file=sys.stderr)
        return 1

    selected = [model] if model else models
    if model and model not in models:
        print(f"Model '{model}' is not exposed by the gateway.", file=sys.stderr)
        return 1

    failures = 0
    for model_id in selected:
        print(f"Testing {model_id}...", end=" ", flush=True)
        result = test_model(base_url, api_key, model_id)
        if result.ok:
            print(f"OK ({result.elapsed_ms} ms)")
            if result.message:
                print(f"  {result.message}")
        else:
            failures += 1
            print(f"FAIL ({result.elapsed_ms} ms)")
            print(f"  {result.message}")
    print(f"Passed: {len(selected) - failures}/{len(selected)}")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copilot-model-gateway")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create missing local configuration files")

    doctor = subparsers.add_parser("doctor", help="Validate configuration and runtime")
    doctor.add_argument("--host")
    doctor.add_argument("--port", type=int)
    doctor.add_argument("--skip-runtime", action="store_true")

    subparsers.add_parser("models", help="Show active model deployments")

    render = subparsers.add_parser("render", help="Generate LiteLLM runtime config")
    render.add_argument("--host")
    render.add_argument("--port", type=int)

    start = subparsers.add_parser("start", help="Start the local gateway")
    start.add_argument("--host")
    start.add_argument("--port", type=int)

    test = subparsers.add_parser("test", help="Test exposed model aliases")
    test.add_argument("--host")
    test.add_argument("--port", type=int)
    test.add_argument("--model")

    ui = subparsers.add_parser("ui", help="Open the local management dashboard")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=4100)
    ui.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.command == "init":
            return _initialize(root)
        if args.command == "doctor":
            return _doctor(root, args.host, args.port, args.skip_runtime)
        if args.command == "models":
            return _models(root)
        if args.command == "render":
            return _render(root, args.host, args.port)
        if args.command == "start":
            return _start(root, args.host, args.port)
        if args.command == "test":
            return _test(root, args.host, args.port, args.model)
        if args.command == "ui":
            return run_dashboard(root, args.host, args.port, open_browser=not args.no_browser)
    except (ConfigurationError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
