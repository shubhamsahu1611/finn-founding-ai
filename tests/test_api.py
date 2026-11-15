import sqlite3

import pytest
from fastapi.testclient import TestClient

from finn import main
from finn.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", Store(tmp_path / "test.db"))
    with TestClient(main.app) as client:
        yield client


def test_initial_public_state_and_digest(client, public_snapshot):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
    assert health["last_live_refresh"] is None
    assert health["uptime_seconds"] >= 0
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert len(data["portfolio"]) == 18
    assert len(data["categories"]) == 17
    assert data["prices"] == {}
    assert client.get("/api/digest").json()["items"] == []
    public_snapshot()
    digest = client.get("/api/digest").json()
    assert len(digest["items"]) == 4
    priorities = [f["priority"] for f in digest["items"]]
    assert priorities == sorted(priorities, reverse=True)
    assert digest["routine_count"] > 0


def test_health_reports_database_failure(client, monkeypatch):
    def unavailable():
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(main.store, "connect", unavailable)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_custom_windows_and_bad_input(client, public_snapshot):
    public_snapshot()
    assert client.get("/api/digest?start=2026-11-10&end=2026-11-11").status_code == 422
    assert client.get("/api/digest?hours=9999").status_code == 422
    week = client.get("/api/digest?hours=168").json()
    assert week["items"]
    assert week["coverage_warning"] is None
    assert (
        client.post("/api/research", json={"symbol": "../../evil"}).status_code == 422
    )
    assert (
        client.post(
            "/api/research", json={"symbol": "TCS", "mode": "bogus"}
        ).status_code
        == 422
    )


def test_preferences_recompute_alerts_and_read_state(client, public_snapshot):
    public_snapshot()
    data = client.get("/api/state").json()
    alerts = data["alerts"]
    assert alerts
    identity = alerts[0]["id"]
    assert client.post("/api/alerts/read", json={"ids": [identity]}).status_code == 200
    assert next(
        a for a in client.get("/api/state").json()["alerts"] if a["id"] == identity
    )["read"]
    assert (
        client.post(
            "/api/alerts/read", json={"ids": [identity], "read": False}
        ).status_code
        == 200
    )
    assert not next(
        a for a in client.get("/api/state").json()["alerts"] if a["id"] == identity
    )["read"]
    assert identity not in Store(main.store.path).get("read_alerts", [])
    prefs = {
        **data["settings"],
        "price_threshold": 50,
        "volume_threshold": 20,
        "categories": [],
    }
    assert client.put("/api/settings", json=prefs).status_code == 200
    assert client.get("/api/state").json()["alerts"] == []
    assert (
        client.put("/api/settings", json={**prefs, "categories": ["bogus"]}).status_code
        == 422
    )


def test_research_cache_and_filing_detail(client, public_snapshot, monkeypatch):
    public_snapshot()

    async def report(symbol, question, store, *, use_ai=False):
        return {"symbol": symbol, "mode": "live", "comparisons": []}

    monkeypatch.setattr(main, "research", report)
    first = client.post("/api/research", json={"symbol": "POLYCAB"}).json()
    assert first["mode"] == "live"
    assert not first["cached"]
    assert client.post("/api/research", json={"symbol": "POLYCAB"}).json()["cached"]
    detail = client.get("/api/filings/tcs-results").json()
    assert detail["source"] == "NSE filing"
    assert detail["network"]["matches"][0]["id"] == "rohan"


def test_live_never_falls_back_to_demo(client, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(main.providers, "prices", unavailable)
    monkeypatch.setattr(main.providers, "announcements", unavailable)
    fixture_quote = {"close": 3064.24, "source": "Synthetic demo"}
    main.store.set("price:RELIANCE", fixture_quote, ttl=900)
    main.store.set(
        "snapshot:live",
        {
            **main.snapshot(),
            "prices": {"RELIANCE": fixture_quote},
            "filings": [{"mode": "demo"}],
        },
    )
    assert client.get("/api/state").json()["prices"] == {}
    assert client.get("/api/digest").json()["items"] == []
    response = client.post("/api/refresh", json={"mode": "live"})
    assert response.status_code == 200
    data = response.json()
    assert data["prices"] == {}
    assert data["filings"] == []
    assert len(data["errors"]) == 19
    assert client.get("/api/state?mode=demo").status_code == 422
    assert client.get("/api/digest?mode=demo").status_code == 422
    assert client.post("/api/refresh", json={"mode": "demo"}).status_code == 422
    assert (
        client.post("/api/research", json={"symbol": "TCS", "mode": "demo"}).status_code
        == 422
    )
    assert client.get("/api/demo/filings/demo-0").status_code == 404


def test_any_nse_ticker_can_be_added_and_researched(client, monkeypatch):
    async def price(symbol):
        assert symbol == "NEWCO"
        return {"name": "New Company", "close": 100}

    async def report(symbol, question, store, *, use_ai=False):
        assert symbol == "NEWCO"
        return {"symbol": symbol, "mode": "live", "sources": []}

    monkeypatch.setattr(main.providers, "prices", price)
    monkeypatch.setattr(main, "research", report)
    assert client.post("/api/portfolio", json={"symbol": "newco.ns"}).status_code == 200
    assert len(client.get("/api/state").json()["portfolio"]) == 19
    assert (
        client.post(
            "/api/research", json={"symbol": "NEWCO", "mode": "live"}
        ).status_code
        == 200
    )
    assert client.delete("/api/portfolio/NEWCO").status_code == 200


def test_security_and_static_content(client):
    assert (
        client.post(
            "/api/refresh", json={}, headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/refresh", content="{}", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    page = client.get("/")
    assert page.status_code == 200
    assert "viewport" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
