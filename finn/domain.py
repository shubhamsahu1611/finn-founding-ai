"""Pure calculations and transparent filing-priority rules."""

import re
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
CATEGORIES = {
    "results": (
        90,
        "Results",
        r"financial results|quarterly results|annual results|results|financial statements",
    ),
    "M&A": (
        90,
        "Mergers & acquisitions",
        r"acquisition|merger|demerger|joint venture|stake sale|subsidiary",
    ),
    "fund_raise": (
        75,
        "Fund raising",
        r"fund rais|rights issue|qip|preferential|buyback|commercial paper|debenture",
    ),
    "management_change": (
        85,
        "Management",
        r"resign|appoint.*(?:ceo|cfo|director|officer)|chief|managing director|retirement",
    ),
    "litigation": (
        90,
        "Litigation",
        r"litigation|penalty|fine\b|regulatory order|insolvency|lawsuit|warning",
    ),
    "insider_trading": (
        65,
        "Insider trading",
        r"insider|personal shareholding|disclosure.*(?:pit|sast)",
    ),
    "earnings_call": (
        45,
        "Earnings calls",
        r"earnings call|conference call|concall|transcript|audio recording",
    ),
    "investor_meetings": (
        15,
        "Investor meetings",
        r"investor meet|analyst meet|investor conference|institutional investor",
    ),
    "credit_rating": (
        60,
        "Credit rating",
        r"credit rating|rating.*(?:upgrade|downgrade|reaffirm)",
    ),
    "dividend": (55, "Dividend", r"dividend"),
    "bonus_split": (60, "Bonus / split", r"bonus|stock split|sub.division"),
    "capex": (
        75,
        "Capital expenditure",
        r"capex|capacity expansion|new plant|capital expenditure",
    ),
    "press_release": (
        40,
        "Press release",
        r"press release|order win|product launch|partnership|clarification",
    ),
    "postal_ballot": (10, "Postal ballot", r"postal ballot"),
    "agm_egm": (
        10,
        "Shareholder meetings",
        r"annual general|extraordinary general|agm|egm",
    ),
    "pledging": (80, "Promoter pledging", r"pledge|pledging|encumbrance"),
    "unclassified": (5, "Routine filings", r".*"),
}
DEFAULT_SETTINGS = {
    "price_threshold": 3.0,
    "volume_threshold": 2.0,
    "categories": ["results", "M&A", "management_change", "litigation", "pledging"],
    "poll_minutes": 30,
    "auto_refresh": False,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ticker(value):
    value = value.strip().upper()
    if value.endswith(".NS"):
        value = value[:-3]
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9&_-]{0,24}", value):
        raise ValueError("Enter a valid NSE symbol, for example INFY or M&M.")
    return value


def classify(title):
    # Specific document types win over incidental words such as 'results'.
    if re.search(r"auditor|secretarial compliance|esop|esg report", title, re.I):
        return "unclassified", 5, "Routine compliance; retained for completeness."
    if re.search(r"(?:redemption|repayment) of commercial paper", title, re.I):
        return "unclassified", 15, "Debt repayment notice; not a new fund raise."
    for key in ["earnings_call", "investor_meetings", "postal_ballot", "agm_egm"]:
        score, _, pattern = CATEGORIES[key]
        if re.search(pattern, title, re.I):
            return key, score, "Supporting disclosure; available in the full digest."
    for key, (score, label, pattern) in CATEGORIES.items():
        if re.search(pattern, title, re.I):
            if key == "results" and re.search(
                r"board meeting|newspaper|publication", title, re.I
            ):
                return (
                    key,
                    20,
                    "Results-related notice, not the actual financial results.",
                )
            if key == "credit_rating" and re.search(r"downgrad", title, re.I):
                score = 90
            return (
                key,
                score,
                f"{label}: review the source for its effect on earnings, capital or governance."
                if score >= 50
                else "Low-priority disclosure; retained in the digest.",
            )


def change(current, previous):
    # A zero or negative comparison base makes percentage growth misleading.
    if current is None or previous is None or previous <= 0:
        return None
    return round((current / previous - 1) * 100, 2)


def price_signal(
    bars,
    current_time=None,
    market_tz=IST,
    close_time=(15, 30),
    *,
    allow_single_session=False,
):
    current_time = current_time or datetime.now(market_tz)
    local = current_time.astimezone(market_tz)
    complete = [
        b
        for b in bars
        if b.get("close") is not None
        and b.get("volume") is not None
        and (
            b["date"] < local.date().isoformat()
            or (
                b["date"] == local.date().isoformat()
                and (local.hour, local.minute) >= close_time
            )
        )
    ]
    complete.sort(key=lambda b: b["date"])
    if len(complete) < (1 if allow_single_session else 2):
        raise ValueError("Not enough completed trading sessions.")
    last = complete[-1]
    previous = complete[-2]["close"] if len(complete) > 1 else None
    baseline = complete[-21:-1]
    average = sum(b["volume"] for b in baseline) / len(baseline) if baseline else None
    return {
        **last,
        "previous_close": previous,
        "change_pct": change(last["close"], previous),
        "volume_ratio": round(last["volume"] / average, 2) if average else None,
        "baseline_sessions": len(baseline),
        "average_volume": round(average) if average is not None else None,
        "history": [b["close"] for b in complete[-30:]],
        "history_start": complete[-30:][0]["date"],
    }


def make_alerts(filings, prices, settings, mode):
    alerts = []
    for filing in filings:
        if filing["category"] in settings["categories"] and filing["priority"] >= 50:
            alerts.append(
                {
                    "id": f"{mode}:filing:{filing['id']}",
                    "symbol": filing["symbol"],
                    "title": filing["title"],
                    "detail": filing["reason"],
                    "kind": "filing",
                    "date": filing["published_at"],
                    "filing_id": filing["id"],
                }
            )
    for symbol, price in prices.items():
        for kind, field, threshold in [
            ("price", "change_pct", settings["price_threshold"]),
            ("volume", "volume_ratio", settings["volume_threshold"]),
        ]:
            value = price.get(field)
            if (
                value is not None
                and abs(value) >= threshold
                and (kind != "volume" or (price.get("baseline_sessions") or 0) >= 20)
            ):
                title = (
                    f"{symbol} {value:+.2f}% at close"
                    if kind == "price"
                    else f"{symbol} volume at {value:.1f}× its average"
                )
                alerts.append(
                    {
                        "id": f"{mode}:{kind}:{symbol}:{price['date']}",
                        "symbol": symbol,
                        "title": title,
                        "detail": f"Your rule: {'±' if kind == 'price' else ''}{threshold}{'%' if kind == 'price' else '× previous 20 sessions'}. End-of-day data.",
                        "kind": kind,
                        "date": price["date"],
                    }
                )

    def occurred_at(alert):
        stamp = datetime.fromisoformat(alert["date"])
        if alert["kind"] == "filing":
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=IST)
        return stamp.replace(hour=15, minute=30, tzinfo=IST)

    return sorted(alerts, key=occurred_at, reverse=True)
