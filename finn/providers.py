"""Public-source adapters. Screener is used only to discover primary documents."""

import asyncio
import hashlib
import ipaddress
import logging
import socket
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from urllib.parse import quote, urljoin

import httpx
import pypdfium2
from bs4 import BeautifulSoup

from .domain import IST, classify, price_signal, ticker

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}
MAX_BYTES = 25 * 1024 * 1024
RETRY_STATUS = {429, 500, 502, 503, 504}
QUOTE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
logger = logging.getLogger(__name__)
pdf_lock = Lock()  # PDFium calls must be serialized, even across different documents.


@dataclass
class AnnouncementBatch:
    filings: list[dict]
    warnings: list[str]


async def get_with_retry(client, url, **kwargs):
    """Retry short-lived public-feed failures, leaving permanent errors visible."""
    for attempt in range(3):
        try:
            response = await client.get(url, **kwargs)
            if response.status_code not in RETRY_STATUS or attempt == 2:
                response.raise_for_status()
                return response
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt == 2:
                raise
        await asyncio.sleep(0.25 * (2**attempt))


def public_url(url):
    parsed = httpx.URL(url)
    if (
        parsed.scheme != "https"
        or not parsed.host
        or parsed.userinfo
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only public HTTPS source URLs are supported.")
    hostname = parsed.raw_host.decode("ascii")
    addresses = {
        ipaddress.ip_address(item[4][0])
        for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    }
    if not addresses or any(not ip.is_global or ip.is_multicast for ip in addresses):
        raise ValueError("Private or local source addresses are not allowed.")
    return parsed, hostname, sorted(addresses, key=lambda ip: ip.version)


async def fetch_bytes(url):
    # Validate every redirect; do not follow a document link into an internal service.
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=30,
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        async with asyncio.timeout(45):
            for _ in range(6):
                parsed, hostname, addresses = await asyncio.to_thread(public_url, url)
                for index, address in enumerate(addresses):
                    try:
                        # Connect to the validated address and verify TLS for the original host.
                        async with client.stream(
                            "GET",
                            parsed.copy_with(host=str(address)),
                            headers={"Host": parsed.netloc.decode("ascii")},
                            extensions={"sni_hostname": hostname},
                        ) as response:
                            if response.is_redirect and "location" in response.headers:
                                url = urljoin(str(parsed), response.headers["location"])
                                break
                            response.raise_for_status()
                            data = bytearray()
                            async for chunk in response.aiter_bytes():
                                data.extend(chunk)
                                if len(data) > MAX_BYTES:
                                    raise ValueError(
                                        "Source exceeds the 25 MB document limit."
                                    )
                            return bytes(data), response.headers.get("content-type", "")
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        if index == len(addresses) - 1:
                            raise
        raise ValueError("Too many source redirects.")


async def prices(symbol, market="NSE", *, allow_single_session=False):
    symbol = ticker(symbol)
    if market not in QUOTE_SUFFIX:
        raise ValueError("Unsupported price market.")
    suffix = QUOTE_SUFFIX[market]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}{suffix}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        response = await get_with_retry(
            client, url, params={"range": "3mo", "interval": "1d"}
        )
        result = response.json()["chart"].get("result")
    if not result:
        raise ValueError(f"No price history for this {market} symbol.")
    chart = result[0]
    data = chart["indicators"]["quote"][0]
    bars = [
        {
            "date": datetime.fromtimestamp(stamp, IST).date().isoformat(),
            "close": close,
            "volume": volume,
            **{
                field: data[field][index]
                for field in ("open", "high", "low")
                if index < len(data.get(field) or []) and data[field][index] is not None
            },
        }
        for index, (stamp, close, volume) in enumerate(
            zip(chart["timestamp"], data["close"], data["volume"])
        )
    ]
    return {
        **price_signal(bars, allow_single_session=allow_single_session),
        "source": f"Yahoo Finance · {market}",
        "source_url": f"https://finance.yahoo.com/quote/{quote(symbol)}{suffix}/",
        "currency": chart.get("meta", {}).get("currency", "INR"),
        "name": chart.get("meta", {}).get("longName", symbol),
    }


async def announcements(symbols, days=7):
    now = datetime.now(IST)
    url = "https://www.nseindia.com/api/corporate-announcements"
    async with httpx.AsyncClient(
        headers={
            **HEADERS,
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        },
        timeout=25,
        follow_redirects=True,
    ) as client:
        # Cookie warm-up can be blocked while the announcement endpoint still works.
        try:
            await client.get("https://www.nseindia.com", timeout=5)
        except httpx.RequestError as error:
            logger.debug("NSE cookie warm-up failed: %s", type(error).__name__)
        response = await get_with_retry(
            client,
            url,
            params={
                "index": "equities",
                "from_date": (now - timedelta(days=days)).strftime("%d-%m-%Y"),
                "to_date": now.strftime("%d-%m-%Y"),
            },
        )
        payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("NSE did not return an announcement list.")
    result = []
    skipped = 0
    for row in payload:
        if not isinstance(row, dict):
            skipped += 1
            continue
        if row.get("symbol") not in symbols:
            continue
        title = " · ".join(
            str(row.get(k) or "").strip()
            for k in ("desc", "attchmntText")
            if row.get(k)
        )
        category, priority, reason = classify(title)
        published = next(
            (
                stamp
                for field in ("an_dt", "sort_date", "broadcast_date")
                if (stamp := announcement_time(row.get(field)))
            ),
            None,
        )
        if not published:
            skipped += 1
            continue
        attachment = (
            row.get("attchmntFile")
            or "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
        )
        if not isinstance(attachment, str):
            skipped += 1
            continue
        if attachment.startswith("http://"):
            attachment = "https://" + attachment[7:]
        identity = str(
            row.get("seq_id") or f"{row['symbol']}:{published}:{title}:{attachment}"
        )
        result.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:20],
                "symbol": row["symbol"],
                "title": title,
                "summary": None,
                "category": category,
                "priority": priority,
                "reason": reason,
                "published_at": published,
                "source_url": attachment,
                "source": "NSE filing",
                "mode": "live",
            }
        )
    warnings = (
        [
            f"NSE announcements: skipped {skipped} malformed rows. Filing coverage may be incomplete."
        ]
        if skipped
        else []
    )
    return AnnouncementBatch(result, warnings)


def announcement_time(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) < 16:  # A date alone does not establish a publication time.
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                stamp = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=IST)).isoformat()


def discover_html(html, symbol, base):
    soup = BeautifulSoup(html, "html.parser")
    name = soup.find("h1")
    documents = []
    for selector, kind in [
        (".annual-reports", "annual_report"),
        (".concalls", "transcript"),
    ]:
        section = soup.select_one(selector)
        if not section:
            continue
        limit = 2 if kind == "annual_report" else 5
        for link in section.select("a[href]"):
            label = link.get_text(" ", strip=True)
            if kind == "transcript" and "transcript" not in label.lower():
                continue
            if kind == "annual_report" and "report" not in label.lower():
                continue
            url = urljoin(base, link["href"])
            if not url.startswith("https://"):
                continue
            # Only the AR and transcript link collections enter the research corpus.
            title = re.sub(
                r"\b(?:AI Summary|PPT|REC)\b", "", link.parent.get_text(" ", strip=True)
            ).strip()[:180]
            documents.append(
                {
                    "id": hashlib.sha256(url.encode()).hexdigest()[:16],
                    "title": title,
                    "url": url,
                    "kind": kind,
                }
            )
            limit -= 1
            if limit == 0:
                break
    unique = {d["url"]: d for d in documents}
    return {
        "symbol": symbol,
        "name": name.get_text(" ", strip=True) if name else symbol,
        "documents": list(unique.values()),
        "discovery_url": base,
    }


async def discover(symbol):
    symbol = ticker(symbol)
    base = f"https://www.screener.in/company/{quote(symbol)}/consolidated/"
    try:
        body, _ = await fetch_bytes(base)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise
        base = f"https://www.screener.in/company/{quote(symbol)}/"
        try:
            body, _ = await fetch_bytes(base)
        except httpx.HTTPStatusError as fallback_error:
            if fallback_error.response.status_code == 404:
                raise ValueError(
                    f"No NSE company page found for {symbol} at the document source. Check the ticker or source coverage."
                ) from fallback_error
            raise
    found = await asyncio.to_thread(
        discover_html, body.decode("utf-8", errors="replace"), symbol, base
    )
    if not found["documents"]:
        raise ValueError(
            "No annual-report or transcript links found. The symbol may be unavailable or the source layout may have changed."
        )
    return found


def parse_document(data, content_type):
    if data.startswith(b"%PDF"):
        pages = []
        with pdf_lock, pypdfium2.PdfDocument(data) as document:
            if len(document) > 1000:
                raise ValueError("Document exceeds 1,000 pages.")
            for index in range(len(document)):
                page = document[index]
                try:
                    text = page.get_textpage()
                    try:
                        pages.append(text.get_text_bounded()[:60000])
                    finally:
                        text.close()
                finally:
                    page.close()
    elif "html" in content_type:
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        pages = [soup.get_text(" ", strip=True)[:200000]]
    else:
        raise ValueError("Source is neither a PDF nor an HTML document.")
    if sum(len(p.strip()) for p in pages) < 150:
        raise ValueError(
            "No usable text. This PDF may require OCR, which is not enabled."
        )
    return pages


async def document(meta, store):
    key = f"document:v1:{meta['id']}"
    cached = await asyncio.to_thread(store.get, key)
    if cached:
        return cached
    body, kind = await fetch_bytes(meta["url"])
    pages = await asyncio.to_thread(parse_document, body, kind)
    result = {**meta, "pages": pages}
    await asyncio.to_thread(store.set, key, result, ttl=86400 * 7)
    return result
