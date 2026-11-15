from datetime import UTC, datetime, timedelta

import pytest

from finn import main
from finn.domain import classify


def exchange_filing(identity, symbol, title, hours=1):
    category, priority, reason = classify(title)
    return {
        "id": identity,
        "symbol": symbol,
        "title": title,
        "category": category,
        "priority": priority,
        "reason": reason,
        "published_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat(),
        "source": "NSE filing",
        "source_url": "https://example.test/filing.pdf",
        "mode": "live",
    }


@pytest.fixture
def public_snapshot(monkeypatch):
    def seed():
        rows = [
            exchange_filing("tcs-results", "TCS", "Quarterly results"),
            exchange_filing("dixon-capex", "DIXON", "Capacity expansion", 2),
            exchange_filing(
                "hdfc-management",
                "HDFCBANK",
                "Appointment of Chief Financial Officer",
                3,
            ),
            exchange_filing("itc-routine", "ITC", "Investor meeting schedule", 4),
        ]
        main.store.set(
            "snapshot:live",
            {
                "prices": {},
                "filings": rows,
                "updated_at": datetime.now(UTC).isoformat(),
                "coverage_days": 7,
                "errors": [],
                "mode": "live",
            },
        )

        async def filing_evidence(filing, store, *, use_ai=False):
            return {**filing, "evidence": []}

        monkeypatch.setattr(main, "enrich_filing", filing_evidence)
        return rows

    return seed
