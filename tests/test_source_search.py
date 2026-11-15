from fastapi.testclient import TestClient

from finn import main
from finn.store import Store


def test_source_search_finds_cached_transcript_pages(monkeypatch, tmp_path):
    store = Store(tmp_path / "sources.db")
    monkeypatch.setattr(main, "store", store)
    transcript = {
        "id": "call",
        "title": "Earnings call",
        "kind": "transcript",
        "url": "https://example.test/call.pdf",
    }
    annual_report = {**transcript, "id": "annual", "kind": "annual_report"}
    missing = {**transcript, "id": "unavailable"}
    store.set("discovery:TCS", {"documents": [transcript, annual_report, missing]})
    store.set(
        "document:v1:call", {"pages": ["Intro", "Our Operating\nMargin improved."]}
    )
    store.set("document:v1:annual", {"pages": ["Our operating margin fell."]})

    client = TestClient(main.app)
    response = client.get(
        "/api/research/tcs/sources/search", params={"q": "operating margin"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "documents": 1,
        "more": False,
        "results": [
            {
                "title": transcript["title"],
                "url": transcript["url"],
                "kind": transcript["kind"],
                "page": 2,
                "before": "Our ",
                "match": "Operating Margin",
                "after": " improved.",
            }
        ],
    }
    literal = client.get("/api/research/TCS/sources/search", params={"q": ".+"})
    assert literal.json()["results"] == []
    assert client.get("/api/research/TCS/sources/search?q=%20%20").status_code == 422
    assert (
        client.get("/api/research/TCS/sources/search?q=margin&kind=all").json()[
            "documents"
        ]
        == 2
    )

    store.set("document:v1:call", {"pages": ["Operating margin improved."] * 21})
    capped = client.get("/api/research/TCS/sources/search?q=margin").json()
    assert len(capped["results"]) == 20 and capped["more"]
