"""Synthetic documents for offline provider tests."""

import re

RESEARCH_COMPANIES = [
    ("TCS", "Tata Consultancy Services"),
    ("INFY", "Infosys"),
    ("HINDUNILVR", "Hindustan Unilever"),
    ("TRENT", "Trent"),
    ("POLYCAB", "Polycab India"),
]


def research_documents(symbol):
    names = dict(RESEARCH_COMPANIES)
    if symbol not in names:
        raise ValueError(
            "Demo research is available for TCS, INFY, HINDUNILVR, TRENT and POLYCAB. Choose Live to research any NSE symbol."
        )
    # Deliberately obvious simulated statements, with page-level evidence for every demo.
    scale = list(names).index(symbol) + 1
    name = names[symbol]
    annual = [
        f"SYNTHETIC DEMO — {name}, FY26. Business snapshot: this illustrative company operates a domestic business (70% of revenue) and an export business (30%). These are fictional figures, not facts about {symbol}.",
        f"Financial snapshot (INR crore): revenue {10000 * scale}; EBITDA {2400 * scale}; PBT {2000 * scale}; PAT {1500 * scale}. EBITDA margin 24%. ROE 18%. ROCE 21%. Trajectory: revenue FY24 {8000 * scale}, FY25 {9000 * scale}, FY26 {10000 * scale}; EBITDA margins 22%, 23%, 24% respectively.",
        f"Balance sheet: total debt {1200 * scale}, equity {8000 * scale}, debt-to-equity 0.15. Working-capital cycle increased from 45 to 52 days. Funding is primarily retained earnings. Contingent liabilities {100 * scale}; related-party transactions {50 * scale}. No auditor qualification in this fictional report.",
        f"Cash quality: operating cash flow FY24 {1000 * scale}, FY25 {1300 * scale}, FY26 {1200 * scale}. FY26 PAT {1500 * scale}; cash conversion 80%; capital expenditure {500 * scale}; free cash flow {700 * scale}. Receivables increased and cash conversion weakened.",
        "Bull case: expanding margins and low leverage could fund growth. Bear case: receivables and longer working-capital cycle could absorb cash. Both are interpretations of this simulated annual report, not recommendations.",
    ]
    docs = [
        {
            "id": f"demo-{symbol}-ar",
            "title": f"{name} · simulated annual report FY26",
            "kind": "annual_report",
            "url": None,
            "pages": annual,
        }
    ]
    targets = [10, 12, 12, 14]
    outcomes = [11, 10, 13, 12]
    for i, quarter in enumerate(["Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"]):
        docs.append(
            {
                "id": f"demo-{symbol}-call-{i}",
                "title": f"{quarter} · simulated transcript",
                "kind": "transcript",
                "url": None,
                "pages": [
                    f"SYNTHETIC DEMO — {name} {quarter}. Prior-quarter guidance for {quarter}: management expected revenue growth of {targets[i]}% YoY. Delivered in {quarter}: revenue growth of {outcomes[i]}% YoY, on the same consolidated basis. Narrative vs. numbers: compare the two percentages; no change of scope or currency basis.",
                    f"Guidance: management expects revenue growth of {targets[i] + 2}% YoY next quarter and an EBITDA margin of 24–25%. Capex budget is {500 * scale} INR crore. These forward-looking targets are not realised results.",
                ],
            }
        )
    # Like live discovery, present the newest transcripts first.
    return docs[:1] + list(reversed(docs[1:]))


def demo_comparisons(corpus):
    rows = []
    for source in corpus:
        match = re.search(
            r"Prior-quarter guidance for (Q\d FY\d+): management expected revenue growth of (\d+)% YoY. Delivered in \1: revenue growth of (\d+)% YoY",
            source["text"],
        )
        if match:
            period, expected, actual = match.groups()
            gap = int(actual) - int(expected)
            rows.append(
                {
                    "period": period,
                    "metric": "Revenue growth YoY",
                    "promised": f"{expected}%",
                    "delivered": f"{actual}%",
                    "assessment": f"{'Beat' if gap > 0 else 'Missed' if gap < 0 else 'Met'} by {abs(gap)} pp",
                    "promise_citation": source["id"],
                    "actual_citation": source["id"],
                    "promise_quote": match.group(0),
                    "actual_quote": match.group(0),
                }
            )
    return sorted(
        rows, key=lambda row: (int(row["period"].split("FY")[1]), int(row["period"][1]))
    )
