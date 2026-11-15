from datetime import date

import pytest
from fastapi.testclient import TestClient

from finn import main, network
from finn.network_data import Role
from finn.store import Store
from finn.domain import IST
from datetime import datetime


@pytest.fixture
def client(tmp_path, monkeypatch, public_snapshot):
    monkeypatch.setattr(main, "store", Store(tmp_path / "network.db"))
    today = max(datetime.now(IST).date(), date(2026, 11, 13))
    monkeypatch.setattr(network, "local_date", lambda: today)
    public_snapshot()
    with TestClient(main.app) as client:
        yield client


def test_real_filing_suggests_company_contacts_without_linking_fictional_executive(
    client,
):
    detail = client.get("/api/filings/hdfc-management").json()
    assert detail["network"]["matches"][0]["id"] == "dev"
    assert "executive" not in detail["network"]
    digest = client.get("/api/digest").json()["items"]
    row = next(item for item in digest if item["id"] == "hdfc-management")
    assert row["network"]["matches"] == detail["network"]["matches"][:1]
    alert = next(
        item
        for item in client.get("/api/state").json()["alerts"]
        if item.get("filing_id") == "hdfc-management"
    )
    assert alert["network"]["matches"] == detail["network"]["matches"][:1]
    assert all("network" not in item for item in digest if item["priority"] < 50)

    profile = client.get("/api/network/people/ananya").json()
    assert [(path["id"], path["kind"]) for path in profile["paths"]] == [
        ("dev", "Reported collaboration"),
        ("isha", "Education overlap"),
    ]
    assert "Cedar Commercial Bank · 2017–2020" in profile["paths"][0]["support"][0]
    assert "2004–2005" in profile["paths"][1]["evidence"]


def test_overlap_requires_intersecting_year_ranges():
    first = Role("cedar", "Role A", 2017, 2020)
    second = Role("cedar", "Role B", 2020, 2022)
    assert network.overlap(first, second, 2026) is None


def test_company_and_theme_queries_explain_different_connections(client):
    def search(question):
        return client.get("/api/network", params={"q": question}).json()

    assert len(search("")["starters"]) == 4
    assert search("Who knows ANaNyA Rao?")["profiles"][0]["id"] == "ananya"
    matches = search("Who can I call about Dixon?")["groups"][0]["matches"]
    assert matches[0]["id"] == "arjun"
    assert {person["kind"] for person in matches} == {
        "Former employee",
        "Supplier",
        "Customer",
    }
    theme = search("Who knows chip packaging?")["groups"][0]
    assert theme["title"] == "Semiconductors"
    assert {person["id"] for person in theme["matches"]} == {"arjun", "leena"}
    assert search("Who knows semiconductorization?")["groups"] == []
    assert client.get("/api/network", params={"q": "x" * 161}).status_code == 422


def test_conversation_updates_reconnect_and_cached_research_without_changing_sources(
    client,
    monkeypatch,
):
    async def sourced_report(symbol, question, store, *, use_ai=False):
        return {
            "symbol": symbol,
            "mode": "live",
            "citations": {"c1": {"text": "Public source fixture"}},
            "sections": [{"title": "Cash quality"}],
        }

    monkeypatch.setattr(main, "research", sourced_report)

    def reconnect():
        return client.get(
            "/api/network", params={"q": "Who should I reconnect with?"}
        ).json()["groups"][0]["matches"]

    assert {item["id"] for item in reconnect()} == {"arjun", "rohan"}
    report = client.post("/api/research", json={"symbol": "TCS"}).json()
    assert report["network"]["matches"][0]["days_since"] >= 90
    history = "/api/network/contacts/rohan/history"
    assert client.put(history, json={"spoken": True}).json()["days_since"] == 0
    assert (
        Store(main.store.path).get("network:spoken:rohan")["date"]
        == network.local_date().isoformat()
    )
    assert {item["id"] for item in reconnect()} == {"arjun"}
    cached = client.post("/api/research", json={"symbol": "TCS"}).json()
    assert cached["cached"]
    assert cached["network"]["matches"][0]["days_since"] == 0
    assert cached["citations"] == report["citations"]
    assert cached["sections"] == report["sections"]
    assert client.put(history, json={"spoken": False}).json()["days_since"] >= 90
    assert {item["id"] for item in reconnect()} == {"arjun", "rohan"}


def test_undo_restores_prior_logged_date(client):
    path = "/api/network/contacts/rohan/history"
    previous = "2026-01-02"
    main.store.set("network:spoken:rohan", {"date": previous})
    for _ in range(2):
        assert client.put(path, json={"spoken": True}).json()["days_since"] == 0
    for _ in range(2):
        assert client.put(path, json={"spoken": False}).json()["last_spoke"] == previous


def test_external_profile_cannot_be_logged_as_a_direct_contact(client):
    assert (
        client.put(
            "/api/network/contacts/ananya/history", json={"spoken": True}
        ).status_code
        == 404
    )
    assert client.get("/api/network/people/unknown").status_code == 404
