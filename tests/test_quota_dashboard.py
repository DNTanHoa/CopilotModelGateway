from decimal import Decimal

from copilot_model_gateway.quota_dashboard import (
    _apply_low_balance_status,
    _build_summary,
)


def test_available_balance_below_threshold_is_low() -> None:
    item = {
        "provider": "deepseek",
        "status": "available",
        "summary": "Balance available",
        "metrics": [{"label": "USD", "value": "0.50"}],
        "note": "Live provider balance.",
    }

    result = _apply_low_balance_status(item, Decimal("1"))

    assert result["status"] == "low"
    assert result["summary"] == "Low balance"
    assert "threshold" in result["note"]


def test_healthy_balance_stays_available() -> None:
    item = {
        "provider": "kimi",
        "status": "available",
        "summary": "Balance available",
        "metrics": [{"label": "Available", "value": "5.00"}],
        "note": "Live provider balance.",
    }

    result = _apply_low_balance_status(item, Decimal("1"))

    assert result["status"] == "available"


def test_summary_counts_provider_states() -> None:
    items = [
        {"status": "available"},
        {"status": "connected"},
        {"status": "low"},
        {"status": "unavailable"},
        {"status": "error"},
        {"status": "unsupported"},
        {"status": "missing_key"},
    ]

    summary = _build_summary(items)

    assert summary == {
        "total": 7,
        "configured": 6,
        "healthy": 2,
        "low": 1,
        "unavailable": 1,
        "errors": 1,
        "unsupported": 1,
    }
