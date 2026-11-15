import gzip
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from finn import companies, main, providers
from finn.store import Store


@pytest.fixture
def equity_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path / "equities.db"))
    downloads = []

    async def fetch_bytes(url):
        exchange = "BSE" if url.endswith("/BSE.json.gz") else "NSE"
        downloads.append(exchange)
        rows = [
            {
                "name": "VAISHNO CEMENT CO.LTD."
                if exchange == "BSE"
                else "MARICO LIMITED",
                "trading_symbol": "VAICC" if exchange == "BSE" else "MARICO",
                "segment": f"{exchange}_EQ",
                "instrument_type": "P" if exchange == "BSE" else "EQ",
                "exchange_token": "526941" if exchange == "BSE" else "4067",
                "isin": "INE116E01018" if exchange == "BSE" else "INE196A01026",
            }
        ]
        return gzip.compress(json.dumps(rows).encode()), "application/gzip"

    monkeypatch.setattr(providers, "fetch_bytes", fetch_bytes)
    with TestClient(main.app) as client:
        yield client, downloads


def test_find_off_watchlist_companies_and_reuse_directory(equity_client):
    client, downloads = equity_client
    for value in (
        "Vaishno Cement Co Ltd",
        "VAICC",
        "VAICC.BO",
        "526941",
        "INE116E01018",
    ):
        data = client.get("/api/companies/search", params={"q": value}).json()
        assert [item["symbol"] for item in data["items"]] == ["VAICC"]
        assert data["items"][0]["code"] == "526941"
    assert (
        client.get("/api/companies/search?q=Marico").json()["items"][0]["exchange"]
        == "NSE"
    )
    assert sorted(downloads) == ["BSE", "NSE"]


def test_bse_quote_and_graceful_missing_quote(equity_client, monkeypatch):
    client, _ = equity_client
    calls = []

    async def get(client, url, **kwargs):
        calls.append(url)
        if url.endswith("MARICO.NS"):
            raise httpx.ConnectError("Source unavailable")
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {"currency": "INR"},
                            "timestamp": [1794397500],
                            "indicators": {
                                "quote": [{"close": [3.01], "volume": [75]}]
                            },
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(providers, "get_with_retry", get)
    bse = client.get("/api/companies/BSE/vaicc").json()
    assert bse["quote"]["close"] == 3.01
    assert bse["quote"]["volume"] == 75
    assert bse["quote"]["change_pct"] is None
    assert bse["research_symbol"] is None
    assert bse["quote_url"].endswith("/VAICC.BO/")
    assert bse["exchange_url"].endswith("/vaicc/526941/")
    assert calls[0].endswith("/VAICC.BO")
    assert client.get("/api/companies/BSE/VAICC").json() == bse
    assert len(calls) == 1
    nse = client.get("/api/companies/NSE/MARICO").json()
    assert nse["quote"] is None
    assert nse["warnings"]
    assert nse["exchange_url"].endswith("symbol=MARICO")
    assert client.get("/api/companies/NSE/VAICC").status_code == 404
    assert len(client.get("/api/state").json()["portfolio"]) == 18


def test_directory_failure_preserves_saved_listings_and_other_exchange(
    equity_client, monkeypatch
):
    client, _ = equity_client
    assert client.get("/api/companies/search?q=VAICC").json()["items"]
    monkeypatch.setattr(companies, "DIRECTORY_TTL", 0)

    async def offline(url):
        raise httpx.ConnectError("Source unavailable")

    monkeypatch.setattr(providers, "fetch_bytes", offline)
    main.store.set("companies:directory:v1:NSE", None)
    result = client.get("/api/companies/search?q=526941").json()
    assert result["items"][0]["symbol"] == "VAICC"
    assert len(result["warnings"]) == 2


def test_dual_listing_research_is_joined_on_isin(monkeypatch, tmp_path):
    import asyncio

    async def directory(exchange, store):
        listing = {"exchange": exchange, "name": "Example Ltd", "isin": "INE196A01026"}
        if exchange == "BSE":
            return [{**listing, "symbol": "EXB", "code": "500209"}], None
        return [{**listing, "symbol": "EXN", "code": None}], None

    async def price(*args, **kwargs):
        return {"close": 100}

    monkeypatch.setattr(companies, "directory", directory)
    monkeypatch.setattr(providers, "prices", price)
    result = asyncio.run(companies.lookup("BSE", "EXB", Store(tmp_path / "db")))
    assert result["research_symbol"] == "EXN"
