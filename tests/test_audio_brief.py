from fastapi.testclient import TestClient

from finn import main
from finn.store import Store


def test_audio_generation_follows_digest_and_invalidates_when_facts_change(
    tmp_path, monkeypatch
):
    db = Store(tmp_path / "finn.db")
    monkeypatch.setattr(main, "store", db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    filing = {
        "symbol": "INFY",
        "title": "Quarterly financial results published",
        "priority": 90,
        "category": "results",
        "published_at": "2026-11-14T11:00:00+00:00",
        "mode": "live",
    }
    snapshot = {
        "filings": [
            filing,
            {
                **filing,
                "title": "Outside range",
                "published_at": "2026-11-12T11:00:00+00:00",
            },
        ],
        "prices": {
            "INFY": {
                "source": "Yahoo Finance · NSE",
                "date": "2026-11-13",
                "change_pct": 3.5,
                "close": 1141.50,
                "volume_ratio": 1.2,
                "baseline_sessions": 20,
            },
            "TCS": {
                "source": "Yahoo Finance · NSE",
                "date": "2026-11-13",
                "change_pct": -1.43,
            },
            "HDFCBANK": {
                "source": "Yahoo Finance · NSE",
                "date": "2026-11-12",
                "change_pct": 8.0,
            },
        },
    }
    db.set("snapshot:live", snapshot)
    calls = []

    async def gemini(_system, prompt, _schema, **_options):
        items = prompt["items"]
        calls.append(items)
        assert len(items) == 2
        assert "Outside range" not in items[0]["sentence"]
        assert items[1]["session"] == "13 November"
        return {
            "sentences": [
                "Infosys released its quarterly results.",
                # Wrong direction must fall back to the market data.
                "Infosys fell 3.5 percent in the 13 November session.",
            ],
        }

    monkeypatch.setattr(main, "generate_json", gemini)
    params = {
        "start": "2026-11-14T00:00:00+00:00",
        "end": "2026-11-15T00:00:00+00:00",
    }
    with TestClient(main.app) as client:

        def speak():
            response = client.post("/api/digest/audio", params=params, json={})
            assert response.status_code == 200, response.text
            return response.json()

        first = speak()
        assert first["engine"] == "gemini"
        assert first["script"].startswith("Infosys released its quarterly results.")
        assert "closed up 3.50 percent" in first["script"]
        assert "Check how revenue, margins and cash flow compare" in first["script"]
        assert "1141.50 rupees" in first["script"]
        assert "1.20 times its 20-session average" in first["script"]
        assert "1 closed higher and 1 closed lower" in first["script"]
        assert "fell" not in first["script"]
        assert speak() == first
        assert len(calls) == 1

        snapshot["prices"]["INFY"]["change_pct"] = 4.25
        db.set("snapshot:live", snapshot)
        updated = speak()
        assert len(calls) == 2
        assert "closed up 4.25 percent" in updated["script"]

        monkeypatch.delenv("GEMINI_API_KEY")
        fallback = speak()
        assert fallback["engine"] == "source"
        assert "closed up 4.25 percent" in fallback["script"]
