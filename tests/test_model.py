"""Exercise optional AI contracts without credentials or network calls."""

import asyncio
import json
from importlib import import_module

import httpx
import pytest
from fastapi.testclient import TestClient
from research_fixtures import research_documents
from finn import main
from finn.research import supported_number
from finn.store import Store

research_module = import_module("finn.research")


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected"),
    [
        (
            400,
            {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]},
            {},
            "rejected the API key (HTTP 400)",
        ),
        (
            429,
            {"status": "RESOURCE_EXHAUSTED"},
            {"Retry-After": "25"},
            "Wait at least 25 seconds",
        ),
        (429, {"status": "RESOURCE_EXHAUSTED"}, {}, "rate or quota limit"),
        (403, {"status": "PERMISSION_DENIED"}, {}, "check the key's restrictions"),
        (503, {"status": "UNAVAILABLE"}, {}, "temporarily unavailable"),
    ],
)
def test_gemini_errors_explain_the_reason_without_exposing_provider_text(
    status, body, headers, expected
):
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com")
    body = {**body, "message": "Private provider detail"}
    response = httpx.Response(
        status, request=request, json={"error": body}, headers=headers
    )
    with pytest.raises(httpx.HTTPStatusError) as error:
        response.raise_for_status()
    message = research_module.model_error_message(error.value)
    assert expected.lower() in message.lower()
    assert "Private provider detail" not in message


def test_numeric_cells_must_exist_in_evidence():
    assert supported_number(1200, "Revenue 1,200; prior quarter 1,100")
    assert not supported_number(9999, "Revenue 1,200; prior quarter 1,100")
    assert not supported_number(float("nan"), "Revenue NaN")
    assert not supported_number(True, "Revenue 1")
    assert supported_number(None, "Not disclosed")


def test_live_model_accepts_supported_claim_and_drops_invented_quote(
    tmp_path, monkeypatch
):
    documents = research_documents("TCS")

    async def discover(symbol):
        return {"name": "Fixture company", "documents": documents}

    async def document(meta, store):
        return meta

    async def model(task, corpus):
        source = next(c for c in corpus if "cash conversion 80%" in c["text"])
        return {
            "sections": [
                {
                    "title": "Cash quality",
                    "claims": [
                        {
                            "text": "Operating cash conversion was 80% in the supplied fixture.",
                            "citation": source["id"],
                            "quote": "cash conversion 80%",
                        }
                    ],
                },
                {
                    "title": "Business snapshot",
                    "claims": [
                        {
                            "text": "Unsupported claim",
                            "citation": source["id"],
                            "quote": "The company sells flying bicycles to Mars.",
                        }
                    ],
                },
            ],
            "comparisons": [],
        }

    monkeypatch.setattr(research_module.providers, "discover", discover)
    monkeypatch.setattr(research_module.providers, "document", document)
    monkeypatch.setattr(research_module, "llm_json", model)
    report = asyncio.run(
        research_module.research(
            "ANYNSE", "cash conversion", Store(tmp_path / "db"), use_ai=True
        )
    )
    cash = next(s for s in report["sections"] if s["title"] == "Cash quality")
    business = next(s for s in report["sections"] if s["title"] == "Business snapshot")
    assert cash["status"] == "analysis"
    assert business["status"] == "evidence"
    assert "flying bicycles" not in str(report)
    assert report["mode"] == "live"


def test_model_failure_retains_source_reader(tmp_path, monkeypatch):
    documents = research_documents("INFY")

    async def discover(symbol):
        return {"name": "Fixture", "documents": documents}

    async def document(meta, store):
        return meta

    async def failed(*args, **kwargs):
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com")
        response = httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "message": "Invalid fixture-secret",
                    "details": [{"reason": "API_KEY_INVALID"}],
                }
            },
        )
        response.raise_for_status()

    monkeypatch.setattr(research_module.providers, "discover", discover)
    monkeypatch.setattr(research_module.providers, "document", document)
    monkeypatch.setattr(research_module, "llm_json", failed)
    report = asyncio.run(
        research_module.research("ANYNSE", "", Store(tmp_path / "db"), use_ai=True)
    )
    assert any(
        "rejected the API key (HTTP 400)" in warning for warning in report["warnings"]
    )
    assert "fixture-secret" not in str(report)
    assert report["engine"] == "Source excerpts · no model cost"
    assert all(s["status"] == "evidence" for s in report["sections"])


def test_slow_documents_return_partial_evidence(tmp_path, monkeypatch):
    fast = research_documents("TCS")[0]
    slow = {**fast, "id": "slow", "title": "Slow report"}
    cancelled = False

    async def discover(symbol):
        return {"name": "Fixture", "documents": [fast, slow]}

    async def document(meta, store):
        nonlocal cancelled
        if meta is fast:
            return meta
        try:
            await asyncio.Future()
        finally:
            cancelled = True

    async def model(*args, **kwargs):
        raise AssertionError("Source research must not invoke a model")

    monkeypatch.setattr(research_module.providers, "discover", discover)
    monkeypatch.setattr(research_module.providers, "document", document)
    monkeypatch.setattr(research_module, "DOCUMENT_BATCH_TIMEOUT", 0.05)
    monkeypatch.setattr(research_module, "llm_json", model)
    result = asyncio.run(research_module.research("TCS", "", Store(tmp_path / "db")))
    assert [doc["id"] for doc in result["sources"]] == [fast["id"]]
    assert result["discovered_count"] == 2
    assert any("Slow report" in warning for warning in result["warnings"])
    assert result["citations"]
    assert cancelled


def test_gemini_only_runs_on_explicit_ai_actions_and_reuses_cache(
    tmp_path, monkeypatch, public_snapshot
):
    store = Store(tmp_path / "db")
    monkeypatch.setattr(main, "store", store)
    public_snapshot()
    monkeypatch.setattr(main, "enrich_filing", research_module.enrich_filing)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-secret")
    documents = research_documents("TCS")
    calls = []

    async def discover(symbol):
        return {"name": "Fixture", "documents": documents}

    async def document(meta, store):
        if meta["kind"] != "filing":
            return meta
        return {
            **meta,
            "pages": ["Revenue was 1,200 crore in the current quarter. " * 8],
        }

    async def prices(symbol):
        return {"source": "Yahoo Finance · NSE"}

    async def announcements(*args):
        return main.providers.AnnouncementBatch([], [])

    def gemini(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert (
            str(request.url)
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        )
        if request.headers["x-goog-api-key"] == "rejected-fixture":
            return httpx.Response(
                400, json={"error": {"details": [{"reason": "API_KEY_INVALID"}]}}
            )
        assert request.headers["x-goog-api-key"] == "fixture-secret"
        assert "authorization" not in request.headers
        config = payload["generationConfig"]
        assert config["maxOutputTokens"] == 5000
        assert config["responseMimeType"] == "application/json"
        if "sections" in json.loads(payload["contents"][0]["parts"][0]["text"])["task"]:
            assert config["responseJsonSchema"]["type"] == "object"
            assert config["responseJsonSchema"]["properties"]["sections"]["items"][
                "properties"
            ]["title"]["enum"] == ["Your question"]
        assert (
            "ONLY the supplied evidence"
            in payload["systemInstruction"]["parts"][0]["text"]
        )
        prompt = json.loads(payload["contents"][0]["parts"][0]["text"])
        source = prompt["evidence"][0]
        claim = {
            "text": source["text"][:25],
            "quote": source["text"][:25],
            "citation": source["citation"],
        }
        output = {
            "sections": [
                {"title": title, "claims": [claim]}
                for title in prompt["task"].get("sections", [])
            ],
            "summary": claim,
        }
        serialized = json.dumps(output)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "thought": True,
                                    "text": "Internal reasoning is not output.",
                                },
                                {"text": serialized[:40]},
                                {"text": serialized[40:]},
                            ]
                        },
                    }
                ]
            },
        )

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        research_module.httpx,
        "AsyncClient",
        lambda **kw: async_client(transport=httpx.MockTransport(gemini), **kw),
    )
    monkeypatch.setattr(main.providers, "discover", discover)
    monkeypatch.setattr(main.providers, "document", document)
    monkeypatch.setattr(main.providers, "prices", prices)
    monkeypatch.setattr(main.providers, "announcements", announcements)
    with TestClient(main.app) as client:
        state = client.get("/api/state")
        assert state.json()["model_configured"]
        assert state.json()["model_name"] == "gemini-3.1-flash-lite"
        assert "fixture-secret" not in state.text
        assert client.post("/api/refresh", json={}).status_code == 200
        assert client.get("/api/digest").status_code == 200
        filing = "/api/filings/tcs-results"
        assert client.get(filing).json()["evidence"]
        request = {"symbol": "TCS", "question": "cash conversion"}
        assert (
            client.post("/api/research", json=request)
            .json()["engine"]
            .startswith("Source excerpts")
        )
        assert calls == []

        # Simulate a 401 persisted by an older FINN run, before the key was replaced.
        research_cache = main.analysis_cache_key(
            "research:v8", ["TCS", "live", request["question"]], main.model_target()
        )
        filing_cache = main.analysis_cache_key(
            "filing:v3", ["live", "tcs-results"], main.model_target()
        )
        store.set(
            research_cache, {"engine": "Source excerpts", "warnings": ["HTTP 401"]}
        )
        store.set(filing_cache, {"extraction_note": "HTTP 401"})
        monkeypatch.setenv("GEMINI_API_KEY", "rejected-fixture")
        failure = client.post("/api/research", json={**request, "use_ai": True}).json()
        assert not failure["cached"]
        assert any("HTTP 400" in warning for warning in failure["warnings"])
        failure = client.post(filing + "/analyze", json={}).json()
        assert not failure["cached"]
        assert "HTTP 400" in failure["extraction_note"]
        assert store.get(research_cache)["warnings"] == ["HTTP 401"]
        assert store.get(filing_cache)["extraction_note"] == "HTTP 401"
        assert len(calls) == 2
        monkeypatch.setenv("GEMINI_API_KEY", "fixture-secret")

        for _ in range(2):
            assert (
                client.post("/api/research", json={**request, "use_ai": True})
                .json()["engine"]
                .startswith("AI analysis")
            )
            assert client.post(filing + "/analyze", json={}).json()["summary"]
        assert len(calls) == 4
        assert not client.get(filing).json().get("summary")
        assert (
            client.post("/api/research", json=request)
            .json()["engine"]
            .startswith("Source excerpts")
        )
        assert len(calls) == 4

        monkeypatch.delenv("GEMINI_API_KEY")
        monkeypatch.setenv("OPENAI_API_KEY", "legacy-fixture")
        assert not client.get("/api/state").json()["model_configured"]
        assert client.post(filing + "/analyze", json={}).status_code == 409
        assert (
            client.post("/api/research", json={**request, "use_ai": True}).status_code
            == 409
        )
        assert len(calls) == 4
