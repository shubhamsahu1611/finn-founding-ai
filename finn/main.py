"""Run with: python -m uvicorn finn.main:app --host 127.0.0.1 --port 8000."""

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import (
    audio_brief,
    companies,
    market_questions,
    network,
    providers,
    watchlist,
)
from .domain import CATEGORIES, DEFAULT_SETTINGS, make_alerts, now_iso, ticker
from .research import (
    enrich_filing,
    generate_json,
    model_error_message,
    model_target,
    research,
    search_cached_sources,
)
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
store = Store(os.getenv("FINN_DB", str(ROOT / "data" / "finn.db")))
refresh_lock = asyncio.Lock()
research_slots = asyncio.Semaphore(2)
ai_requests = asyncio.Lock()
started_at = time.monotonic()


def portfolio():
    return store.get("portfolio", watchlist.portfolio())


def settings():
    return {**DEFAULT_SETTINGS, **store.get("settings", {})}


def snapshot():
    data = store.get(
        "snapshot:live",
        {
            "prices": {},
            "filings": [],
            "updated_at": None,
            "errors": ["Live sources have not been refreshed yet."],
            "mode": "live",
            "coverage_days": 0,
        },
    )
    prices = {
        symbol: price
        for symbol, price in data["prices"].items()
        if price.get("source") == "Yahoo Finance · NSE"
    }
    filings = [filing for filing in data["filings"] if filing.get("mode") == "live"]
    metadata = (
        "updated_at",
        "errors",
        "coverage_days",
        "filings_updated_at",
        "filings_coverage_start",
        "filings_incomplete",
    )
    return {
        **{key: data[key] for key in metadata if key in data},
        "mode": "live",
        "prices": prices,
        "filings": filings,
    }


async def refresh_live(days=7):
    if refresh_lock.locked():
        raise HTTPException(409, "A refresh is already running.")
    async with refresh_lock:
        old = await asyncio.to_thread(snapshot)
        symbols = [p["symbol"] for p in await asyncio.to_thread(portfolio)]
        prices = {s: p for s, p in old["prices"].items() if s in symbols}
        errors, semaphore = [], asyncio.Semaphore(4)

        async def fetch_price(symbol):
            async with semaphore:
                try:
                    value = await asyncio.to_thread(store.get, f"price:{symbol}")
                    if not value or value.get("source") != "Yahoo Finance · NSE":
                        value = await providers.prices(symbol)
                        await asyncio.to_thread(
                            store.set, f"price:{symbol}", value, ttl=900
                        )
                    prices[symbol] = {**value, "stale": False}
                except Exception as error:
                    errors.append(
                        f"{symbol} prices: {type(error).__name__}. Source unavailable."
                    )
                    if symbol in prices:
                        prices[symbol]["stale"] = True

        async def fetch_filings():
            try:
                batch = await providers.announcements(symbols, days)
                errors.extend(batch.warnings)
                return batch.filings, not batch.warnings
            except Exception as error:
                errors.append(
                    f"NSE announcements: {type(error).__name__}. Last successful filings retained; coverage may be incomplete."
                )
                return [], False

        (filings, complete), *_ = await asyncio.gather(
            fetch_filings(), *(fetch_price(s) for s in symbols)
        )
        merged = {f["id"]: f for f in old["filings"] if f["symbol"] in symbols}
        merged.update({f["id"]: f for f in filings})
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        filings = [
            f
            for f in merged.values()
            if datetime.fromisoformat(f["published_at"]) >= cutoff
        ]
        updated_at = now_iso()
        old_start = filing_coverage_start(old)
        new_start = datetime.fromisoformat(updated_at) - timedelta(days=days)
        old_end = old.get("filings_updated_at")
        if old_start and old_end and datetime.fromisoformat(old_end) >= new_start:
            new_start = min(old_start, new_start)
        result = {
            "mode": "live",
            "prices": prices,
            "filings": filings,
            "updated_at": updated_at,
            "errors": errors,
            "filings_updated_at": updated_at if complete else old_end,
            "filings_coverage_start": max(new_start, cutoff).isoformat()
            if complete
            else old_start.isoformat()
            if old_start
            else None,
            "filings_incomplete": not complete,
            "coverage_days": days if complete else old.get("coverage_days", 0),
        }
        await asyncio.to_thread(store.set, "snapshot:live", result)
        return result


async def scheduled_refresh():
    last_attempt = time.monotonic()
    last_purge = last_attempt
    while True:
        await asyncio.sleep(30)
        if time.monotonic() - last_purge >= 3600:
            last_purge = time.monotonic()
            with suppress(sqlite3.Error):
                await asyncio.to_thread(store.purge_expired)
        preferences = await asyncio.to_thread(settings)
        if (
            preferences["auto_refresh"]
            and time.monotonic() - last_attempt >= preferences["poll_minutes"] * 60
        ):
            last_attempt = time.monotonic()
            with suppress(Exception):
                await refresh_live()


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(store.purge_expired)
    task = asyncio.create_task(scheduled_refresh())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="FINN", version="2.0.0", lifespan=lifespan)


@app.middleware("http")
async def headers(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/")}
        if render_url := os.getenv("RENDER_EXTERNAL_URL"):
            allowed.add(render_url.rstrip("/"))
        allowed.update(
            value.strip().rstrip("/")
            for value in os.getenv("FINN_ALLOWED_ORIGINS", "").split(",")
            if value.strip()
        )
        if origin and (origin == "null" or origin not in allowed):
            return JSONResponse(
                {"detail": "Cross-origin writes are not allowed."}, status_code=403
            )
        content_type = (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if request.method != "DELETE" and content_type != "application/json":
            return JSONResponse({"detail": "Use application/json."}, status_code=415)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def invalid(request, error):
    return JSONResponse({"detail": str(error)}, status_code=422)


class Preferences(BaseModel):
    price_threshold: float = Field(ge=0.1, le=50)
    volume_threshold: float = Field(ge=1, le=20)
    categories: list[str] = Field(max_length=17)
    poll_minutes: int = Field(ge=5, le=1440)
    auto_refresh: bool

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, value):
        if any(c not in CATEGORIES for c in value):
            raise ValueError("Unknown announcement category.")
        return list(dict.fromkeys(value))


class Company(BaseModel):
    symbol: str = Field(max_length=28)


class ResearchRequest(Company):
    mode: Literal["live"] = "live"
    intent: Literal["auto", "market"] = "auto"
    question: str = Field(default="", max_length=500)
    use_ai: bool = False


class RefreshRequest(BaseModel):
    mode: Literal["live"] = "live"
    days: int = Field(default=7, ge=1, le=90)


class FilingAnalysis(BaseModel):
    mode: Literal["live"] = "live"


class ReadRequest(BaseModel):
    ids: list[str] = Field(max_length=200)
    read: bool = True


class FilingReview(BaseModel):
    model_config = {"extra": "forbid"}
    saved: bool | None = None
    reviewed: bool | None = None
    note: str | None = Field(default=None, max_length=1200)


class ContactHistory(BaseModel):
    model_config = {"extra": "forbid"}
    spoken: bool


def with_filing_network(filing, history, today, limit=3):
    context = network.filing_context(filing, history, today, limit)
    return {**filing, "network": context} if context else filing


@app.get("/api/health")
def health():
    try:
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        last_refresh = store.get("snapshot:live", {}).get("updated_at")
    except sqlite3.Error:
        return JSONResponse(
            {"status": "unhealthy", "database": "unavailable"}, status_code=503
        )
    return {
        "status": "ok",
        "database": "ok",
        "uptime_seconds": round(time.monotonic() - started_at),
        "last_live_refresh": last_refresh,
    }


@app.get("/api/state")
def state(mode: Literal["live"] = "live"):
    data = snapshot()
    holdings, preferences = portfolio(), settings()
    symbols = {p["symbol"] for p in holdings}
    data["prices"] = {s: p for s, p in data["prices"].items() if s in symbols}
    data["filings"] = [f for f in data["filings"] if f["symbol"] in symbols]
    alerts = make_alerts(data["filings"], data["prices"], preferences, mode)
    read = set(store.get("read_alerts", []))
    history, today = network.contact_history(store), network.local_date()
    by_id = {f["id"]: f for f in data["filings"]}
    for alert in alerts:
        filing = by_id.get(alert.get("filing_id"))
        if filing and (
            context := network.filing_context(filing, history, today, limit=1)
        ):
            alert["network"] = context
        alert["read"] = alert["id"] in read
    target = model_target()
    return {
        **data,
        "portfolio": holdings,
        "settings": preferences,
        "alerts": alerts,
        "reviews": store.records(f"review:{mode}:"),
        "network_starters": network.STARTERS,
        "network_search": {
            "people": [person.name for person in network.PROFILES.values()],
            "themes": [label for label, _ in network.THEMES.values()],
        },
        "categories": [{"id": k, "label": v[1]} for k, v in CATEGORIES.items()],
        "research_companies": [
            {"symbol": s, "name": n} for s, n in watchlist.RESEARCH_COMPANIES
        ],
        "model_configured": bool(target),
        "model_name": target[1] if target else None,
    }


def filing_coverage_start(data):
    if "filings_coverage_start" in data:
        start = data["filings_coverage_start"]
        return datetime.fromisoformat(start) if start else None
    stamp = data.get("filings_updated_at") or data["updated_at"]
    return (
        datetime.fromisoformat(stamp) - timedelta(days=data["coverage_days"])
        if stamp and data["coverage_days"]
        else None
    )


def filing_window(hours, start, end):
    if not 1 <= hours <= 2160:
        raise ValueError("Choose a window between 1 hour and 90 days.")
    finish = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
    begin = datetime.fromisoformat(start) if start else finish - timedelta(hours=hours)
    if (
        begin.tzinfo is None
        or finish.tzinfo is None
        or begin >= finish
        or finish - begin > timedelta(days=90)
    ):
        raise ValueError("Use an ordered, timezone-aware window of at most 90 days.")
    return begin, finish


def filings_in_window(data, symbols, begin, finish):
    items = [
        f
        for f in data["filings"]
        if f["symbol"] in symbols
        and begin <= datetime.fromisoformat(f["published_at"]) <= finish
    ]
    items.sort(
        key=lambda f: (f["priority"], datetime.fromisoformat(f["published_at"])),
        reverse=True,
    )
    return items


@app.get("/api/digest")
def digest(
    mode: Literal["live"] = "live",
    hours: int = 24,
    start: str | None = None,
    end: str | None = None,
):
    begin, finish = filing_window(hours, start, end)
    data = snapshot()
    symbols = {p["symbol"] for p in portfolio()}
    items = filings_in_window(data, symbols, begin, finish)
    history, today = network.contact_history(store), network.local_date()
    items = [with_filing_network(f, history, today, limit=1) for f in items]
    coverage_start = filing_coverage_start(data)
    return {
        "items": items,
        "start": begin.isoformat(),
        "end": finish.isoformat(),
        "routine_count": sum(f["priority"] < 50 for f in items),
        "coverage_warning": "Some requested dates have not been fetched. Refresh this window to load available filings."
        if data.get("filings_incomplete")
        or coverage_start is None
        or begin < coverage_start - timedelta(minutes=1)
        else None,
    }


def audio_facts(begin, finish):
    data, holdings = snapshot(), portfolio()
    symbols = {p["symbol"] for p in holdings}
    items = filings_in_window(data, symbols, begin, finish)
    prices = {s: p for s, p in data["prices"].items() if s in symbols and p.get("date")}
    return audio_brief.source_facts(items, prices, holdings, settings())


@app.post("/api/digest/audio")
async def digest_audio(
    hours: int = 24, start: str | None = None, end: str | None = None
):
    begin, finish = filing_window(hours, start, end)
    facts, breadth = await asyncio.to_thread(audio_facts, begin, finish)
    if not facts:
        return {
            "script": breadth
            or "No material filings or unusual stock moves are loaded for this brief.",
            "engine": "source",
        }
    target = model_target()
    if target:
        key = analysis_cache_key("daily-audio:v2", [facts, breadth], target)
        try:
            async with asyncio.timeout(12), ai_requests:
                cached = await asyncio.to_thread(store.get, key)
                if cached:
                    return cached
                items = [
                    {key: value for key, value in fact.items() if key != "follow_up"}
                    for fact in facts
                ]
                result = await generate_json(
                    audio_brief.SYSTEM,
                    {"items": items},
                    audio_brief.SCHEMA,
                    max_tokens=1000,
                )
                script, used_model = audio_brief.render_script(facts, breadth, result)
                if used_model:
                    brief = {"script": script, "engine": "gemini"}
                    await asyncio.to_thread(store.set, key, brief, ttl=86400)
                    return brief
        except (TimeoutError, ValueError, TypeError, httpx.HTTPError):
            pass
    script, _ = audio_brief.render_script(facts, breadth)
    return {"script": script, "engine": "source"}


@app.post("/api/refresh")
async def refresh(body: RefreshRequest):
    return await refresh_live(body.days)


@app.put("/api/settings")
def save_settings(body: Preferences):
    store.set("settings", body.model_dump())
    return settings()


@app.post("/api/portfolio")
async def add_company(body: Company):
    symbol = ticker(body.symbol)

    def validate(holdings):
        if any(item["symbol"] == symbol for item in holdings):
            raise HTTPException(409, "This company is already in your portfolio.")
        if len(holdings) >= 50:
            raise ValueError("The prototype supports up to 50 companies.")

    validate(await asyncio.to_thread(portfolio))
    # Validate against the live provider; do not silently accept a typo as a listed company.
    try:
        price = await providers.prices(symbol)
    except Exception as error:
        raise HTTPException(
            502,
            "Could not verify this NSE ticker with the price source. Check the symbol and try again.",
        ) from error

    def add(holdings):
        validate(holdings)
        return [
            *holdings,
            {
                "symbol": symbol,
                "name": price.get("name", symbol),
                "sector": "Added by you",
                "size": "Unspecified",
            },
        ]

    holdings = await asyncio.to_thread(
        store.update, "portfolio", watchlist.portfolio(), add
    )
    await asyncio.to_thread(store.set, f"price:{symbol}", price, ttl=900)
    return {"portfolio": holdings}


@app.delete("/api/portfolio/{symbol}")
def remove_company(symbol: str):
    symbol = ticker(symbol)

    def remove(holdings):
        remaining = [item for item in holdings if item["symbol"] != symbol]
        if not remaining:
            raise ValueError("Keep at least one company in the portfolio.")
        return remaining

    return {"portfolio": store.update("portfolio", watchlist.portfolio(), remove)}


@app.post("/api/alerts/read")
def mark_read(body: ReadRequest):
    for identity in body.ids:
        if not identity or len(identity) > 150:
            raise ValueError("Invalid alert ID.")
    store.set_membership("read_alerts", body.ids, body.read)
    return {"ok": True}


@app.get("/api/companies/search")
async def company_search(q: str):
    if not 2 <= len(q.strip()) <= 100:
        raise ValueError(
            "Enter a company name, ticker, BSE code or ISIN (2–100 characters)."
        )
    return await companies.search(q, store)


@app.get("/api/companies/{exchange}/{symbol}")
async def company_lookup(exchange: Literal["NSE", "BSE"], symbol: str):
    identity = symbol.strip().upper()
    if not companies.SYMBOL.fullmatch(identity):
        raise ValueError("Enter a valid equity ticker.")
    try:
        result = await companies.lookup(exchange, identity, store)
    except ConnectionError as error:
        raise HTTPException(503, str(error)) from error
    if result is None:
        raise HTTPException(
            404, "This equity listing was not found in the company directory."
        )
    return result


@app.get("/api/network")
def search_network(
    q: str = "", hours: int = 168, start: str | None = None, end: str | None = None
):
    if len(q) > 160:
        raise ValueError("Use a Network question of 160 characters or fewer.")
    holdings = portfolio()
    symbols = {p["symbol"] for p in holdings}
    begin, finish = filing_window(hours, start, end)
    return network.query_network(
        q.strip(),
        [
            f
            for f in snapshot()["filings"]
            if f["symbol"] in symbols
            and begin <= datetime.fromisoformat(f["published_at"]) <= finish
        ],
        network.contact_history(store),
        network.local_date(),
        holdings,
    )


@app.get("/api/network/people/{identity}")
def network_person(identity: str):
    if identity not in network.PROFILES:
        raise HTTPException(404, "Profile unavailable in this workspace.")
    return network.person_profile(
        identity, network.contact_history(store), network.local_date(), portfolio()
    )


@app.put("/api/network/contacts/{identity}/history")
def update_contact_history(identity: str, body: ContactHistory):
    person = network.PROFILES.get(identity)
    if not person or not person.relationship:
        raise HTTPException(404, "Contact unavailable in this workspace.")
    today = network.local_date()
    key = f"network:spoken:{identity}"
    date_value = today.isoformat()

    def change_history(current):
        if body.spoken and current.get("date") != date_value:
            return {"date": date_value, "previous": current.get("date")}
        if not body.spoken and current.get("date") == date_value:
            return {"date": current.get("previous")}
        return current

    updated = store.update(key, {}, change_history)
    return network.contact_details(identity, {identity: updated}, today)


@app.post("/api/research")
async def company_research(body: ResearchRequest):
    try:
        async with asyncio.timeout(90 if body.use_ai else 50):
            return await build_research(body)
    except TimeoutError as error:
        raise HTTPException(
            504,
            str(error) or "Research reached its time limit. Please try again shortly.",
        ) from error


@app.get("/api/research/{symbol}/sources/search")
def search_research_sources(
    symbol: str,
    q: str = Query(min_length=2, max_length=100),
    kind: Literal["all", "transcript", "annual_report"] = "transcript",
):
    if len(q.strip()) < 2:
        raise ValueError("Enter at least two characters.")
    return search_cached_sources(store, ticker(symbol), q, kind)


async def build_research(body):
    symbol = ticker(body.symbol)
    question = body.question.strip()
    if body.intent == "market" or market_questions.is_market_question(question, symbol):
        return await build_market_research(body, symbol, question)
    target = require_model() if body.use_ai else None
    return await build_document_research(body.mode, symbol, question, target)


async def build_market_research(body, symbol, question):
    data = await asyncio.to_thread(snapshot)
    mixed = body.intent == "auto" and market_questions.asks_for_company_context(
        question
    )
    answer = await market_questions.answer_market_question(
        symbol, question, store, data["prices"].get(symbol), include_trend=mixed
    )
    technical = mixed or market_questions.is_technical_question(question)
    target = model_target() if body.use_ai and technical else None
    evidence = market_questions.market_evidence(answer) if technical else None
    if body.use_ai and evidence and not target:
        answer["notes"].append(
            "Gemini is disabled. Showing the latest available market data."
        )
    if mixed:
        try:
            report = await build_document_research(
                body.mode,
                symbol,
                market_questions.company_question(question, symbol),
                target,
                market_context={**evidence, "question": question} if evidence else None,
            )
        except (TimeoutError, ValueError, HTTPException):
            answer["notes"].append(
                "Company documents were unavailable for this question."
            )
        else:
            answer["analysis"] = report.pop("market_analysis", None)
            return {**report, "market": answer}
    if evidence and target:
        await add_market_analysis(answer, evidence, target)
    return answer


async def add_market_analysis(answer, evidence, target):
    key = analysis_cache_key(
        "market-analysis:v1", [answer["question"], evidence], target
    )
    async with ai_requests:
        analysis = await asyncio.to_thread(store.get, key)
        if analysis is None:
            try:
                generated = await generate_json(
                    market_questions.MARKET_INSTRUCTION,
                    {"question": answer["question"], "market_evidence": evidence},
                    market_questions.market_output_schema(evidence),
                    max_tokens=1200,
                )
                analysis = market_questions.validate_market_analysis(
                    generated, evidence
                )
            except (TimeoutError, ValueError, TypeError, httpx.HTTPError) as error:
                answer["notes"].append(model_error_message(error))
                return
            if analysis is not None:
                await asyncio.to_thread(store.set, key, analysis, ttl=900)
    if analysis is None:
        answer["notes"].append(
            "Gemini analysis was unavailable. Showing the calculated market data."
        )
    else:
        answer["analysis"] = analysis


async def build_document_research(
    mode, symbol, question, target, *, market_context=None
):
    cache_namespace = "research:v8" if target else "research:source:v7"
    fields = [symbol, mode, question]
    if market_context is not None and target:
        fields.append(market_context)
    key = analysis_cache_key(cache_namespace, fields, target)
    async with ai_requests if target else research_slots:
        report = await asyncio.to_thread(store.get, key)
        cached = report is not None and (not target or has_research_analysis(report))
        if not cached:
            try:
                options = {"market_context": market_context} if market_context else {}
                report = await research(
                    symbol, question, store, use_ai=bool(target), **options
                )
            except (TimeoutError, ValueError):
                raise
            except Exception as error:
                raise HTTPException(
                    502,
                    "Research source unavailable. Try again later; no unsupported analysis was generated.",
                ) from error
            if not target or has_research_analysis(report):
                incomplete = len(report.get("sources", [])) < report.get(
                    "discovered_count", 0
                )
                ttl = 300 if incomplete else 21600
                await asyncio.to_thread(store.set, key, report, ttl=ttl)
    result = {**report, "cached": cached}
    context = network.research_context(
        symbol,
        await asyncio.to_thread(network.contact_history, store),
        network.local_date(),
    )
    if context:
        result["network"] = context
    return result


def has_research_analysis(report):
    return bool(report.get("comparisons") or report.get("market_analysis")) or any(
        section.get("status") == "analysis" for section in report.get("sections", [])
    )


@app.get("/api/filings/{identity}")
async def filing_detail(identity: str, mode: Literal["live"] = "live"):
    return await read_filing(identity, mode)


@app.post("/api/filings/{identity}/analyze")
async def analyze_filing(identity: str, body: FilingAnalysis):
    target = require_model()
    async with ai_requests:
        return await read_filing(identity, body.mode, target)


def require_model():
    target = model_target()
    if not target:
        raise HTTPException(
            409,
            "AI is disabled. Set GEMINI_API_KEY in your environment and restart FINN.",
        )
    return target


def analysis_cache_key(namespace, fields, target):
    # Include endpoint and model in the cache identity, never the credential.
    digest = hashlib.sha256(
        json.dumps([fields, target[:2] if target else None]).encode()
    )
    return f"{namespace}:{digest.hexdigest()}"


async def read_filing(identity, mode, target=None):
    data = await asyncio.to_thread(snapshot)
    filing = next((f for f in data["filings"] if f["id"] == identity), None)
    if not filing:
        raise HTTPException(404, "Filing not found.")
    key = analysis_cache_key("filing:v3", [mode, identity], target)
    result = await asyncio.to_thread(store.get, key)
    cached = result is not None and (not target or has_filing_analysis(result, filing))
    if not cached:
        try:
            result = await enrich_filing(filing, store, use_ai=bool(target))
        except Exception:
            result = {
                **filing,
                "extraction_note": "The attachment could not be read. Open the original exchange filing to review it.",
            }
        else:
            if not target or has_filing_analysis(result, filing):
                await asyncio.to_thread(store.set, key, result, ttl=21600)
    history = await asyncio.to_thread(network.contact_history, store)
    if target:
        result = {**result, "cached": cached}
    return with_filing_network(result, history, network.local_date())


def has_filing_analysis(result, filing):
    return bool(
        result.get("results")
        or result.get("management")
        or result.get("summary") != filing.get("summary")
    )


@app.patch("/api/filings/{identity}/review")
def review_filing(identity: str, body: FilingReview, mode: Literal["live"] = "live"):
    if not any(f["id"] == identity for f in snapshot()["filings"]):
        raise HTTPException(404, "Filing not found.")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise ValueError("Choose a review action or enter a note.")
    return store.patch(f"review:{mode}:{identity}", {**fields, "updated_at": now_iso()})


@app.get("/")
def index():
    return FileResponse(
        ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"}
    )


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
