import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from finn import main, providers
from finn.domain import DEFAULT_SETTINGS, make_alerts
from finn.research import supported_number
from finn.store import Store


def test_cache_prefix_is_literal_and_expired_values_are_purged(tmp_path):
    store = Store(tmp_path / "test.db")
    store.set("x_:current", 1)
    store.set("xa:other", 2)
    store.set("x_:expired", 3, ttl=-1)
    assert store.records("x_:") == {"current": 1}
    store.purge_expired()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM kv").fetchone() == (2,)


def test_parallel_portfolio_adds_preserve_all_verified_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path / "test.db"))

    async def quote(symbol):
        await asyncio.sleep(0.02)
        return {"name": symbol}

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.post("/api/portfolio", json={"symbol": symbol})
                    for symbol in ("EXAMPLE", "SECOND", "EXAMPLE")
                )
            )
        assert sorted(response.status_code for response in responses) == [200, 200, 409]

    monkeypatch.setattr(main.providers, "prices", quote)
    asyncio.run(run())
    assert {"EXAMPLE", "SECOND"} <= {item["symbol"] for item in main.portfolio()}


def test_nse_keeps_valid_filing_when_warmup_and_a_row_fail(monkeypatch):
    def upstream(request):
        if request.url.path == "/":
            raise httpx.ConnectTimeout("warmup timeout", request=request)
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "TCS",
                    "an_dt": "bad",
                    "sort_date": "2026-11-13T12:00:00+05:30",
                    "desc": "Results",
                },
                {"symbol": "TCS", "an_dt": "bad"},
            ],
        )

    client_cls = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kw: client_cls(transport=httpx.MockTransport(upstream), **kw),
    )
    batch = asyncio.run(providers.announcements(["TCS"]))
    assert [row["published_at"] for row in batch.filings] == [
        "2026-11-13T12:00:00+05:30"
    ]
    assert "skipped 1" in batch.warnings[0]


def test_document_request_pins_ip_and_checks_redirect(monkeypatch):
    remote = "93.184.215.14"
    resolved = []

    def resolve(host, *args, **kwargs):
        resolved.append(host)
        address = remote if host == "source.example" else "127.0.0.1"
        return [(None, None, None, None, (address, 443))]

    def upstream(request):
        assert request.url.host == remote
        assert request.headers["host"] == "source.example"
        assert request.extensions["sni_hostname"] == "source.example"
        return httpx.Response(302, headers={"Location": "https://internal.example/"})

    client_cls = httpx.AsyncClient
    monkeypatch.setattr(providers.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kw: client_cls(transport=httpx.MockTransport(upstream), **kw),
    )
    with pytest.raises(ValueError, match="Private or local"):
        asyncio.run(providers.fetch_bytes("https://source.example/report.pdf"))
    assert resolved == ["source.example", "internal.example"]


def test_loss_quotes_preserve_sign_and_alerts_use_market_close():
    assert supported_number(-1234.5, "Net loss (1,234.50) crore")
    assert not supported_number(1234.5, "Net loss (1,234.50) crore")
    assert supported_number(-11, "Net loss −11 crore")
    assert not supported_number(11, "Net loss −11 crore")
    assert supported_number(-11, "PAT(11).")
    assert supported_number(-12.5, "Margin (12.5%)")
    assert not supported_number(12.5, "Net income (₹12.5)")
    rows = [
        {
            "id": "morning",
            "symbol": "TCS",
            "title": "Results",
            "category": "results",
            "priority": 90,
            "reason": "Results",
            "published_at": "2026-11-13T09:00:00+05:30",
        },
        {
            "id": "late",
            "symbol": "TCS",
            "title": "Results",
            "category": "results",
            "priority": 90,
            "reason": "Results",
            "published_at": "2026-11-13T11:30:00Z",
        },
    ]
    alerts = make_alerts(
        rows,
        {"TCS": {"date": "2026-11-13", "change_pct": 40}},
        {**DEFAULT_SETTINGS, "categories": ["results"]},
        "live",
    )
    assert [alert["id"].split(":")[2] for alert in alerts] == ["late", "TCS", "morning"]


def test_proxy_origin_and_reconnect_use_selected_window(
    tmp_path, monkeypatch, public_snapshot
):
    monkeypatch.setattr(main, "store", Store(tmp_path / "test.db"))
    monkeypatch.setenv("FINN_ALLOWED_ORIGINS", "https://finn.example")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://finn-founding-ai.onrender.com")
    public_snapshot()
    data = main.snapshot()
    data["filings"][0]["published_at"] = (
        datetime.now(UTC) - timedelta(days=12)
    ).isoformat()
    main.store.set("snapshot:live", data)
    with TestClient(main.app) as client:
        for origin in ["https://finn.example", "https://finn-founding-ai.onrender.com"]:
            assert (
                client.put(
                    "/api/settings", json=DEFAULT_SETTINGS, headers={"Origin": origin}
                ).status_code
                == 200
            )
        assert (
            client.put(
                "/api/settings",
                json=DEFAULT_SETTINGS,
                headers={"Origin": "https://other.example"},
            ).status_code
            == 403
        )
        assert (
            client.get("/api/network", params={"q": "Ananya"}).json()["profiles"][0][
                "id"
            ]
            == "ananya"
        )
        for hours, expected in [(168, False), (720, True)]:
            result = client.get(
                "/api/network",
                params={"q": "Who should I reconnect with?", "hours": hours},
            ).json()
            assert (
                any(
                    item["filing"]["id"] == "tcs-results"
                    for item in result["groups"][0]["matches"]
                )
                is expected
            )


def test_partial_refresh_keeps_coverage_honest_and_filters_timezone_boundary(
    tmp_path, monkeypatch, public_snapshot
):
    monkeypatch.setattr(main, "store", Store(tmp_path / "test.db"))
    rows = public_snapshot()
    cutoff = datetime.now(UTC) - timedelta(days=90)
    older = (cutoff - timedelta(hours=1)).astimezone(providers.IST).isoformat()
    newer = (cutoff + timedelta(hours=1)).isoformat()

    async def price(*args, **kwargs):
        return {"source": "Yahoo Finance · NSE"}

    async def announcements(*args):
        return providers.AnnouncementBatch(
            [
                {**rows[0], "id": "older", "published_at": older},
                {**rows[0], "id": "newer", "published_at": newer},
            ],
            ["NSE skipped a malformed row."],
        )

    monkeypatch.setattr(providers, "announcements", announcements)
    monkeypatch.setattr(providers, "prices", price)
    result = asyncio.run(main.refresh_live())
    ids = {row["id"] for row in result["filings"]}
    assert {"newer", "tcs-results"} <= ids
    assert "older" not in ids
    assert result["filings_updated_at"] is None
    assert main.digest()["coverage_warning"]
