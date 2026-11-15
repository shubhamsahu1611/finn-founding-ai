from datetime import datetime

import pytest

from finn.domain import (
    IST,
    change,
    classify,
    make_alerts,
    price_signal,
    ticker,
    DEFAULT_SETTINGS,
)


@pytest.mark.parametrize(
    "title,category,material",
    [
        ("Quarterly financial results", "results", True),
        ("Board meeting to approve results", "results", False),
        ("Newspaper publication of results", "results", False),
        ("Earnings call transcript for quarterly results", "earnings_call", False),
        ("Appointment of statutory auditor", "unclassified", False),
        ("Appointment of Chief Financial Officer", "management_change", True),
        ("Credit rating downgraded", "credit_rating", True),
        ("Postal ballot voting results", "postal_ballot", False),
        ("Acquisition of a subsidiary", "M&A", True),
        ("Promoter pledge disclosure", "pledging", True),
        ("Redemption of Commercial Paper", "unclassified", False),
    ],
)
def test_classification(title, category, material):
    actual, score, reason = classify(title)
    assert actual == category
    assert (score >= 50) == material
    assert reason


def test_price_excludes_incomplete_day_and_latest_from_volume_baseline():
    bars = [
        {"date": f"2026-10-{i:02}", "close": 100, "volume": 100} for i in range(1, 22)
    ]
    bars += [
        {"date": "2026-11-09", "close": 104, "volume": 220},
        {"date": "2026-11-10", "close": 999, "volume": 9999},
    ]
    result = price_signal(bars, datetime(2026, 11, 10, 12, tzinfo=IST))
    assert result["close"] == 104
    assert result["change_pct"] == 4
    assert result["volume_ratio"] == 2.2
    assert result["baseline_sessions"] == 20


def test_close_and_null_handling():
    bars = [
        {"date": "2026-11-09", "close": 100, "volume": 100},
        {"date": "2026-11-10", "close": 90, "volume": 0},
    ]
    result = price_signal(bars, datetime(2026, 11, 10, 16, tzinfo=IST))
    assert result["change_pct"] == -10
    assert result["volume_ratio"] == 0
    assert change(10, 0) is None
    assert change(10, -10) is None
    assert change(None, 10) is None


def test_volume_alert_requires_full_baseline_and_inclusive_thresholds():
    p = {
        "date": "2026-11-09",
        "change_pct": -3,
        "volume_ratio": 2,
        "baseline_sessions": 19,
    }
    alerts = make_alerts([], {"TCS": p}, DEFAULT_SETTINGS, "live")
    assert [a["kind"] for a in alerts] == ["price"]
    p["baseline_sessions"] = 20
    alerts = make_alerts([], {"TCS": p}, DEFAULT_SETTINGS, "live")
    assert {a["kind"] for a in alerts} == {"price", "volume"}
    assert len({a["id"] for a in alerts}) == 2


def test_ticker_validation():
    assert ticker(" infy.ns ") == "INFY"
    assert ticker("M&M") == "M&M"
    with pytest.raises(ValueError):
        ticker("../../etc/passwd")
