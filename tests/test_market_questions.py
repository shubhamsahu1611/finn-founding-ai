from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from finn import main, market_questions
from finn import research as research_module
from finn.store import Store
from research_fixtures import research_documents


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Summarize today's stock changes", "auto"),
        ("What was behaviour of this stock today?", "auto"),
        ("How did BHARTIARTL do today?", "auto"),
        ("How has the share performed?", "auto"),
        ("", "market"),
    ],
)
def test_stock_change_prompt_uses_completed_quotes_without_gemini(
    question,
    intent,
    tmp_path,
    monkeypatch,
):
    store = Store(tmp_path / "finn.db")
    monkeypatch.setattr(main, "store", store)
    today = market_questions.datetime.now(market_questions.IST).date()
    yesterday = (today - timedelta(days=1)).isoformat()

    async def quote(symbol):
        assert symbol == "BHARTIARTL"
        return {
            "date": yesterday,
            "close": 102,
            "previous_close": 100,
            "volume": 1000,
            "volume_ratio": 1.25,
            "baseline_sessions": 20,
            "source_url": "https://finance.yahoo.com/quote/BHARTIARTL.NS/",
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("A stock-move question must not run document research")

    monkeypatch.setattr(main.providers, "prices", quote)
    monkeypatch.setattr(main, "research", forbidden)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/research",
            json={
                "symbol": "BHARTIARTL",
                "question": question,
                "intent": intent,
                "use_ai": True,
            },
        )
    assert response.status_code == 200
    result = response.json()
    assert result["kind"] == "market"
    assert result["quote"]["date"] == yesterday
    assert result["quote"]["change"] == 2
    assert result["quote"]["change_pct"] == 2
    assert result["quote"]["volume_ratio"] == 1.25
    if "today" in question:
        assert any("today" in note for note in result["notes"])


@pytest.mark.parametrize(
    "question",
    [
        "How did stock compensation affect profit?",
        "How did share buybacks affect cash flow?",
        "How has BHARTIARTL performed on revenue and cash flow?",
        "What did management say about market share today?",
        "What was the latest sales volume?",
    ],
)
def test_company_questions_still_go_to_documents(question):
    assert not market_questions.is_market_question(question, "BHARTIARTL")


@pytest.mark.parametrize(
    "question",
    [
        "Analyze today's stock pattern for this stock",
        "Did SUNPHARMA's rally stall?",
        "Is it consolidating?",
        "What are the support and resistance levels?",
        "How's trading volume today?",
    ],
)
def test_trading_pattern_phrases_route_to_market_analysis(question):
    assert market_questions.is_market_question(question, "SUNPHARMA")
    assert market_questions.is_technical_question(question)


def test_stock_pattern_supplies_current_session_and_history_to_gemini(
    tmp_path, monkeypatch
):
    db = Store(tmp_path / "finn.db")
    monkeypatch.setattr(main, "store", db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    db.set(
        "price:SUNPHARMA",
        {
            "date": "2026-11-13",
            "source_url": "https://finance.yahoo.com/quote/SUNPHARMA.NS/",
            "close": 106,
            "open": 109,
            "high": 110,
            "low": 105,
            "volume": 10000,
            "volume_ratio": 0.88,
            "baseline_sessions": 20,
            "history": [100, 103, 110, 106],
        },
    )
    calls = []

    async def model(_system, prompt, schema, **_kwargs):
        evidence = prompt["market_evidence"]
        calls.append(prompt)
        assert evidence["session_date"] == "2026-11-13"
        assert evidence["closing_prices_oldest_first"] == [100, 103, 110, 106]
        assert evidence["metrics"]["session_open"] == 109
        assert evidence["metrics"]["session_volume_ratio"] == 0.88
        assert evidence["metrics"]["window_return_pct"] == 6
        assert "session_change_pct" in schema["properties"]["metrics"]["items"]["enum"]
        return {
            "text": "The stock pulled back from its closing high of ₹110 on 0.88× average volume.",
            "metrics": ["window_high_close", "session_volume_ratio"],
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("A trading-only question must use the quote path")

    monkeypatch.setattr(main, "generate_json", model)
    monkeypatch.setattr(main, "research", forbidden)
    body = {
        "symbol": "SUNPHARMA",
        "question": "Analyze today's stock pattern for this stock",
        "use_ai": True,
    }
    with TestClient(main.app) as client:
        for _ in range(2):
            response = client.post("/api/research", json=body)
            assert response.status_code == 200
            result = response.json()
            assert result["kind"] == "market"
            assert result["analysis"]["text"].startswith("The stock pulled back")
            assert result["trend"]["sessions"] == 4
    assert len(calls) == 1


def test_mixed_question_supplies_market_and_document_evidence_together(
    tmp_path, monkeypatch
):
    db = Store(tmp_path / "finn.db")
    monkeypatch.setattr(main, "store", db)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    db.set(
        "price:TCS",
        {
            "date": "2026-11-13",
            "close": 102,
            "history": [100, 102],
        },
    )
    documents = research_documents("TCS")

    async def discover(_symbol):
        return {"name": "Fixture", "documents": documents}

    async def document(meta, _store):
        return meta

    async def model(_system, prompt, schema):
        assert "market_analysis" in schema["properties"]
        assert prompt["task"]["question"] == "the company's cash conversion."
        assert prompt["task"]["market_context"]["closing_prices_oldest_first"] == [
            100,
            102,
        ]
        source = next(
            item for item in prompt["evidence"] if "cash conversion 80%" in item["text"]
        )
        return {
            "market_analysis": {
                "text": "The shares closed higher at ₹102.",
                "metrics": ["session_close"],
            },
            "sections": [
                {
                    "title": "Your question",
                    "claims": [
                        {
                            "text": "Cash conversion was 80%.",
                            "citation": source["citation"],
                            "quote": "cash conversion 80%",
                        }
                    ],
                }
            ],
            "comparisons": [],
        }

    monkeypatch.setattr(main.providers, "discover", discover)
    monkeypatch.setattr(main.providers, "document", document)
    monkeypatch.setattr(research_module, "generate_json", model)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/research",
            json={
                "symbol": "TCS",
                "question": "Show the stock price and the company's cash conversion.",
                "use_ai": True,
            },
        )
    assert response.status_code == 200
    report = response.json()
    assert report["market"]["analysis"]["metrics"] == ["session_close"]
    answer = next(
        section for section in report["sections"] if section["title"] == "Your question"
    )
    assert answer["status"] == "analysis"
    assert answer["claims"][0]["citation"] in report["citations"]


def test_market_analysis_rejects_figures_absent_from_its_evidence():
    evidence = {"metrics": {"session_change_pct": -0.27}}
    for figure in ("+0.27", "-4.52"):
        assert (
            market_questions.validate_market_analysis(
                {
                    "text": f"The stock moved {figure}% during the last session.",
                    "metrics": ["session_change_pct"],
                },
                evidence,
            )
            is None
        )


def test_saved_quote_is_marked_and_does_not_invent_a_reason(tmp_path, monkeypatch):
    store = Store(tmp_path / "finn.db")
    monkeypatch.setattr(main, "store", store)
    store.set(
        "snapshot:live",
        {
            "mode": "live",
            "filings": [],
            "prices": {
                "INFY": {
                    "source": "Yahoo Finance · NSE",
                    "date": "2026-11-13",
                    "close": 96,
                    "history": [100, 96],
                },
            },
        },
    )

    async def unavailable(_symbol):
        raise httpx.ConnectError("Offline")

    monkeypatch.setattr(main.providers, "prices", unavailable)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/research",
            json={
                "symbol": "INFY",
                "question": "Why did the stock fall last week?",
            },
        )
    assert response.status_code == 200
    result = response.json()
    assert result["quote"]["change_pct"] == -4
    assert any("period wasn’t calculated" in note for note in result["notes"])
    assert any("saved quote" in note for note in result["notes"])
    assert any("cannot establish" in note for note in result["notes"])
