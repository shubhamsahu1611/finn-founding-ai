"""Deterministic Network queries and contextual matches for the fictional demo."""

import re
import unicodedata
from datetime import date, datetime

from .domain import IST
from .network_data import COMPANY_LINKS, KNOWN_LINKS, ORGANISATIONS, PROFILES, THEMES

EVENT_THEMES = {
    "capex": {"manufacturing", "energy"},
    "management_change": {"treasury"},
}
EVENT_QUESTIONS = {
    "capex": "Which milestone would tell you the new capacity is ramping successfully?",
    "results": "What operating metric would you watch to tell whether this result is repeatable?",
    "M&A": "What would you look for to tell whether the integration is on track?",
    "litigation": "Which public milestone would help assess the operational impact?",
    "management_change": "What priorities should we watch as the new leadership takes over?",
}
STARTERS = (
    "Who knows Ananya Rao?",
    "Who can I call about Dixon?",
    "Who knows semiconductors?",
    "Who should I reconnect with?",
)
DILIGENCE_QUESTIONS = {
    "ananya": "At Cedar, how did you decide when to tighten liquidity buffers? What would you review first in the new role?",
}
RELATIONSHIP_LABELS = {
    "peer": "Peer company",
    "supplier": "Supplier",
    "customer": "Customer",
    "sector peer": "Sector peer",
}


def normalise(text):
    return " ".join(
        re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())
    )


def org_name(key):
    return ORGANISATIONS[key][0]


def local_date():
    return datetime.now(IST).date()


def years(start, end):
    return f"{start}–{end}" if end else f"{start}–present"


def find_matches(entities, query):
    padded = f" {normalise(query)} "
    return [
        key
        for key, aliases in entities.items()
        if any(f" {normalise(alias)} " in padded for alias in aliases)
    ]


def contact_history(store):
    return store.records("network:spoken:")


def contact_details(key, history, today):
    person = PROFILES[key]
    last_spoke = history.get(key, {}).get("date")
    if last_spoke is None and person.last_spoke:
        # Older versions stored a null override when undoing today's conversation.
        last_spoke = person.last_spoke.isoformat()
    return {
        "id": key,
        "name": person.name,
        "relationship": person.relationship,
        "last_spoke": last_spoke,
        "days_since": max(0, (today - date.fromisoformat(last_spoke)).days)
        if last_spoke
        else None,
    }


def company_matches(symbol, history, today, category=None):
    matches = []
    for key, person in PROFILES.items():
        if not person.relationship:
            continue
        paths = []
        for role in person.roles:
            name = org_name(role.company)
            evidence = f"{role.title} at {name} · {years(role.start, role.end)}"
            if role.company == symbol:
                current = role.end is None
                paths.append(
                    (
                        50 if current else 45,
                        "Current employee" if current else "Former employee",
                        evidence,
                    )
                )
            elif connection := COMPANY_LINKS.get(symbol, {}).get(role.company):
                paths.append((30, RELATIONSHIP_LABELS[connection], evidence))
        if not paths:
            continue
        paths.sort(key=lambda path: -path[0])
        score, label, evidence = paths[0]
        score += 10 * bool(
            EVENT_THEMES.get(category, set()).intersection(person.themes)
        )
        matches.append(
            (
                score,
                {
                    **contact_details(key, history, today),
                    "kind": label,
                    "evidence": evidence,
                    "perspective": person.bio,
                    "support": [f"{kind} · {reason}" for _, kind, reason in paths[1:]],
                },
            )
        )
    matches.sort(key=lambda match: (-match[0], match[1]["name"]))
    return [result for _, result in matches]


def overlap(first, second, year):
    start = max(first.start, second.start)
    end = min(first.end or year + 1, second.end or year + 1)
    if start >= end:
        return None
    return years(start, end if first.end or second.end else None)


def person_paths(target, history, today):
    person = PROFILES[target]
    matches = []
    for key, contact in PROFILES.items():
        if not contact.relationship or key == target:
            continue
        evidence = []
        if (key, target) in KNOWN_LINKS:
            evidence.append((30, "Reported collaboration", KNOWN_LINKS[key, target]))
        for first in contact.roles:
            for second in person.roles:
                if first.company == second.company and (
                    period := overlap(first, second, today.year)
                ):
                    evidence.append(
                        (
                            20,
                            "Employer overlap",
                            f"{org_name(first.company)} · {period} · {first.title} / {second.title}",
                        )
                    )
        for first in contact.education:
            for second in person.education:
                if first.school == second.school and (
                    period := overlap(first, second, today.year)
                ):
                    evidence.append(
                        (
                            10,
                            "Education overlap",
                            f"{first.school} · {first.programme} / {second.programme} · {period}",
                        )
                    )
        if evidence:
            evidence.sort(key=lambda item: -item[0])
            score, label, reason = evidence[0]
            matches.append(
                (
                    score,
                    {
                        **contact_details(key, history, today),
                        "kind": label,
                        "evidence": reason,
                        "support": [item[2] for item in evidence[1:]],
                        "target": person.name,
                    },
                )
            )
    matches.sort(key=lambda match: (-match[0], match[1]["name"]))
    return [result for _, result in matches]


def person_profile(key, history, today, holdings=()):
    person = PROFILES[key]
    related = []
    if person.relationship:
        for holding in holdings:
            symbol = holding["symbol"]
            match = next(
                (
                    item
                    for item in company_matches(symbol, history, today)
                    if item["id"] == key
                ),
                None,
            )
            if match:
                related.append(
                    {
                        "symbol": symbol,
                        "name": holding["name"],
                        "kind": match["kind"],
                        "evidence": match["evidence"],
                    }
                )
    return {
        **contact_details(key, history, today),
        "bio": person.bio,
        "roles": [
            {
                "title": role.title,
                "company": org_name(role.company),
                "years": years(role.start, role.end),
            }
            for role in sorted(person.roles, key=lambda role: -role.start)
        ],
        "education": [
            {
                "school": item.school,
                "programme": item.programme,
                "years": years(item.start, item.end),
            }
            for item in person.education
        ],
        "themes": [THEMES[theme][0] for theme in person.themes],
        "paths": person_paths(key, history, today),
        "watchlist_connections": related,
        "meeting_question": DILIGENCE_QUESTIONS.get(key),
    }


def filing_context(filing, history, today, limit=3):
    if filing["priority"] < 50:
        return None
    category, symbol = filing["category"], filing["symbol"]
    # Public filings supply company and category only. The graph contains fictional people.
    matches = company_matches(symbol, history, today, category)
    if not matches:
        return None
    reconnect = next(
        (
            match["id"]
            for match in matches[:limit]
            if match["kind"] == "Former employee" and (match["days_since"] or 0) >= 90
        ),
        None,
    )
    return {
        "matches": matches[:limit],
        "reconnect": reconnect,
        "question": EVENT_QUESTIONS.get(
            category, "What public indicators would help put this filing in context?"
        ),
    }


def research_context(symbol, history, today):
    matches = company_matches(symbol, history, today)
    return (
        {
            "matches": matches[:3],
            "question": "Which operating metric would you track to test the story in the disclosures?",
        }
        if matches
        else None
    )


def query_network(query, filings, history, today, holdings=()):
    result = {"source": "synthetic", "query": query, "groups": []}
    if not query:
        return {**result, "starters": STARTERS}
    if find_matches({"reconnect": ("reconnect", "catch up", "keep warm")}, query):
        opportunities = []
        seen = set()
        for filing in sorted(
            filings,
            key=lambda item: datetime.fromisoformat(item["published_at"]),
            reverse=True,
        ):
            context = filing_context(filing, history, today)
            if not context or not (key := context["reconnect"]) or key in seen:
                continue
            seen.add(key)
            opportunities.append(
                {
                    **next(match for match in context["matches"] if match["id"] == key),
                    "filing": {
                        "id": filing["id"],
                        "title": filing["title"],
                        "symbol": filing["symbol"],
                    },
                    "question": context["question"],
                }
            )
        return {
            **result,
            "groups": [{"title": "Reasons to reconnect", "matches": opportunities}],
            "kind": "reconnect",
        }

    people = find_matches(
        {key: (person.name,) for key, person in PROFILES.items()}, query
    )
    if not people:
        name = re.sub(r"^(?:who knows|do i know|find|show me)\s+", "", normalise(query))
        if len(name) >= 2:
            people = [
                key
                for key, person in PROFILES.items()
                if name in normalise(person.name).split()
            ]
    if people:
        return {
            **result,
            "profiles": [
                person_profile(key, history, today, holdings) for key in people
            ],
        }

    companies = find_matches(
        {key: (key, name, *aliases) for key, (name, aliases) in ORGANISATIONS.items()},
        query,
    )
    themes = find_matches(
        {key: (label, *aliases) for key, (label, aliases) in THEMES.items()}, query
    )
    for symbol in companies:
        result["groups"].append(
            {
                "title": org_name(symbol),
                "matches": company_matches(symbol, history, today),
            }
        )
    for theme in themes:
        matches = [
            {
                **contact_details(key, history, today),
                "kind": "Relevant experience",
                "evidence": person.bio,
            }
            for key, person in PROFILES.items()
            if person.relationship and theme in person.themes
        ]
        result["groups"].append({"title": THEMES[theme][0], "matches": matches})
    return result
