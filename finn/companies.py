"""Search the public Indian equity listings and fetch a quote on selection."""

import asyncio
import gzip
import io
import json
import re
import time
from functools import lru_cache
from urllib.parse import quote
from weakref import WeakKeyDictionary

import httpx

from . import providers

EXCHANGES = ("NSE", "BSE")
DIRECTORY_TTL = 24 * 60 * 60
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024
SHARE_SERIES = {
    "NSE": {"EQ", "BE", "BZ", "SM", "ST", "SZ"},
    "BSE": {"A", "B", "E", "M", "MS", "MT", "P", "R", "T", "TS", "X", "XT", "Z", "ZP"},
}
directory_locks = {exchange: asyncio.Lock() for exchange in EXCHANGES}
directory_cache = WeakKeyDictionary()
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9&_-]{0,24}")
ISIN = re.compile(r"INE[A-Z0-9]{8}[0-9]")


def listings_from_file(data, exchange):
    if data.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as archive:
            data = archive.read(MAX_DIRECTORY_BYTES + 1)
    if len(data) > MAX_DIRECTORY_BYTES:
        raise ValueError("Instrument directory exceeds the size limit.")
    payload = json.loads(data)
    if not isinstance(payload, list):
        raise TypeError("Unexpected instrument directory format.")
    listings = {}
    for row in payload:
        if (
            not isinstance(row, dict)
            or row.get("segment") != f"{exchange}_EQ"
            or row.get("instrument_type") not in SHARE_SERIES[exchange]
        ):
            continue
        symbol = str(row.get("trading_symbol") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        isin = str(row.get("isin") or "").strip()
        code = str(row.get("exchange_token") or "") if exchange == "BSE" else None
        if not name or not SYMBOL.fullmatch(symbol) or not ISIN.fullmatch(isin):
            continue
        if exchange == "BSE" and not re.fullmatch(r"[0-9]{6}", code):
            continue
        listings[symbol] = {
            "name": name,
            "symbol": symbol,
            "exchange": exchange,
            "code": code,
            "isin": isin,
        }
    if not listings:
        raise ValueError("No equity listings found in the instrument directory.")
    return list(listings.values())


async def directory(exchange, store):
    key = f"companies:directory:v1:{exchange}"
    async with directory_locks[exchange]:
        memory = directory_cache.setdefault(store, {})
        cached = memory.get(exchange)
        if cached is None:
            cached = await asyncio.to_thread(store.get, key)
            if cached:
                memory[exchange] = cached
        if cached and time.time() - cached["fetched_at"] < DIRECTORY_TTL:
            return cached["listings"], None
        if not await asyncio.to_thread(store.get, f"{key}:retry"):
            try:
                url = f"https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
                async with asyncio.timeout(12):
                    data, _ = await providers.fetch_bytes(url)
                    listings = await asyncio.to_thread(
                        listings_from_file, data, exchange
                    )
            except (OSError, EOFError, TypeError, ValueError, httpx.HTTPError):
                await asyncio.to_thread(store.set, f"{key}:retry", True, ttl=60)
            else:
                cached = {"listings": listings, "fetched_at": time.time()}
                await asyncio.to_thread(store.set, key, cached)
                memory[exchange] = cached
                return listings, None
        if cached:
            return cached[
                "listings"
            ], f"{exchange} directory refresh failed. Showing saved listings."
        return [], f"{exchange} directory is temporarily unavailable."


@lru_cache(maxsize=16000)
def name_tokens(value):
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return tuple(
        word for word in words if word not in {"co", "company", "ltd", "limited"}
    )


def match_rank(listing, query, words):
    symbol = listing["symbol"].lower()
    if query in (symbol, listing["isin"].lower(), listing["code"]):
        return 0
    name = name_tokens(listing["name"])
    if words and name == words:
        return 1
    if symbol.startswith(query) or (words and name[: len(words)] == words):
        return 2
    if words and all(any(token.startswith(word) for token in name) for word in words):
        return 3
    return None


async def search(query, store):
    directories = await asyncio.gather(
        *(directory(exchange, store) for exchange in EXCHANGES)
    )
    return await asyncio.to_thread(rank_listings, query, directories)


def rank_listings(query, directories):
    value = query.strip().lower()
    selected_exchange = None
    if value.endswith((".ns", ".bo")):
        value, suffix = value.rsplit(".", 1)
        selected_exchange = "NSE" if suffix == "ns" else "BSE"
    words = name_tokens(value)
    matches = []
    warnings = []
    for listings, warning in directories:
        if warning:
            warnings.append(warning)
        for listing in listings:
            if selected_exchange and listing["exchange"] != selected_exchange:
                continue
            rank = match_rank(listing, value, words)
            if rank is not None:
                matches.append((rank, listing))
    matches.sort(
        key=lambda item: (item[0], item[1]["symbol"], item[1]["exchange"] != "NSE")
    )
    return {"items": [listing for _, listing in matches[:12]], "warnings": warnings}


async def lookup(exchange, symbol, store):
    listings, warning = await directory(exchange, store)
    if not listings:
        raise ConnectionError(warning)
    listing = next((item for item in listings if item["symbol"] == symbol), None)
    if listing is None:
        return None
    source_symbol = quote(symbol, safe="")
    suffix = providers.QUOTE_SUFFIX[exchange]
    quote_url = f"https://finance.yahoo.com/quote/{source_symbol}{suffix}/"
    if exchange == "BSE":
        slug = "-".join(re.findall(r"[a-z0-9]+", listing["name"].lower()))
        exchange_url = f"https://www.bseindia.com/stock-share-price/{slug}/{source_symbol.lower()}/{listing['code']}/"
    else:
        exchange_url = (
            f"https://www.nseindia.com/get-quotes/equity?symbol={source_symbol}"
        )
    warnings = [warning] if warning else []
    key = f"companies:quote:{exchange}:{symbol}"
    price = await asyncio.to_thread(store.get, key)
    if price is None:
        try:
            price = await providers.prices(
                symbol, market=exchange, allow_single_session=True
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            warnings.append(
                "Yahoo Finance did not return a completed-session quote for this listing."
            )
        else:
            await asyncio.to_thread(store.set, key, price, ttl=900)
    research_symbol = symbol if exchange == "NSE" else None
    if exchange == "BSE":
        nse_listings, nse_warning = await directory("NSE", store)
        research_symbol = next(
            (
                item["symbol"]
                for item in nse_listings
                if item["isin"] == listing["isin"]
            ),
            None,
        )
        if nse_warning and not research_symbol:
            warnings.append(nse_warning)
    return {
        **listing,
        "research_symbol": research_symbol,
        "quote": price,
        "quote_url": quote_url,
        "exchange_url": exchange_url,
        "warnings": warnings,
    }
