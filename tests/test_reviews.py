import pytest
from fastapi.testclient import TestClient

from finn import main
from finn.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch, public_snapshot):
    monkeypatch.setattr(main, "store", Store(tmp_path / "reviews.db"))
    public_snapshot()
    with TestClient(main.app) as client:
        yield client


def test_review_actions_persist_without_overwriting_other_fields(client):
    url = "/api/filings/tcs-results/review"
    assert client.patch(url, json={"saved": True}).status_code == 200
    assert (
        client.patch(
            url, json={"note": "Check cash conversion next quarter."}
        ).status_code
        == 200
    )
    assert client.patch(url, json={"reviewed": True}).status_code == 200
    record = client.get("/api/state").json()["reviews"]["tcs-results"]
    assert record["saved"] and record["reviewed"]
    assert record["note"] == "Check cash conversion next quarter."
    assert record["updated_at"]
    # Reopen SQLite to prove persistence, rather than relying on in-memory state.
    reopened = Store(main.store.path)
    assert reopened.records("review:live:")["tcs-results"] == record
    result = client.patch(url, json={"reviewed": False, "note": ""}).json()
    assert result["saved"] is True
    assert result["reviewed"] is False and result["note"] == ""


def test_old_demo_reviews_are_excluded(client):
    main.store.set("review:demo:demo-0", {"saved": True})
    assert client.get("/api/state").json()["reviews"] == {}
    assert (
        client.patch(
            "/api/filings/tcs-results/review?mode=demo", json={"saved": True}
        ).status_code
        == 422
    )
    assert (
        client.patch("/api/filings/unknown/review", json={"saved": True}).status_code
        == 404
    )


def test_notes_validate_length_and_forbid_unknown_fields(client):
    url = "/api/filings/tcs-results/review"
    assert client.patch(url, json={"note": "x" * 1201}).status_code == 422
    assert client.patch(url, json={"priority": 99}).status_code == 422
    assert client.patch(url, json={}).status_code == 422
    # Treat all note content as plain data; rendering escapes it in the browser.
    note = '<script>alert("not executable")</script>'
    assert client.patch(url, json={"note": note}).json()["note"] == note


def test_reading_notes_never_change_the_source_filing(client):
    before = client.get("/api/filings/tcs-results").json()
    client.patch(
        "/api/filings/tcs-results/review",
        json={"saved": True, "note": "My interpretation"},
    )
    after = client.get("/api/filings/tcs-results").json()
    assert before == after
