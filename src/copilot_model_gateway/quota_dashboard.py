from __future__ import annotations

import copy
import os
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .provider_extensions import collect_provider_quotas
from .settings import load_env_file

_CACHE_TTL_SECONDS = 300
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _parse_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _low_balance_threshold(root: Path) -> Decimal:
    env = load_env_file(root / ".env")
    raw = os.environ.get(
        "QUOTA_LOW_BALANCE_THRESHOLD",
        env.get("QUOTA_LOW_BALANCE_THRESHOLD", "1"),
    )
    value = _parse_decimal(raw)
    if value is None or value < 0:
        return Decimal("1")
    return value


def _metric_values(item: dict[str, Any]) -> list[Decimal]:
    values: list[Decimal] = []
    for metric in item.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        value = _parse_decimal(metric.get("value"))
        if value is not None:
            values.append(value)
    return values


def _apply_low_balance_status(
    item: dict[str, Any],
    threshold: Decimal,
) -> dict[str, Any]:
    normalized = copy.deepcopy(item)
    if normalized.get("provider") not in {"deepseek", "kimi"}:
        return normalized
    if normalized.get("status") != "available":
        return normalized

    values = [value for value in _metric_values(normalized) if value >= 0]
    if values and max(values) <= threshold:
        normalized["status"] = "low"
        normalized["summary"] = "Low balance"
        normalized["note"] = (
            f"Balance is at or below the configured warning threshold ({threshold}). "
            f"{normalized.get('note', '')}"
        ).strip()
    return normalized


def _build_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(items),
        "configured": 0,
        "healthy": 0,
        "low": 0,
        "unavailable": 0,
        "errors": 0,
        "unsupported": 0,
    }
    for item in items:
        status = str(item.get("status") or "")
        if status != "missing_key":
            summary["configured"] += 1
        if status in {"available", "connected"}:
            summary["healthy"] += 1
        elif status == "low":
            summary["low"] += 1
        elif status == "unavailable":
            summary["unavailable"] += 1
        elif status == "error":
            summary["errors"] += 1
        elif status == "unsupported":
            summary["unsupported"] += 1
    return summary


def _build_snapshot(root: Path) -> dict[str, Any]:
    threshold = _low_balance_threshold(root)
    items = [
        _apply_low_balance_status(item, threshold)
        for item in collect_provider_quotas(root)
    ]
    checked_at = time.time()
    return {
        "items": items,
        "summary": _build_summary(items),
        "checked_at_unix": checked_at,
        "low_balance_threshold": str(threshold),
        "cache_ttl_seconds": _CACHE_TTL_SECONDS,
        "cached": False,
    }


def get_quota_snapshot(root: Path, *, refresh: bool = False) -> dict[str, Any]:
    resolved = root.resolve()
    key = str(resolved)
    now = time.time()

    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and not refresh:
            cached_at, payload = cached
            age = now - cached_at
            if age < _CACHE_TTL_SECONDS:
                result = copy.deepcopy(payload)
                result["cached"] = True
                result["cache_age_seconds"] = max(0, int(age))
                return result

        payload = _build_snapshot(resolved)
        _CACHE[key] = (now, copy.deepcopy(payload))
        return payload


def install_quota_dashboard_extension() -> None:
    """Add the richer cached quota endpoint to the dashboard app factory."""

    from . import dashboard

    original_create_dashboard_app = dashboard.create_dashboard_app
    if getattr(original_create_dashboard_app, "_quota_dashboard_installed", False):
        return

    def create_dashboard_app_with_quota_dashboard(root: Path):
        app = original_create_dashboard_app(root)

        @app.get("/api/provider-quota-dashboard")
        def provider_quota_dashboard(refresh: bool = False) -> dict[str, Any]:
            try:
                return get_quota_snapshot(root, refresh=refresh)
            except (OSError, ValueError) as exc:
                return {
                    "items": [],
                    "summary": _build_summary([]),
                    "error": str(exc),
                    "cached": False,
                }

        return app

    create_dashboard_app_with_quota_dashboard._quota_dashboard_installed = True  # type: ignore[attr-defined]
    dashboard.create_dashboard_app = create_dashboard_app_with_quota_dashboard
