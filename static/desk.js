"use strict";

// Small workflow additions. No model calls are made by filters or research lenses.
const researchLenses = {
  all: { label: "Full picture", sections: null },
  business: {
    label: "Business & growth",
    sections: [
      "Business snapshot",
      "Financial snapshot",
      "Trajectory",
      "Bull vs. bear",
    ],
  },
  cash: {
    label: "Follow the cash",
    sections: ["Balance sheet", "Cash quality", "Financial snapshot"],
  },
  promises: {
    label: "Test the story",
    sections: ["Narrative vs. numbers", "Guidance", "Bull vs. bear"],
  },
};
const researchQuestions = [
  {
    label: "Cash vs. profit",
    question:
      "Are profits turning into operating cash? Show cash conversion, receivables and capital expenditure from the sources.",
  },
  {
    label: "Test management",
    question:
      "Where do management's growth and margin promises agree with or diverge from delivered results? Cite the periods and evidence.",
  },
  {
    label: "Find the blind spot",
    question:
      "What risks in debt, working capital, contingent liabilities or auditor comments deserve a closer look? Separate evidence from inference.",
  },
];
const followUpQuestions = {
  results:
    "Are profits turning into operating cash, and are margins improving on a comparable basis?",
  management_change:
    "What governance and key-person risks are disclosed in the annual report?",
  "M&A":
    "How do acquisitions affect debt, cash generation and management's capital-allocation plans?",
  capex:
    "Can operating cash flow fund the capital expenditure management has guided?",
  credit_rating:
    "What do the primary documents say about debt, liquidity and funding needs?",
  pledging:
    "What promoter pledging or contingent liabilities are disclosed in primary documents?",
};

function filingReview(id) {
  return typeof state !== "undefined" && state.data?.reviews?.[id]
    ? state.data.reviews[id]
    : {};
}

function briefSelection(items, options, reviews) {
  let matches = items.filter(
    (f) =>
      (options.category === "all" || f.category === options.category) &&
      (!options.symbol || f.symbol === options.symbol) &&
      `${f.symbol} ${f.title}`
        .toLowerCase()
        .includes(options.query.toLowerCase()) &&
      (options.queue !== "saved" || reviews[f.id]?.saved) &&
      (options.queue !== "unreviewed" || !reviews[f.id]?.reviewed),
  );
  if (options.queue === "focus")
    matches = matches
      .filter((f) => f.priority >= 50 && !reviews[f.id]?.reviewed)
      .slice(0, 3);
  return matches;
}

let preparedBrief;
let activeUtterance;

function parseDeskQuestion(question, portfolio) {
  const text = String(question || "").trim().toLowerCase();
  const tokens = text.toUpperCase().split(/[^A-Z0-9&]+/);
  const company = portfolio.find(
    (item) =>
      tokens.includes(item.symbol) || text.includes(item.name.toLowerCase()),
  );
  if (/(biggest|largest|most unusual).*(price|move|change)|(price|move).*(biggest|largest)/.test(text))
    return { type: "move" };
  if (/(unread|new).*(alert|signal)|(alert|signal).*(unread|new)/.test(text))
    return { type: "alerts" };
  if (/(filing|announcement|disclosure|results?)/.test(text)) {
    const hours = /(?:this week|past week|last (?:7|seven) days)/.test(text)
      ? "168"
      : /(?:last (?:3|three) days)/.test(text)
        ? "72"
        : /(?:last (?:30|thirty) days|this month)/.test(text)
          ? "720"
          : "24";
    return {
      type: "filings",
      symbol: company?.symbol || "",
      hours,
      category: /\bresults?\b/.test(text) ? "results" : "all",
    };
  }
  return { type: "unsupported" };
}

function deskAskBar() {
  return `<section class="desk-ask" aria-label="Ask your investment desk"><div class="desk-ask-heading"><div><span class="eyebrow">A FASTER WAY THROUGH THE BRIEF</span><h2>Ask the desk.</h2></div><p>Uses your loaded filings, alerts and completed prices. No model call.</p></div><form id="desk-ask-form"><label class="sr-only" for="desk-question">Ask about filings, alerts or price moves</label><input id="desk-question" maxlength="120" placeholder="Show me filings for TCS this week" value="${e(state.deskQuestion || "")}" required><button class="button primary" type="submit">Show me ↗</button></form><div class="desk-ask-examples"><button type="button" data-ask-example="Show me filings for TCS this week">TCS filings this week</button><button type="button" data-ask-example="Which company had the biggest price move?">Biggest price move</button><button type="button" data-ask-example="Show unread alerts">Unread alerts</button></div><p id="desk-ask-answer" role="status" aria-live="polite">${e(state.deskAnswer || "")}</p></section>`;
}

async function answerDeskQuestion(question) {
  state.deskQuestion = question.trim();
  const intent = parseDeskQuestion(question, state.data.portfolio);
  if (intent.type === "filings") {
    state.hours = intent.hours;
    state.symbol = intent.symbol;
    state.category = intent.category;
    state.queue = "all";
    await loadDigest();
    const count = briefSelection(state.digest.items, state, state.data.reviews || {}).length;
    const period = { "24": "24 hours", "72": "3 days", "168": "7 days", "720": "30 days" }[intent.hours];
    state.deskAnswer = `Showing ${count} ${intent.symbol || "portfolio"} filing${count === 1 ? "" : "s"} from the last ${period}${intent.category === "results" ? " in Results" : ""}.`;
    renderBrief();
    $("#filing-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (intent.type === "move") {
    const known = state.data.portfolio
      .map((company) => ({ company, price: state.data.prices[company.symbol] }))
      .filter((item) => item.price?.change_pct != null);
    known.sort((a, b) => Math.abs(b.price.change_pct) - Math.abs(a.price.change_pct));
    state.deskAnswer = known.length
      ? `${known[0].company.symbol} had the largest absolute move in the loaded completed session: ${signed(known[0].price.change_pct)} on ${known[0].price.date}${known[0].price.stale ? " (cached quote)" : ""}.`
      : "No completed price moves are loaded. Refresh public sources to load quotes.";
    $("#desk-ask-answer").textContent = state.deskAnswer;
  } else if (intent.type === "alerts") {
    state.alertFilter = "unread";
    setView("alerts");
    toast("Showing unread alerts.");
  } else {
    state.deskAnswer = "Try ‘TCS filings this week’, ‘biggest price move’, or ‘unread alerts’. Use Research for company analysis.";
    $("#desk-ask-answer").textContent = state.deskAnswer;
  }
}

function focusHero() {
  const material = state.digest.items.filter((f) => f.priority >= 50);
  const reviewed = material.filter((f) => filingReview(f.id).reviewed).length;
  const remaining = material.length - reviewed;
  const percent = material.length
    ? Math.round((reviewed / material.length) * 100)
    : 0;
  const audio = briefAudioButton();
  return `<section class="focus-hero" aria-label="Review progress">
    <div class="hero-copy"><div class="hero-kicker"><span class="hero-dot"></span> REVIEW QUEUE</div>
      <h2>${remaining ? `${remaining} filing${remaining === 1 ? "" : "s"} to review` : material.length ? "You’re caught up" : "No material filings"}</h2>
      <p>${remaining ? "Start with the three highest-priority disclosures." : material.length ? "All material filings in this window have been reviewed." : "Choose a wider window to see earlier disclosures."}</p>
      <div class="hero-actions">
        ${remaining ? `<button class="button" data-queue="focus">${reviewed ? "Continue review" : "Start review"} <span aria-hidden="true">→</span></button>` : state.hours === "24" ? '<button class="button" data-digest-window="168">View last 7 days <span aria-hidden="true">→</span></button>' : ""}
        <button data-queue="saved" class="hero-secondary">Saved filings ↗</button>
        <button class="hero-audio-btn ${activeUtterance ? "playing" : ""}" id="play-audio-brief" type="button" aria-label="${audio.label}" title="${audio.label}" aria-busy="${audio.busy}">
          <span class="audio-wave" aria-hidden="true"><span></span><span></span><span></span></span>
          <span class="audio-label" aria-live="polite">${audio.text}</span>
        </button>
      </div>
      <div class="mobile-progress"><span>${reviewed} of ${material.length} material filings reviewed</span><progress value="${reviewed}" max="${material.length || 1}" aria-label="Material filings reviewed"></progress></div>
    </div>
    <div class="hero-progress"><svg viewBox="0 0 140 140" role="img" aria-label="${reviewed} of ${material.length} material filings reviewed"><circle class="progress-track" cx="70" cy="70" r="59"/><circle class="progress-value" cx="70" cy="70" r="59" pathLength="100" stroke-dasharray="${percent} 100"/><text x="70" y="72" text-anchor="middle">${reviewed}<tspan> / ${material.length}</tspan></text><text class="progress-caption" x="70" y="94" text-anchor="middle">REVIEWED</text></svg><span>One source at a time.</span></div>
  </section>`;
}

function reviewControls(filing) {
  const review = filingReview(filing.id);
  return `<div class="review-actions"><button class="review-button ${review.saved ? "is-saved" : ""}" data-save-filing="${e(filing.id)}" aria-pressed="${!!review.saved}" aria-label="${review.saved ? "Unsave" : "Save"} ${e(filing.symbol)} filing"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><path d="M5 3h10v14l-5-3-5 3z"/></svg>${review.saved ? "Saved" : "Save"} <span class="key-hint" aria-hidden="true">[S]</span></button><button class="review-button ${review.reviewed ? "is-reviewed" : ""}" data-review-filing="${e(filing.id)}" aria-pressed="${!!review.reviewed}" aria-label="${review.reviewed ? "Mark unreviewed" : "Mark reviewed"} ${e(filing.symbol)} filing"><span aria-hidden="true">${review.reviewed ? "✓" : "○"}</span>${review.reviewed ? "Reviewed" : "Mark reviewed"} <span class="key-hint" aria-hidden="true">[R]</span></button>${review.note ? `<button class="review-button note-indicator" data-filing="${e(filing.id)}">Note attached ↗</button>` : ""}</div>`;
}

function queueTabs() {
  const reviews = state.data.reviews || {};
  const saved = state.digest.items.filter((f) => reviews[f.id]?.saved).length;
  return `<div class="queue-tabs" role="group" aria-label="Brief view">${[
    ["all", "All filings"],
    ["unreviewed", "To review"],
    ["focus", "Focus · next 3"],
    ["saved", `Saved · ${saved}`],
  ]
    .map(
      ([key, label]) =>
        `<button data-queue="${key}" aria-pressed="${state.queue === key}" class="${state.queue === key ? "active" : ""}">${label}</button>`,
    )
    .join(
      "",
    )}</div>${state.queue === "focus" ? '<p class="queue-explainer">Your next three unreviewed material filings, ordered by priority. Mark one reviewed to bring the next into view. Press <kbd>J</kbd>/<kbd>K</kbd> to step through.</p>' : state.queue === "saved" ? '<p class="queue-explainer">Saved filings in the selected time window. Widen the window to revisit older ideas.</p>' : ""}${state.symbol ? `<button class="filter-token" id="clear-symbol">${e(state.symbol)} filings <span aria-hidden="true">×</span><span class="sr-only">Clear company filter</span></button>` : ""}`;
}

function portfolioPulse() {
  const prices = state.data.prices;
  const known = state.data.portfolio.filter(
    (c) => prices[c.symbol]?.change_pct != null,
  );
  if (!known.length) return "";
  const gainers = known.filter((c) => prices[c.symbol].change_pct > 0).length;
  const losers = known.filter((c) => prices[c.symbol].change_pct < 0).length;
  const unchanged = known.length - gainers - losers;
  const sorted = [...known].sort(
    (a, b) =>
      Math.abs(prices[b.symbol].change_pct) -
      Math.abs(prices[a.symbol].change_pct),
  );
  return `<section class="pulse-section" aria-label="Portfolio pulse"><div class="pulse-heading"><h2>Portfolio pulse <span>COMPLETED SESSIONS</span></h2><div class="breadth"><span class="positive">↑ ${gainers}</span><span class="negative">↓ ${losers}</span><span>— ${unchanged}</span></div></div><div class="pulse-grid">${sorted
    .slice(0, 4)
    .map((c) => {
      const p = prices[c.symbol];
      const volume =
        p.baseline_sessions >= 20 &&
        p.volume_ratio >= state.data.settings.volume_threshold;
      return `<button class="pulse-tile ${p.change_pct >= 0 ? "up" : "down"} ${state.symbol === c.symbol ? "selected" : ""}" data-pulse="${e(c.symbol)}" aria-pressed="${state.symbol === c.symbol}" aria-label="Filter brief to ${e(c.symbol)}, ${signed(p.change_pct)}"><span class="pulse-symbol">${e(c.symbol)} <span aria-hidden="true">↗</span></span><strong>${signed(p.change_pct)}</strong><span class="pulse-detail">${volume ? `${number(p.volume_ratio, 1)}× volume · unusual` : e(c.sector)}</span><span class="pulse-date">${e(p.date)}${p.stale ? " · cached" : ""}</span></button>`;
    })
    .join(
      "",
    )}</div><p class="pulse-caption">Largest absolute moves · click a company to filter its filings. Counts cover ${known.length}/${state.data.portfolio.length} available quotes; not weighted portfolio returns.</p></section>`;
}

function updateBriefTools() {
  if (typeof $ === "undefined" || !$("#focus-hero-slot")) return;
  $("#focus-hero-slot").innerHTML = focusHero();
  $("#queue-tools").innerHTML = queueTabs();
  document.querySelectorAll("[data-pulse]").forEach((button) => {
    const selected = button.dataset.pulse === state.symbol;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function reviewForm(filing) {
  const note = filingReview(filing.id).note || "";
  return `<section class="filing-workspace"><div class="section-heading"><h3>Your reading desk</h3><span class="tag">PERSONAL NOTE</span></div><div id="dialog-review-controls">${reviewControls(filing)}</div><form id="filing-note-form" data-identity="${e(filing.id)}"><label for="filing-note">What would change your view?</label><textarea id="filing-note" maxlength="1200" rows="3" placeholder="A question to revisit, a risk to watch, or a number to check…">${e(note)}</textarea><div class="note-footer"><small>Saved in this workspace · never sent to a model</small><button class="button primary" type="submit">Save note</button></div></form><div class="next-question"><span>ONE QUESTION WORTH ASKING</span><p>${e(followUpQuestions[filing.category] || "What do the annual report and transcripts reveal about this company's cash generation and risks?")}</p><button class="text-button" data-follow-up="${e(filing.id)}">Take this to research →</button></div></section>`;
}

async function saveReview(identity, fields) {
  const result = await post(
    `/api/filings/${encodeURIComponent(identity)}/review?mode=live`,
    fields,
    "PATCH",
  );
  state.data.reviews ||= {};
  state.data.reviews[identity] = result;
  if (state.view === "brief") {
    const routineOpen = $(".routine")?.open;
    updateBriefTools();
    renderFilings();
    if (routineOpen && $(".routine")) $(".routine").open = true;
  }
  const filing = state.data.filings.find((f) => f.id === identity);
  if (filing && $("#filing-note-form")?.dataset.identity === identity)
    $("#dialog-review-controls").innerHTML = reviewControls(filing);
}

function researchPrompts() {
  return `<div class="question-starters"><span>ASK A SHARPER QUESTION</span>${researchQuestions.map((q, i) => `<button type="button" data-question="${i}">${e(q.label)} <span aria-hidden="true">↗</span></button>`).join("")}</div>`;
}

function researchLensBar() {
  return `<div class="lens-bar" role="group" aria-label="Research lens">${Object.entries(
    researchLenses,
  )
    .map(
      ([id, lens]) =>
        `<button data-lens="${id}" class="${state.lens === id ? "active" : ""}" aria-pressed="${state.lens === id}">${lens.label}</button>`,
    )
    .join("")}</div>`;
}

function applyResearchLens() {
  const lens = researchLenses[state.lens] || researchLenses.all;
  document.querySelectorAll(".research-section").forEach((section) => {
    const title = section.dataset.researchSection || section.querySelector("h3").textContent;
    section.hidden =
      !!lens.sections &&
      !lens.sections.includes(title) &&
      title !== "Your question";
  });
  document.querySelectorAll("[data-lens]").forEach((button) => {
    button.classList.toggle("active", button.dataset.lens === state.lens);
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.lens === state.lens),
    );
  });
  const comparison = $(".comparison");
  if (comparison) {
    comparison.hidden = state.lens !== "promises" &&
      (state.lens !== "all" || !state.report?.comparisons.length);
  }
  const more = $(".research-more");
  if (more) {
    more.hidden = !more.querySelector(".research-section:not([hidden])");
    more.open = state.lens !== "all";
  }
  const highlights = $(".research-highlights");
  if (highlights) highlights.hidden = !highlights.querySelector(".research-section:not([hidden])");
}

// -------------------------------------------------------------
// Institutional Visual Enhancements: Scorecard, Margin & Tape
// -------------------------------------------------------------

function renderMarketTape() {
  const container = document.getElementById("market-tape");
  if (!container || typeof state === "undefined" || !state.data?.portfolio)
    return;

  const prices = Object.fromEntries(
    Object.entries(state.data.prices || {}).filter(([, price]) => price?.source === "Yahoo Finance · NSE"),
  );
  const currency = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
  });
  const quoteDates = Object.values(prices)
    .map((price) => price.date)
    .filter(Boolean);
  const latestQuote = quoteDates.length ? quoteDates.sort().at(-1) : null;
  const items = state.data.portfolio
    .slice(0, 12)
    .map((c) => {
      const p = prices[c.symbol];
      const chg = p?.change_pct;
      const sign = chg != null ? (chg >= 0 ? "+" : "") : "";
      const cls =
        chg != null ? (chg >= 0 ? "positive" : "negative") : "neutral";
      const quotePage = `https://finance.yahoo.com/quote/${encodeURIComponent(c.symbol)}.NS/`;
      const href = p?.source_url ? safeURL(p.source_url) : "#";
      const description = p?.date
        ? `Closing price · ${p.date}${p.stale ? " (cached)" : ""}`
        : "Closing price unavailable";
      return `<a class="tape-chip" href="${href === "#" ? quotePage : href}" target="_blank" rel="noopener noreferrer" title="${e(description)} · Open ${e(c.symbol)} on Yahoo Finance (new tab)">
      <span class="ticker">${e(c.symbol)}</span>
      <span class="price">${p?.close != null ? `${currency.format(p.close)}` : "—"}</span>
      <span class="delta ${cls}">${chg != null ? `${sign}${Number(chg).toFixed(2)}%` : "—"}</span>
      <span class="tape-link-icon" aria-hidden="true">↗</span>
      <span class="sr-only">Open public quote on Yahoo Finance (new tab)</span>
    </a>`;
    })
    .join("");

  container.innerHTML = `
    <div class="tape-status closed">
      <span class="status-dot">●</span>
      <span class="status-text">PUBLIC END-OF-DAY DATA</span>
      <span class="status-hours">${latestQuote ? `Latest session ${e(latestQuote)}` : "No closing prices loaded"}</span>
    </div>
    <div class="tape-track">${items}</div>
  `;
}

function renderCredibilityScorecard(comparisons) {
  if (!comparisons || !comparisons.length) return "";
  let beatCount = 0;
  let metCount = 0;
  let missCount = 0;

  for (const c of comparisons) {
    const text = (c.assessment || "").toLowerCase();
    if (text.includes("beat")) beatCount++;
    else if (text.includes("miss")) missCount++;
    else if (text.includes("met")) metCount++;
  }

  const delivered = beatCount + metCount;
  const total = beatCount + metCount + missCount;
  if (!total) return "";
  const rate = Math.round((delivered / total) * 100);

  return `
    <div class="credibility-scorecard">
      <div class="scorecard-header">
        <div>
          <span class="scorecard-tag">MATCHED GUIDANCE PAIRS</span>
          <h3>Promises vs. delivery</h3>
        </div>
        <div class="scorecard-metric">
          <div class="scorecard-rate ${rate >= 70 ? "good" : rate >= 50 ? "mixed" : "poor"}">${rate}%</div>
          <div class="scorecard-caption">${delivered} of ${total} delivered</div>
        </div>
      </div>
      <div class="scorecard-summary-bars">
        <div class="score-pill beat">${beatCount} Beat</div>
        <div class="score-pill met">${metCount} Met In-Line</div>
        <div class="score-pill miss">${missCount} Missed / Lowered</div>
      </div>
      <p class="scorecard-explainer">Describes ${total} comparable guidance/result pair${total === 1 ? "" : "s"} in this brief. Check each cited source and period; this is not a rating of management.</p>
    </div>
  `;
}

function resultBars(results) {
  const periods = [results.periods?.[2], results.periods?.[1], results.periods?.[0]];
  if (periods.some((period) => !period)) return "";
  const rows = results.rows.filter((row) =>
    [row.year_ago, row.previous, row.current].every(
      (value) => typeof value === "number" && Number.isFinite(value),
    ),
  );
  if (!rows.length) return "";
  return `<figure class="results-chart"><figcaption><strong>Headline numbers across three reported periods</strong><small>${e(results.unit)} · Bars are scaled within each metric; read the table for exact values.</small></figcaption>${rows.map((row) => {
    const values = [row.year_ago, row.previous, row.current];
    const low = Math.min(0, ...values);
    const high = Math.max(0, ...values);
    const range = high - low || 1;
    const zero = (-low / range) * 100;
    const bars = values.map((value, index) => {
      const width = Math.abs(value) / range * 100;
      const x = value < 0 ? zero - width : zero;
      const color = value < 0 ? "loss" : index === 2 ? "current" : "";
      return `<div class="result-bar"><span>${e(periods[index])}</span><svg class="result-bar-track" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true"><rect class="result-bar-fill ${color}" x="${x}" width="${width}" height="8"/>${low < 0 ? `<line class="result-bar-zero" x1="${zero}" x2="${zero}" y2="8"/>` : ""}</svg><b>${number(value, 2)}</b></div>`;
    });
    return `<div class="result-bars-row"><strong>${e(row.metric)}</strong><div>${bars.join("")}</div></div>`;
  }).join("")}</figure>`;
}

function renderResultsAnalysis(results) {
  if (!results || !results.rows || !results.rows.length) return "";

  // Find revenue and profits
  const revRow = results.rows.find((r) =>
    /revenue|income|sales/i.test(r.metric),
  );
  const ebitdaRow = results.rows.find((r) => /ebitda/i.test(r.metric));
  const patRow = results.rows.find((r) => /pat|net profit/i.test(r.metric));

  let marginHtml = "";
  if (revRow && (ebitdaRow || patRow)) {
    const calcMargin = (num, den) =>
      den > 0 && num != null ? ((num / den) * 100).toFixed(1) : null;
    const calcBps = (curr, prev) =>
      curr != null && prev != null ? Math.round((curr - prev) * 100) : null;

    const curRev = revRow.current;
    const prevRev = revRow.previous;
    const yoyRev = revRow.year_ago;

    const cards = [];
    if (ebitdaRow) {
      const curMargin = calcMargin(ebitdaRow.current, curRev);
      const prevMargin = calcMargin(ebitdaRow.previous, prevRev);
      const yoyMargin = calcMargin(ebitdaRow.year_ago, yoyRev);
      const yoyBps = calcBps(curMargin, yoyMargin);
      const qoqBps = calcBps(curMargin, prevMargin);
      cards.push(`
        <div class="margin-card">
          <span class="margin-label">EBITDA MARGIN</span>
          <strong class="margin-value">${curMargin != null ? `${curMargin}%` : "—"}</strong>
          <span class="margin-delta ${yoyBps != null ? (yoyBps >= 0 ? "positive" : "negative") : ""}">
            ${yoyBps != null ? `${yoyBps >= 0 ? "+" : ""}${yoyBps} bps YoY` : "YoY N/A"}
          </span>
          <small class="margin-sub">${qoqBps != null ? `${qoqBps >= 0 ? "+" : ""}${qoqBps} bps QoQ` : ""}</small>
        </div>
      `);
    }
    if (patRow) {
      const curMargin = calcMargin(patRow.current, curRev);
      const prevMargin = calcMargin(patRow.previous, prevRev);
      const yoyMargin = calcMargin(patRow.year_ago, yoyRev);
      const yoyBps = calcBps(curMargin, yoyMargin);
      const qoqBps = calcBps(curMargin, prevMargin);
      cards.push(`
        <div class="margin-card">
          <span class="margin-label">PAT MARGIN</span>
          <strong class="margin-value">${curMargin != null ? `${curMargin}%` : "—"}</strong>
          <span class="margin-delta ${yoyBps != null ? (yoyBps >= 0 ? "positive" : "negative") : ""}">
            ${yoyBps != null ? `${yoyBps >= 0 ? "+" : ""}${yoyBps} bps YoY` : "YoY N/A"}
          </span>
          <small class="margin-sub">${qoqBps != null ? `${qoqBps >= 0 ? "+" : ""}${qoqBps} bps QoQ` : ""}</small>
        </div>
      `);
    }
    if (cards.length) {
      marginHtml = `<div class="margin-trajectory-row">${cards.join("")}</div>`;
    }
  }

  const pctCell = (a, b) => {
    if (b > 0 && a != null) {
      const pct = (a / b - 1) * 100;
      const cls = pct >= 0 ? "positive" : "negative";
      const sign = pct >= 0 ? "+" : "";
      return `<span class="delta-chip ${cls}">${sign}${pct.toFixed(2)}%</span>`;
    }
    return `<span class="delta-chip neutral">N/M</span>`;
  };

  return `
    <div class="results-analysis-block">
      ${marginHtml}
      ${resultBars(results)}
      <div class="table-scroll">
        <table class="financial-table">
          <thead>
            <tr>
              <th>Metric</th>
              ${results.periods.map((p) => `<th>${e(p)}</th>`).join("")}
              <th>QoQ Growth</th>
              <th>YoY Growth</th>
            </tr>
          </thead>
          <tbody>
            ${results.rows
              .map(
                (r) => `
              <tr>
                <td><strong>${e(r.metric)}</strong></td>
                <td class="num">${number(r.current)}</td>
                <td class="num">${number(r.previous)}</td>
                <td class="num">${number(r.year_ago)}</td>
                <td class="delta-cell">${pctCell(r.current, r.previous)}</td>
                <td class="delta-cell">${pctCell(r.current, r.year_ago)}</td>
              </tr>
            `,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// -------------------------------------------------------------
// Spoken Audio Briefing (Web Speech API)
// -------------------------------------------------------------

function currentPreparedBrief() {
  return preparedBrief?.digest === state.digest && preparedBrief?.data === state.data
    ? preparedBrief
    : null;
}

function briefAudioButton() {
  if (activeUtterance) return { text: "Stop audio", label: "Stop audio brief", busy: false };
  const current = currentPreparedBrief();
  if (current && !current.script)
    return { text: "Preparing…", label: "Cancel spoken brief preparation", busy: true };
  if (current?.needsTap)
    return { text: "Play brief", label: "Play the prepared brief", busy: false };
  return { text: "Listen", label: "Listen to spoken brief", busy: false };
}

function updateBriefAudioButton() {
  const button = $("#play-audio-brief");
  if (!button) return;
  const info = briefAudioButton();
  button.classList.toggle("playing", Boolean(activeUtterance));
  button.setAttribute("aria-label", info.label);
  button.setAttribute("aria-busy", String(info.busy));
  button.title = info.label;
  button.querySelector(".audio-label").textContent = info.text;
}

async function toggleAudioBrief() {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    if (typeof toast === "function")
      toast("Audio speech synthesis is not supported on this browser.");
    return;
  }

  if (activeUtterance) {
    activeUtterance = null;
    window.speechSynthesis.cancel();
    updateBriefAudioButton();
    return;
  }
  if (!state.digest) return;
  const current = currentPreparedBrief();
  if (current?.script) {
    speakBrief(current);
    return;
  }
  if (current) {
    preparedBrief = null;
    updateBriefAudioButton();
    return;
  }
  const request = { digest: state.digest, data: state.data };
  preparedBrief = request;
  updateBriefAudioButton();
  const range = new URLSearchParams({ start: request.digest.start, end: request.digest.end });
  try {
    const brief = await api("/api/digest/audio?" + range, {
      method: "POST",
      signal: AbortSignal.timeout(17000),
    });
    if (currentPreparedBrief() !== request) return;
    if (typeof brief.script !== "string" || !brief.script.trim())
      throw new Error("FINN returned an empty spoken brief.");
    request.script = brief.script;
    if (navigator.userActivation?.isActive) {
      speakBrief(request);
    } else {
      request.needsTap = true;
      updateBriefAudioButton();
      toast("Brief ready. Tap Play brief to listen.");
    }
  } catch (error) {
    if (currentPreparedBrief() !== request) return;
    preparedBrief = null;
    updateBriefAudioButton();
    toast(error.message);
  }
}

function speakBrief(brief) {
  window.speechSynthesis.cancel();
  brief.needsTap = false;
  const utterance = new SpeechSynthesisUtterance(brief.script);
  activeUtterance = utterance;
  utterance.rate = 1.05;
  utterance.onend = () => {
    if (activeUtterance !== utterance) return;
    activeUtterance = null;
    updateBriefAudioButton();
  };
  utterance.onerror = (event) => {
    if (activeUtterance !== utterance) return;
    activeUtterance = null;
    brief.needsTap = event.error === "not-allowed";
    updateBriefAudioButton();
    toast(brief.needsTap ? "Tap Play brief to start playback." : "The browser could not play the brief.");
  };
  updateBriefAudioButton();
  window.speechSynthesis.speak(utterance);
}

// -------------------------------------------------------------
// Command Palette (Cmd+K / Ctrl+K)
// -------------------------------------------------------------

let commandSelectedIndex = 0;
let currentCommandMatches = [];
let companySearchTimer;
let companySearchRequest;
let companySearchResult;
let companySearchStatus = "";
let pendingCompanySearch;

function getCommandItems() {
  if (typeof state === "undefined" || !state.data) return [];
  const items = [];

  // Actions
  items.push({
    type: "action",
    category: "Workflow Action",
    label: "Start two-minute priority brief",
    shortcut: "B",
    action: () => {
      setView("brief");
      state.queue = "focus";
      state.category = "all";
      state.query = "";
      state.symbol = "";
      updateBriefTools();
      renderFilings();
    },
  });

  items.push({
    type: "action",
    category: "Workflow Action",
    label: "Toggle Dark / Light Theme",
    shortcut: "T",
    action: toggleTheme,
  });

  items.push({
    type: "action",
    category: "Workflow Action",
    label: "Play spoken brief",
    shortcut: "Audio",
    action: () => {
      if (state.view !== "brief") setView("brief");
      return toggleAudioBrief();
    },
  });

  items.push({
    type: "action",
    category: "Workflow Action",
    label: "Open financial glossary",
    shortcut: "G",
    action: () => showGlossary(),
  });

  items.push({
    type: "action",
    category: "Workflow Action",
    label: "Refresh all data sources",
    shortcut: "R",
    action: () => refresh(),
  });

  // Views
  Object.entries(navigation).forEach(([key, title]) => {
    items.push({
      type: "view",
      category: "Navigate View",
      label: `Go to ${title}`,
      shortcut: "Tab",
      action: () => setView(key),
    });
  });

  // Watchlist Tickers
  if (state.data.portfolio) {
    state.data.portfolio.forEach((c) => {
      items.push({
        type: "symbol",
        category: "Company Research",
        label: `${c.symbol} · ${c.name} (${c.sector})`,
        shortcut: "Research",
        action: () => runResearch(c.symbol),
      });
      items.push({
        type: "symbol_filter",
        category: "Filter Brief",
        label: `Filter filings by ${c.symbol}`,
        shortcut: "Filter",
        action: () => {
          setView("brief");
          state.symbol = c.symbol;
          state.queue = "all";
          updateBriefTools();
          renderFilings();
        },
      });
    });
  }

  for (const filing of state.digest?.items || []) {
    items.push({
      category: "Filing",
      label: `${filing.symbol} · ${filing.title}`,
      shortcut: "Open",
      action: () => filingDetails(filing.id),
    });
  }
  for (const [group, category] of [["people", "Network person"], ["themes", "Network theme"]]) {
    for (const label of state.data.network_search?.[group] || []) {
      items.push({ category, label, shortcut: "Network", action: () => runNetwork(label) });
    }
  }

  // Categories
  if (state.data.categories) {
    state.data.categories.forEach((cat) => {
      items.push({
        type: "category",
        category: "Announcement Category",
        label: `Filter by ${cat.label}`,
        shortcut: "Category",
        action: () => {
          setView("brief");
          state.category = cat.id;
          state.queue = "all";
          const catFilter = document.getElementById("category-filter");
          if (catFilter) catFilter.value = cat.id;
          renderFilings();
        },
      });
    });
  }

  return items;
}

function openCommandPalette(query = "") {
  const dialog = document.getElementById("command-palette-dialog");
  const input = document.getElementById("command-input");
  if (!dialog || !input) return;
  commandSelectedIndex = 0;
  input.value = query;
  updateCommandSearch(query);
  if (!dialog.open) dialog.showModal();
  input.focus();
}

function closeCommandPalette() {
  const dialog = document.getElementById("command-palette-dialog");
  if (dialog?.open) dialog.close();
}

function updateCommandSearch(query) {
  clearTimeout(companySearchTimer);
  companySearchRequest?.abort();
  pendingCompanySearch = null;
  commandSelectedIndex = 0;
  companySearchResult = null;
  const term = query.trim();
  const canSearch = term.length >= 2;
  companySearchStatus = canSearch ? "Searching NSE and BSE listings…" : "";
  renderCommandList(query);
  if (!canSearch) return;

  const request = new AbortController();
  companySearchRequest = request;
  async function search() {
    try {
      const result = await api(`/api/companies/search?q=${encodeURIComponent(term)}`, {
        signal: request.signal,
      });
      if (request.signal.aborted) return;
      companySearchResult = result;
      companySearchStatus = result.warnings.join(" ");
    } catch (error) {
      if (request.signal.aborted) return;
      companySearchStatus = error.message;
    }
    const selected = currentCommandMatches[commandSelectedIndex];
    renderCommandList(query);
    const index = currentCommandMatches.findIndex((item) => item.label === selected?.label && item.category === selected?.category);
    if (index >= 0) selectCommand(index);
  }
  let result;
  pendingCompanySearch = () => {
    clearTimeout(companySearchTimer);
    return result ??= search();
  };
  companySearchTimer = setTimeout(pendingCompanySearch, 250);
}

function renderCommandList(query) {
  const list = document.getElementById("command-list");
  if (!list) return;
  const q = (query || "").trim().toLowerCase();
  const all = getCommandItems();

  const localMatches = q
    ? all.filter(
        (item) =>
          item.label.toLowerCase().includes(q) ||
          item.category.toLowerCase().includes(q),
      )
    : all.slice(0, 20);

  const companyMatches = (companySearchResult?.items || []).map((company) => ({
    category: `${company.exchange} equity${company.code ? ` · ${company.code}` : ""}`,
    label: `${company.name} · ${company.symbol}`,
    shortcut: "Quote",
    action: () => openIndianCompany(company),
  }));
  currentCommandMatches = [...companyMatches, ...localMatches];

  if (commandSelectedIndex >= currentCommandMatches.length) {
    commandSelectedIndex = 0;
  }

  list.innerHTML = currentCommandMatches
    .map(
      (item, idx) => `
    <div class="command-item" id="command-option-${idx}" data-cmd-idx="${idx}" role="option" aria-selected="false">
      <div class="cmd-item-left">
        <span class="cmd-item-cat">${e(item.category)}</span>
        <strong class="cmd-item-title">${e(item.label)}</strong>
      </div>
      <kbd class="cmd-item-tag">${e(item.shortcut)}</kbd>
    </div>
  `,
    )
    .join("");

  const status = companySearchStatus || (!currentCommandMatches.length
    ? (q.length < 2 ? "Enter at least two characters." : "No match. Try a company name, NSE ticker, BSE code or ISIN.")
    : "");
  document.getElementById("command-status").textContent = status;
  selectCommand(commandSelectedIndex);
}

function selectCommand(index) {
  const list = document.getElementById("command-list");
  const input = document.getElementById("command-input");
  const previous = list.querySelector(".selected");
  previous?.classList.remove("selected");
  previous?.setAttribute("aria-selected", "false");
  commandSelectedIndex = index;
  const option = document.getElementById(`command-option-${index}`);
  if (option) {
    option.classList.add("selected");
    option.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView({ block: "nearest" });
  } else input.removeAttribute("aria-activedescendant");
}

async function executeSelectedCommand() {
  if (!currentCommandMatches.length && pendingCompanySearch) {
    const request = companySearchRequest;
    await pendingCompanySearch();
    if (request.signal.aborted || !document.getElementById("command-palette-dialog").open) return;
  }
  if (currentCommandMatches[commandSelectedIndex]) {
    const item = currentCommandMatches[commandSelectedIndex];
    closeCommandPalette();
    await item.action();
  }
}

// -------------------------------------------------------------
// Theme Management (Dark / Light)
// -------------------------------------------------------------

function toggleTheme() {
  if (typeof document === "undefined") return;
  const current =
    document.documentElement.getAttribute("data-theme") || "light";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem("finn-theme", next);
  } catch {
    // The current appearance still applies if storage is disabled.
  }
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = next === "dark" ? "☀️" : "🌓";
  if (typeof toast === "function") toast(`Switched to ${next} theme.`);
}

// -------------------------------------------------------------
// Keyboard Navigation (J/K/S/R/T/?)
// -------------------------------------------------------------

let focusedCardIndex = -1;

function highlightFocusedCard(cards) {
  cards.forEach((c, idx) => {
    const isFocused = idx === focusedCardIndex;
    c.classList.toggle("is-focused", isFocused);
    if (isFocused) {
      c.scrollIntoView({ behavior: "smooth", block: "nearest" });
      const primaryBtn = c.querySelector(".signal-footer [data-filing]");
      if (primaryBtn) primaryBtn.focus({ preventScroll: true });
    }
  });
}

// Global click delegation
async function handleDeskClick(event, button) {
  const cmdItem = event.target.closest(".command-item");
  if (cmdItem) {
    const idx = Number(cmdItem.dataset.cmdIdx);
    if (!Number.isNaN(idx) && currentCommandMatches[idx]) {
      closeCommandPalette();
      await currentCommandMatches[idx].action();
    }
    return true;
  }
  if (!button) return false;

  if (button.id === "theme-toggle") {
    toggleTheme();
    return true;
  }
  if (button.id === "cmd-k-trigger") {
    openCommandPalette();
    return true;
  }
  if (button.id === "close-command") {
    closeCommandPalette();
    return true;
  }
  if (button.id === "play-audio-brief") {
    toggleAudioBrief();
    return true;
  }
  if (button.id === "shortcuts-button") {
    const dialog = document.getElementById("shortcuts-dialog");
    if (dialog && !dialog.open) dialog.showModal();
    return true;
  }
  if (button.id === "close-shortcuts") {
    const dialog = document.getElementById("shortcuts-dialog");
    if (dialog?.open) dialog.close();
    return true;
  }
  if (!state.data) return false;

  try {
    if (button.dataset.askExample) {
      $("#desk-question").value = button.dataset.askExample;
      await answerDeskQuestion(button.dataset.askExample);
      return true;
    } else if (button.dataset.saveFiling || button.dataset.reviewFiling) {
      const id = button.dataset.saveFiling || button.dataset.reviewFiling;
      const field = button.dataset.saveFiling ? "saved" : "reviewed";
      button.disabled = true;
      await saveReview(id, { [field]: !filingReview(id)[field] });
      toast(
        field === "saved"
          ? filingReview(id).saved
            ? "Saved to your reading list."
            : "Removed from saved filings."
          : filingReview(id).reviewed
            ? "Reviewed. One less thing to read."
            : "Moved back to your review queue.",
      );
      const replacement = document.querySelector(
        `[data-${field === "saved" ? "save" : "review"}-filing="${CSS.escape(id)}"]`,
      );
      if (!$("#detail-dialog").open)
        (replacement || $("[data-queue].active"))?.focus({
          preventScroll: true,
        });
    } else if (button.dataset.queue) {
      state.queue = button.dataset.queue;
      if (state.queue === "focus") {
        state.category = "all";
        state.query = "";
        state.symbol = "";
        $("#filing-search").value = "";
        $("#category-filter").value = "all";
      }
      updateBriefTools();
      renderFilings();
      $("#queue-tools").scrollIntoView({ behavior: "smooth", block: "start" });
      $("[data-queue].active")?.focus({ preventScroll: true });
    } else if (button.dataset.pulse) {
      state.symbol =
        state.symbol === button.dataset.pulse ? "" : button.dataset.pulse;
      state.queue = "all";
      state.query = "";
      state.category = "all";
      $("#filing-search").value = "";
      $("#category-filter").value = "all";
      updateBriefTools();
      renderFilings();
      $("#queue-tools").scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (button.id === "clear-symbol") {
      state.symbol = "";
      renderBrief();
    } else if (button.dataset.question !== undefined) {
      const question = researchQuestions[Number(button.dataset.question)];
      if (!question) return;
      $("#research-question").value = question.question;
      state.researchQuestion = question.question;
      $("#research-question").focus();
    } else if (button.dataset.lens) {
      state.lens = button.dataset.lens;
      applyResearchLens();
    } else if (button.dataset.followUp) {
      const filing = state.data.filings.find(
        (f) => f.id === button.dataset.followUp,
      );
      if (!filing) return;
      state.researchSymbol = filing.symbol;
      state.researchQuestion =
        followUpQuestions[filing.category] ||
        "What do the primary sources say about cash generation and risks?";
      state.report = null;
      $("#detail-dialog").close();
      setView("research");
      $("#research-question").focus();
    } else return false;
  } catch (error) {
    toast(error.message);
  } finally {
    if (button.dataset.saveFiling || button.dataset.reviewFiling) button.disabled = false;
  }
  return true;
}

// Command palette input listener
document.addEventListener("input", (event) => {
  if (event.target.id === "command-input") {
    updateCommandSearch(event.target.value);
  }
});

document.addEventListener("close", (event) => {
  if (event.target.id === "command-palette-dialog" && !event.target.open) {
    clearTimeout(companySearchTimer);
    companySearchRequest?.abort();
    pendingCompanySearch = null;
  }
}, true);

// Keyboard navigation listeners
document.addEventListener("keydown", (event) => {
  // Command palette shortcuts
  const cmdDialog = document.getElementById("command-palette-dialog");
  const isCmdOpen = cmdDialog?.open;

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (isCmdOpen) closeCommandPalette();
    else openCommandPalette();
    return;
  }

  if (isCmdOpen) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (commandSelectedIndex < currentCommandMatches.length - 1) {
        selectCommand(commandSelectedIndex + 1);
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (commandSelectedIndex > 0) {
        selectCommand(commandSelectedIndex - 1);
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      executeSelectedCommand().catch((error) => toast(error.message));
    } else if (event.key === "Escape") {
      closeCommandPalette();
    }
    return;
  }

  // Ignore global shortcuts when user is typing in forms or dialogues are open
  const activeTag = document.activeElement?.tagName;
  const isTyping =
    ["INPUT", "TEXTAREA", "SELECT"].includes(activeTag) ||
    document.activeElement?.isContentEditable;
  const isAnyModalOpen = document.querySelector("dialog[open]");

  if (isTyping || isAnyModalOpen) {
    if (event.key === "Escape" && isAnyModalOpen) {
      isAnyModalOpen.close();
    }
    return;
  }

  if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
  const cards = [...document.querySelectorAll(".signal-card")].filter(
    (card) => !card.closest("details:not([open])"),
  );
  focusedCardIndex = cards.indexOf(document.activeElement?.closest(".signal-card"));
  if (event.key === "j" || event.key === "J") {
    event.preventDefault();
    if (cards.length) {
      focusedCardIndex = Math.min(focusedCardIndex + 1, cards.length - 1);
      highlightFocusedCard(cards);
    }
  } else if (event.key === "k" || event.key === "K") {
    event.preventDefault();
    if (cards.length) {
      focusedCardIndex = Math.max(focusedCardIndex - 1, 0);
      highlightFocusedCard(cards);
    }
  } else if (event.key === "s" || event.key === "S") {
    if (focusedCardIndex >= 0 && cards[focusedCardIndex]) {
      const saveBtn =
        cards[focusedCardIndex].querySelector("[data-save-filing]");
      if (saveBtn) saveBtn.click();
    }
  } else if (event.key === "r" || event.key === "R") {
    if (focusedCardIndex >= 0 && cards[focusedCardIndex]) {
      const revBtn = cards[focusedCardIndex].querySelector(
        "[data-review-filing]",
      );
      if (revBtn) revBtn.click();
    }
  } else if (event.key === "t" || event.key === "T") {
    event.preventDefault();
    toggleTheme();
  } else if (event.key === "?") {
    event.preventDefault();
    const dialog = document.getElementById("shortcuts-dialog");
    if (dialog && !dialog.open) dialog.showModal();
  } else if (
    event.key >= "1" &&
    event.key <= "4" &&
    state?.view === "research"
  ) {
    const keys = ["all", "business", "cash", "promises"];
    const targetLens = keys[Number(event.key) - 1];
    if (targetLens) {
      state.lens = targetLens;
      applyResearchLens();
    }
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.id === "desk-ask-form") {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    button.disabled = true;
    try {
      await answerDeskQuestion($("#desk-question").value);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (form.id !== "filing-note-form") return;
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await saveReview(form.dataset.identity, {
      note: $("#filing-note").value.trim(),
    });
    toast("Note saved to this filing.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
