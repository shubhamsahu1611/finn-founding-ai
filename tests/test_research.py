import asyncio

import httpx
import pytest

from finn import providers
from research_fixtures import demo_comparisons, research_documents
from finn.providers import discover_html
from finn.research import (
    chunks,
    question_claim_matches,
    research,
    validate_claim,
    validate_comparisons,
)
from finn.store import Store


def test_public_feed_retries_transient_status_only(monkeypatch):
    attempts = []

    def responder(request):
        attempts.append(request.url.path)
        return httpx.Response(503 if len(attempts) < 3 else 200, request=request)

    async def no_delay(_):
        pass

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(responder)
        ) as client:
            return await providers.get_with_retry(client, "https://example.com/feed")

    monkeypatch.setattr(providers.asyncio, "sleep", no_delay)
    assert asyncio.run(run()).status_code == 200
    assert len(attempts) == 3


def test_public_feed_does_not_retry_permanent_error(monkeypatch):
    attempts = []

    def responder(request):
        attempts.append(1)
        return httpx.Response(404, request=request)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(responder)
        ) as client:
            await providers.get_with_retry(client, "https://example.com/missing")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
    assert len(attempts) == 1


def test_nse_announcement_adapter_uses_retry_client(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    batch = asyncio.run(providers.announcements(["TCS"]))
    assert batch.filings == []
    assert batch.warnings == []


def test_missing_nse_company_has_clear_coverage_error(monkeypatch):
    async def missing(url):
        request = httpx.Request("GET", url)
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("Not found", request=request, response=response)

    monkeypatch.setattr(providers, "fetch_bytes", missing)
    with pytest.raises(ValueError, match="No NSE company page found for NOPE"):
        asyncio.run(providers.discover("NOPE"))


def test_primary_link_discovery_excludes_secondary_summaries():
    html = """<h1>Example</h1><div class="annual-reports"><a href="https://company.test/ar.pdf">Annual Report 2026</a></div>
    <div class="concalls"><div>Sep 2026<a href="https://exchange.test/transcript.pdf">Transcript</a><a href="/ai">AI Summary</a><a href="/slides.pdf">PPT</a></div></div>
    <a href="https://broker.test/note.pdf">Broker research</a>"""
    found = discover_html(html, "EXAMPLE", "https://www.screener.in/company/EXAMPLE/")
    assert len(found["documents"]) == 2
    assert {d["kind"] for d in found["documents"]} == {"annual_report", "transcript"}


def test_invalid_citations_and_invented_quotes_are_rejected():
    evidence = {"a": {"text": "The company expects revenue growth of 12% next year."}}
    claim = {
        "text": "Management guided to 12% revenue growth.",
        "citation": "a",
        "quote": "expects revenue growth of 12% next year",
    }
    assert validate_claim(claim, evidence)
    assert not validate_claim({**claim, "citation": "invented"}, evidence)
    assert not validate_claim(
        {**claim, "quote": "expects revenue growth of 25% next year"}, evidence
    )


def test_short_brief_skips_transcript_boilerplate_and_keeps_the_citation():
    from finn.research import brief_evidence

    text = (
        "Final transcript of Example Limited's quarterly webinar. "
        "Republished with permission. All rights reserved. "
        "Revenue growth was 12% year on year, led by higher subscriptions."
    )
    source = {"id": "a", "text": text}
    (claim,) = brief_evidence([source], "revenue growth", "Financial snapshot")
    assert (
        claim["text"]
        == "Revenue growth was 12% year on year, led by higher subscriptions."
    )
    assert validate_claim(claim, {"a": source})


def test_ai_question_remains_unanswered_if_no_relevant_claim_passes(
    tmp_path, monkeypatch
):
    from finn import research as research_module

    documents = research_documents("TCS")
    documents[0]["pages"][0] += (
        " Thanks very much for all your questions and for participating."
    )

    async def discover(_symbol):
        return {"name": "Fixture", "documents": documents}

    async def document(meta, _store):
        return meta

    async def model(_task, corpus):
        source = next(item for item in corpus if "Thanks very much" in item["text"])
        return {
            "sections": [
                {
                    "title": "Your question",
                    "claims": [
                        {
                            "citation": source["id"],
                            "quote": "Thanks very much for all your questions and for participating.",
                            "text": "Thanks for participating.",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(providers, "discover", discover)
    monkeypatch.setattr(providers, "document", document)
    monkeypatch.setattr(research_module, "llm_json", model)
    result = asyncio.run(
        research(
            "TCS",
            "Can you explain the business segments?",
            Store(tmp_path / "qa.db"),
            use_ai=True,
        )
    )
    answer = next(s for s in result["sections"] if s["title"] == "Your question")
    assert answer["status"] == "unanswered"
    assert answer["claims"] == []
    assert result["analysis_notice"].startswith("Gemini found no claims")


def test_custom_answer_can_use_the_subject_identified_near_the_exact_quote():
    quote = "Higher subscription uptake and network expansion contributed."
    claim = {"text": "Homes grew as subscriptions rose and the network expanded.", "quote": quote}
    question = "What drove growth in the Homes segment in FY26?"
    assert question_claim_matches(
        claim, {"text": f"FY26 Homes review. {quote}"}, question
    )
    assert not question_claim_matches(
        claim, {"text": f"FY26 wholesale review. {quote}"}, question
    )


def test_source_reader_returns_primary_evidence_without_a_model(tmp_path, monkeypatch):
    documents = research_documents("TCS")

    async def discover(symbol):
        return {"name": "Fixture company", "documents": documents}

    async def document(meta, store):
        return meta

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(providers, "discover", discover)
    monkeypatch.setattr(providers, "document", document)
    report = asyncio.run(
        research("TCS", "cash conversion", Store(tmp_path / "finn.db"))
    )
    assert len(report["sections"]) == 9
    assert report["comparisons"] == []
    assert len(report["sources"]) == 5
    for section in report["sections"]:
        assert section["claims"]
        assert all(validate_claim(c, report["citations"]) for c in section["claims"])
    assert all(s["kind"] in {"annual_report", "transcript"} for s in report["sources"])
    trajectory = next(s for s in report["sections"] if s["title"] == "Trajectory")
    assert "revenue FY24" in trajectory["claims"][0]["text"]
    guidance = next(s for s in report["sections"] if s["title"] == "Guidance")
    assert "16%" in guidance["claims"][0]["text"]


def test_comparisons_require_both_sources():
    corpus = chunks(research_documents("INFY"))
    rows = demo_comparisons(corpus)
    evidence = {c["id"]: c for c in corpus}
    assert len(validate_comparisons(rows, evidence)) == 4
    rows[0]["actual_citation"] = "unverified"
    assert len(validate_comparisons(rows, evidence)) == 3


def test_read_state_and_cache_are_persistent(tmp_path):
    path = tmp_path / "finn.db"
    first = Store(path)
    first.set("settings", {"threshold": 4})
    first.append_unique("read", "signal-1")
    first.append_unique("read", "signal-1")
    second = Store(path)
    assert second.get("settings") == {"threshold": 4}
    assert second.get("read") == ["signal-1"]
