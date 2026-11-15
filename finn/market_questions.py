"""Route questions about the stock itself to completed trading-session data."""

import asyncio
import math
import re
from datetime import datetime

import httpx

from . import providers
from .domain import IST, change

MARKET_METRIC = re.compile(
    r"\b(?:stocks?|shares?)\s+(?:prices?|moves?|changes?|movement|performance|returns?|volume|patterns?|trends?|momentum)\b"
    r"|\b(?:closing prices?|last close|previous close|trading volume|market quote|ohlc)\b"
    r"|\b(?:stock|shares?)\s+(?:do|doing|did|moved?|fell|fall|rose|rise|down|up|trading)\b"
    r"|\b(?:fell|rose|closed|traded)\s+today\b"
    r"|\b(?:stock|share|trading|market|closing)\s+(?:price\s+)?(?:rally|sell[- ]?off|gap(?:ped)?|trend)\b"
    r"|\b(?:today|current|latest|intraday)\b.{0,24}\b(?:prices?|volume|quote|close)\b"
    r"|\b(?:prices?|volume|quote|close)\b.{0,20}\b(?:today|right now)\b",
    re.IGNORECASE,
)
NON_TRADING_REFERENCES = re.compile(
    r"\b(?:stock[- ]based|stock\s+(?:compensation|options?|grants?|splits?|exchange)|"
    r"share\s+(?:capital|count|buybacks?|repurchases?)|market\s+share|"
    r"(?:sales|production|shipment|operating)\s+volumes?)\b",
    re.IGNORECASE,
)
TECHNICAL_SIGNAL = re.compile(
    r"\b(?:technical analysis|price action|chart patterns?|moving averages?|"
    r"breakouts?|pullbacks?|consolidat(?:e|ed|ing|ion)|support (?:and resistance|levels?)|"
    r"resistance (?:and support|levels?)|(?:above|below|find|identify) (?:support|resistance))\b",
    re.IGNORECASE,
)
PATTERN_TERMS = re.compile(
    r"\b(?:patterns?|trends?|momentum|rally|rallied|rallies|volume|"
    r"trad(?:e|ing)|candlesticks?|intraday|ohlc)\b",
    re.IGNORECASE,
)
SECURITY_REFERENCE = re.compile(r"\b(?:stocks?|shares?|ticker)\b", re.IGNORECASE)
TRADING_BEHAVIOUR = re.compile(
    r"\b(?:behaviou?r|behav(?:e|ed|ing)|perform(?:ance|ed|ing)|trad(?:e|ed|ing)|"
    r"movement|moved?|fluctuat\w*|gain(?:ed|s)?|fall|fell|ris(?:e|ing)|rose|"
    r"up|down|flat|returns?)\b",
    re.IGNORECASE,
)
SESSION_REFERENCE = re.compile(
    r"\b(?:today|yesterday|intraday|right now|last (?:session|week|month)|"
    r"(?:latest|previous|current) (?:day|session))\b",
    re.IGNORECASE,
)
SESSION_QUESTION = re.compile(
    r"\b(?:how (?:did|has|is|was)|what happened)\b", re.IGNORECASE
)
DOCUMENT_CONTEXT = re.compile(
    r"\b(?:earnings|guidance|management|revenues?|sales|profits?|margins?|dividends?|"
    r"annual reports?|transcripts?|filings?|cash (?:flows?|conversion)|balance sheet|buybacks?|compensation|"
    r"inventor(?:y|ies)|capex|ebitda|eps|segments?)\b",
    re.IGNORECASE,
)
CLOSING_ONLY_PERIOD = re.compile(
    r"\b(?:this|last|past|previous)\s+(?:\d+\s+)?(?:days?|weeks?|months?|years?)\b"
    r"|\b(?:yesterday|weekly|monthly|year.to.date|ytd)\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
MARKET_CONTEXT_REQUEST = re.compile(
    r"\b(?:compare|also|and|alongside|versus|vs\.?|against|after|around)\b",
    re.IGNORECASE,
)
MIXED_CLAUSE_BREAK = re.compile(
    r"\s*[,;]\s*|\s+\b(?:and|also|then|alongside|versus|vs\.?)\b\s+",
    re.IGNORECASE,
)


def is_market_question(question, symbol=""):
    text = NON_TRADING_REFERENCES.sub(" ", question)
    if MARKET_METRIC.search(text):
        return True
    ticker_mentioned = symbol and re.search(
        rf"(?<!\w){re.escape(symbol)}(?!\w)", text, re.IGNORECASE
    )
    has_security = SECURITY_REFERENCE.search(text) or ticker_mentioned
    if TECHNICAL_SIGNAL.search(text) and (
        has_security or not DOCUMENT_CONTEXT.search(text)
    ):
        return True
    if DOCUMENT_CONTEXT.search(text):
        return False
    if PATTERN_TERMS.search(text) and (has_security or SESSION_REFERENCE.search(text)):
        return True
    return bool(
        has_security
        and (
            TRADING_BEHAVIOUR.search(text)
            or SESSION_REFERENCE.search(text)
            and SESSION_QUESTION.search(text)
        )
    )


def is_technical_question(question):
    return bool(PATTERN_TERMS.search(question) or TECHNICAL_SIGNAL.search(question))


def asks_for_company_context(question):
    return bool(
        DOCUMENT_CONTEXT.search(question) and MARKET_CONTEXT_REQUEST.search(question)
    )


def company_question(question, symbol):
    for separator in MIXED_CLAUSE_BREAK.finditer(question):
        left = question[: separator.start()].strip()
        right = question[separator.end() :].strip()
        if is_market_question(left, symbol) and DOCUMENT_CONTEXT.search(right):
            return right
        if DOCUMENT_CONTEXT.search(left) and is_market_question(right, symbol):
            return left
    return question


async def answer_market_question(
    symbol, question, store, saved, *, include_trend=False
):
    """Use the fresh quote cache first and clearly label any snapshot fallback."""
    key = f"price:{symbol}"
    price = await asyncio.to_thread(store.get, key)
    if not price or price.get("close") is None:
        try:
            async with asyncio.timeout(15):
                price = await providers.prices(symbol)
        except (
            TimeoutError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ):
            price = {**saved, "stale": True} if saved else None
        else:
            await asyncio.to_thread(store.set, key, price, ttl=900)

    notes = []
    trend = None
    technical = include_trend or is_technical_question(question)
    if CLOSING_ONLY_PERIOD.search(question):
        notes.append(
            "The trend uses the latest available completed sessions."
            if technical
            else "The requested period wasn’t calculated. This shows the latest completed session."
        )
    if price is None or price.get("close") is None:
        quote = None
        notes.append(
            "A completed-session quote is unavailable. Check the ticker or try again."
        )
    else:
        history = price.get("history") or []
        previous = price.get("previous_close")
        if previous is None and len(history) >= 2 and history[-1] == price["close"]:
            previous = history[-2]
        previous = previous if valid_price(previous) else None
        close = price["close"]
        quote = {
            "date": price["date"],
            "close": close,
            "previous_close": previous,
            "change": round(close - previous, 2) if previous is not None else None,
            "change_pct": change(close, previous),
            "volume": price.get("volume"),
            "volume_ratio": price.get("volume_ratio")
            if (price.get("baseline_sessions") or 0) >= 20
            else None,
            "source_url": price.get("source_url"),
            **{
                field: round(price[field], 2)
                for field in ("open", "high", "low")
                if valid_price(price.get(field))
            },
        }
        if technical:
            trend = closing_trend(history, close, price.get("history_start"))
            if trend is None:
                notes.append("Recent closing history is unavailable for this quote.")
        if price.get("stale"):
            notes.append("The price provider did not respond. This is a saved quote.")
        if re.search(r"\b(?:intraday|live|right now)\b", question, re.IGNORECASE):
            notes.append(
                "FINN shows completed sessions only. It has no live intraday feed."
            )
        elif (
            "today" in question.lower()
            and quote["date"] != datetime.now(IST).date().isoformat()
        ):
            notes.append(
                "No completed quote is available for today. Showing the latest completed session."
            )
        if re.search(r"\b(?:why|reason|cause|drove)\b", question, re.IGNORECASE):
            notes.append(
                "A quote shows the size of the move. It cannot establish what caused it."
            )

    return {
        "kind": "market",
        "mode": "live",
        "symbol": symbol,
        "name": price.get("name", symbol) if price else symbol,
        "question": question,
        "quote": quote,
        "trend": trend,
        "notes": notes,
    }


def valid_price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def closing_trend(history, close, start_date):
    closes = [round(value, 2) for value in (history or [])[-30:] if valid_price(value)]
    if len(closes) < 2 or closes[-1] != round(close, 2):
        return None
    high = max(closes)
    return {
        "closes": closes,
        "start_date": start_date,
        "sessions": len(closes),
        "first_close": closes[0],
        "high_close": high,
        "low_close": min(closes),
        "return_pct": change(closes[-1], closes[0]),
        "five_session_return_pct": change(closes[-1], closes[-6])
        if len(closes) >= 6
        else None,
        "drawdown_pct": change(closes[-1], high),
        "average_20_close": round(sum(closes[-20:]) / 20, 2)
        if len(closes) >= 20
        else None,
    }


def market_evidence(answer):
    quote = answer["quote"]
    if quote is None:
        return None
    metrics = {
        f"session_{name}": quote.get(name)
        for name in (
            "open",
            "high",
            "low",
            "close",
            "previous_close",
            "change",
            "change_pct",
            "volume",
            "volume_ratio",
        )
    }
    trend = answer["trend"] or {}
    metrics.update(
        {
            f"window_{name}": value
            for name, value in trend.items()
            if name not in {"closes", "start_date"}
        }
    )
    return {
        "symbol": answer["symbol"],
        "currency": "INR",
        "session_date": quote["date"],
        "source": "Yahoo Finance · NSE",
        "source_url": quote["source_url"],
        "window_start_date": trend.get("start_date"),
        "closing_prices_oldest_first": trend.get("closes", []),
        "metrics": {
            name: value for name, value in metrics.items() if value is not None
        },
    }


MARKET_INSTRUCTION = (
    "Answer the trading question in up to two short sentences using only the dated Yahoo Finance evidence. "
    "Explain how the latest move and volume fit the recent closing trend when relevant. Use ₹ for prices and "
    "describe relative volume in plain English as a multiple of average volume. Do not infer causation, "
    "predict moves, give trading advice, or claim live intraday coverage. Daily open, high, low and close show "
    "only the session range, with no intraday sequence. Treat closing highs and lows as reference levels, "
    "not established support or resistance. Use only figures from the selected metric keys, preserve their "
    "precision, and omit the date and window size in the prose. Say 'latest session' instead of 'today'. "
    "Volume ratio is versus the prior 20 sessions."
)


def market_output_schema(evidence):
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": MARKET_INSTRUCTION},
            "metrics": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {"type": "string", "enum": list(evidence["metrics"])},
            },
        },
        "required": ["text", "metrics"],
    }


def validate_market_analysis(result, evidence):
    if not isinstance(result, dict) or not evidence:
        return None
    text, names = result.get("text"), result.get("metrics")
    if not isinstance(text, str) or not 15 <= len(text.strip()) <= 360:
        return None
    values = evidence["metrics"]
    if (
        not isinstance(names, list)
        or not names
        or len(names) > 6
        or any(not isinstance(name, str) or name not in values for name in names)
    ):
        return None
    allowed = {values[name] for name in names}
    if "session_volume_ratio" in names or "window_average_20_close" in names:
        allowed.add(20)
    if "window_five_session_return_pct" in names:
        allowed.add(5)
    magnitudes = {abs(value) for value in allowed}
    for sign, number in re.findall(r"([+−-]?)₹?(\d[\d,]*(?:\.\d+)?)", text):
        value = float(number.replace(",", ""))
        if sign in ("-", "−") and -value not in allowed:
            return None
        if sign == "+" and value not in allowed:
            return None
        if value not in magnitudes:
            return None
    return {"text": text.strip(), "metrics": list(dict.fromkeys(names))}
