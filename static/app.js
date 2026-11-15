"use strict";

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const e = escapeHTML;
function highlightNumbers(text) {
  const numeric = /((?<!\w)₹?[-−]?\d+(?:,\d+)*(?:\.\d+)?(?:%|\s*(?:crore|lakh|cr|mn|bn)\b)?(?!\w))/gi;
  return String(text ?? "").split(numeric).map((part, index) =>
    index % 2 ? `<mark class="evidence-quote-hl">${e(part)}</mark>` : e(part),
  ).join("");
}
const number = (value, digits = 0) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("en-IN", { maximumFractionDigits: digits });
const signed = (value) =>
  value == null ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
const safeURL = (value) => {
  try {
    const url = new URL(value, location.origin);
    return ["https:", "http:"].includes(url.protocol) ? e(url.href) : "#";
  } catch {
    return "#";
  }
};
const external = (url, text) =>
  url
    ? `<a href="${safeURL(url)}" target="_blank" rel="noopener noreferrer">${e(text)} ↗</a>`
    : "";
const time = (value) =>
  value
    ? new Date(value).toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Kolkata",
      }) + " IST"
    : "Not yet refreshed";
const icons = {
  brief:
    '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  portfolio:
    '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4h8v3M3 12h18M10 12v3h4v-3"/>',
  research:
    '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5M8 11h5M10.5 8.5v5"/>',
  network:
    '<path d="m9 10-3 6m9-6 3 6M8 19h8"/><circle cx="12" cy="6" r="4"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>',
  alerts: '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zM10 21h4M12 2v2"/>',
  settings:
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="10" cy="18" r="2" fill="currentColor"/>',
};
const navigation = {
  brief: "Daily brief",
  portfolio: "Portfolio",
  research: "Research",
  network: "Network",
  alerts: "Alerts",
  settings: "Preferences",
};
const titles = {
  brief: [
    "Daily brief",
    "Material filings and unusual moves across your watchlist.",
  ],
  portfolio: [
    "Watchlist",
    "Companies you follow, with closing prices in INR.",
  ],
  research: [
    "Research",
    "Explore annual reports and earnings calls.",
  ],
  network: [
    "Your network",
    "Find relevant experience and see how you’re connected.",
  ],
  alerts: [
    "Alerts",
    "Filings, price and volume signals that matched your rules.",
  ],
  settings: [
    "Preferences",
    "Choose the signals you want to receive.",
  ],
};
const state = {
  view: "brief",
  data: null,
  digest: null,
  hours: "24",
  query: "",
  category: "all",
  report: null,
  researching: false,
  queue: "all",
  symbol: "",
  lens: "all",
  alertFilter: "all",
};
let toastTimer,
  loadSequence = 0,
  digestSequence = 0,
  sourceSearchSequence = 0;
function toast(text) {
  const target = $("#detail-dialog").open ? $("#dialog-toast") : $("#toast");
  document.querySelectorAll(".toast.show").forEach((node) => node.classList.remove("show"));
  target.textContent = text;
  target.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => target.classList.remove("show"), 4500);
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      ...options,
    });
  } catch (error) {
    if (error.name === "TimeoutError")
      throw new Error("FINN took too long to respond. Please try again shortly.");
    throw error;
  }
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : Array.isArray(data?.detail)
          ? data.detail.map((item) => item.msg).join("; ")
          : `The request could not be completed (HTTP ${response.status}).`,
    );
  if (data === null) throw new Error("FINN returned an unreadable response.");
  return data;
}
function post(path, data, method = "POST") {
  return api(path, { method, body: JSON.stringify(data) });
}
function empty(title, message) {
  return `<div class="empty"><h3>${e(title)}</h3><p>${e(message)}</p></div>`;
}
function loadingSkeleton() {
  return '<div class="desk-skeleton" role="status" aria-label="Loading your investment desk"><span class="sr-only">Loading your investment desk…</span><div class="skeleton-hero"></div><div class="skeleton-row"></div><div class="skeleton-row short"></div></div>';
}
function showDialog(html) {
  const dialog = $("#detail-dialog");
  $("#dialog-content").innerHTML = html;
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}
function sparkline(history, positive) {
  if (!history?.length) return "";
  const low = Math.min(...history),
    range = Math.max(...history) - low || 1;
  const points = history
    .map(
      (v, i) =>
        `${(i * 80) / (history.length - 1 || 1)},${24 - ((v - low) / range) * 20}`,
    )
    .join(" ");
  return `<svg class="sparkline" viewBox="0 0 80 28" role="img" aria-label="Recent closing-price trend"><polyline points="${points}" fill="none" stroke="${positive ? "#2452be" : "#ac4438"}" stroke-width="1.5"/></svg>`;
}
function updateAlertBadge() {
  const count = state.data?.alerts.filter((a) => !a.read).length || 0;
  const alerts = $("#navigation [data-view=alerts]");
  if (!alerts) return;
  alerts.setAttribute("aria-label", count ? `Alerts, ${count} unread` : "Alerts");
  let badge = alerts.querySelector(".nav-count");
  if (!count) {
    badge?.remove();
    return;
  }
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "nav-count";
    badge.setAttribute("aria-hidden", "true");
    alerts.append(badge);
  }
  badge.textContent = count > 99 ? "99+" : count;
}
function nav() {
  document.body.dataset.view = state.view;
  $("#navigation").innerHTML = Object.entries(navigation)
    .map(
      ([key, label]) =>
        `<button class="nav-item ${state.view === key ? "active" : ""}" data-view="${key}" aria-label="${label}" ${state.view === key ? 'aria-current="page"' : ""}>
          <span class="nav-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">${icons[key]}</svg></span>
          <span class="nav-label">${label}</span>
          ${key === "brief" || key === "portfolio" ? `<span class="mobile-nav-label">${key === "brief" ? "Brief" : "Watchlist"}</span>` : ""}
        </button>`,
    )
    .join("");
  updateAlertBadge();
  $("#breadcrumb").textContent = navigation[state.view];
  $("#page-title").textContent = titles[state.view][0];
  $("#page-subtitle").textContent = titles[state.view][1];
}
async function loadData(renderPage = true) {
  const sequence = ++loadSequence;
  const data = await api("/api/state?mode=live");
  if (sequence !== loadSequence) return;
  if (data.mode !== "live") {
    throw new Error("This server returned demo data. Restart FINN from the Founding AI Engineer folder.");
  }
  state.data = data;
  await loadDigest();
  if (sequence !== loadSequence) return;
  if (!renderPage) {
    updateAlertBadge();
    return;
  }
  renderSourceStatus();
  render();
}
function renderSourceStatus() {
  const data = state.data;
  $("#data-banner").innerHTML =
    `<span><strong>PUBLIC SOURCES</strong> · Yahoo Finance and NSE</span><span>${data.updated_at ? `Refresh attempted ${e(time(data.updated_at))}` : "Awaiting first refresh"}</span>`;
  const noticesOpen = $("#source-errors details")?.open;
  $("#source-errors").innerHTML = data.errors.length
    ? `<div class="warning"><details><summary>${data.errors.length} source notice${data.errors.length > 1 ? "s" : ""} · some coverage may be unavailable</summary><ul>${data.errors.map((v) => `<li>${e(v)}</li>`).join("")}</ul></details></div>`
    : "";
  if (noticesOpen && $("#source-errors details")) $("#source-errors details").open = true;
  if (typeof renderMarketTape === "function") renderMarketTape();
  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    const curTheme =
      document.documentElement.getAttribute("data-theme") || "light";
    themeBtn.textContent = curTheme === "dark" ? "☀️" : "🌓";
  }
}
function digestParams() {
  const params = new URLSearchParams({
    mode: "live",
    hours: state.hours === "custom" ? "24" : state.hours,
  });
  if (state.hours === "custom" && state.start && state.end) {
    params.set("start", state.start);
    params.set("end", state.end);
  }
  return params;
}
async function loadDigest() {
  const sequence = ++digestSequence;
  const digest = await api(`/api/digest?${digestParams()}`);
  if (sequence !== digestSequence) return;
  if (digest.items.some((filing) => filing.mode !== "live")) {
    throw new Error("This server returned demo filings. Restart FINN from the Founding AI Engineer folder.");
  }
  state.digest = digest;
}
function render() {
  $("#workspace-updates").hidden = true;
  nav();
  if (!state.data) return;
  ({
    brief: renderBrief,
    portfolio: renderPortfolio,
    research: renderResearch,
    network: renderNetwork,
    alerts: renderAlerts,
    settings: renderSettings,
  })[state.view]();
}
function setView(view) {
  state.view = view;
  if (state.data) renderSourceStatus();
  render();
  window.scrollTo({ top: 0, behavior: "instant" });
  $("#main").focus({ preventScroll: true });
}
function filingCard(filing) {
  const label =
    state.data.categories.find((c) => c.id === filing.category)?.label ||
    filing.category;
  return `<article class="signal-card ${filingReview(filing.id).reviewed ? "is-read" : ""} ${filing.priority >= 70 ? "material" : ""}"><div class="signal-top"><span class="ticker">${e(filing.symbol)}</span><span class="tag ${filing.priority >= 80 ? "amber" : ""}">${e(label)}</span><span class="timestamp">${e(time(filing.published_at))}</span></div><h3 class="signal-title">${e(filing.title)}</h3><p class="signal-description">${e(filing.summary || filing.reason)}</p>${networkHint(filing.network, filing.id)}<div class="signal-footer"><span>${e(filing.source)} · Priority ${filing.priority}</span><button data-filing="${e(filing.id)}">${filing.category === "results" ? "See the numbers" : filing.category === "management_change" ? "Meet the incoming leader" : "Read the filing"} <span aria-hidden="true">↗</span></button></div>${reviewControls(filing)}</article>`;
}
function filteredFilings() {
  return briefSelection(state.digest.items, state, state.data.reviews || {});
}
function renderFilings() {
  const routineOpen = $("#filing-list .routine")?.open;
  const items = filteredFilings(),
    material = items.filter((f) => f.priority >= 50),
    routine = items.filter((f) => f.priority < 50);
  $("#filing-list").innerHTML =
    (material.length
      ? material.map(filingCard).join("")
      : empty(
          state.queue === "focus"
            ? "You’re through your focus queue."
            : state.queue === "saved"
              ? "A place for your next good question."
              : "A quiet window.",
          items.length
            ? "The filings in this window are routine. Expand them below."
            : state.queue === "saved"
              ? "Save a filing to revisit it here. Saved items respect the selected time window."
              : "No filings match these filters. Try All filings, a wider window, or refresh sources.",
        )) +
    (routine.length
      ? `<details class="routine"><summary>${routine.length} routine or supporting filing${routine.length === 1 ? "" : "s"} · kept out of your way</summary>${routine.map(filingCard).join("")}</details>`
      : "");
  if (routineOpen && $("#filing-list .routine")) $("#filing-list .routine").open = true;
}
function renderBrief() {
  const routineOpen = $("#filing-list .routine")?.open;
  const { data, digest } = state,
    material = digest.items.filter((f) => f.priority >= 50).length;
  const prices = Object.values(data.prices),
    abnormal = prices.filter(
      (p) =>
        Math.abs(p.change_pct || 0) >= data.settings.price_threshold ||
        (p.baseline_sessions >= 20 &&
          (p.volume_ratio || 0) >= data.settings.volume_threshold),
    ).length;
  const stats = [
    [
      "WATCHED",
      data.portfolio.length,
      "Across sectors & market sizes",
    ],
    [
      "FILINGS",
      digest.items.length,
      `${material} prioritised for your attention`,
    ],
    [
      "UNUSUAL MOVES",
      abnormal,
      `±${data.settings.price_threshold}% price · ${data.settings.volume_threshold}× volume`,
    ],
    [
      "ROUTINE",
      digest.routine_count,
      "Every filing is still one click away",
    ],
  ];
  $("#content").innerHTML =
    `<div id="focus-hero-slot">${focusHero()}</div><div class="stats">${stats.map(([label, value, note]) => `<div class="stat"><div class="stat-label">${label}<span aria-hidden="true">↗</span></div><div class="stat-value">${value.toString().padStart(2, "0")}</div><div class="stat-note">${e(note)}</div></div>`).join("")}</div><div class="dashboard"><section><div class="section-heading"><div><h2>Priority filings</h2><p>Material filings first.</p></div><label><span class="sr-only">Digest time window</span><select id="time-window">${[
      ["24", "Last 24 hours"],
      ["72", "Last 3 days"],
      ["168", "Last 7 days"],
      ["720", "Last 30 days"],
      ["custom", "Custom window"],
    ]
      .map(
        ([v, l]) =>
          `<option value="${v}" ${state.hours === v ? "selected" : ""}>${l}</option>`,
      )
      .join(
        "",
      )}</select></label></div>${state.hours === "custom" ? `<form class="custom-window" id="window-form"><label>From (local time)<input type="datetime-local" id="window-start" required value="${e(state.startInput || "")}"></label><label>To (local time)<input type="datetime-local" id="window-end" required value="${e(state.endInput || "")}"></label><button class="button" type="submit">Apply window</button></form>` : ""}<div id="queue-tools">${queueTabs()}</div><div class="filters"><input id="filing-search" type="search" placeholder="Search your brief…" aria-label="Search filings" value="${e(state.query)}"><select id="category-filter" aria-label="Announcement category"><option value="all">All categories</option>${data.categories.map((c) => `<option value="${e(c.id)}" ${state.category === c.id ? "selected" : ""}>${e(c.label)}</option>`).join("")}</select></div>${digest.coverage_warning ? `<div class="warning">${e(digest.coverage_warning)}</div>` : ""}<div id="filing-list"></div></section><aside class="right-column"><section class="side-card"><div class="side-card-header"><h3>On your radar</h3><span>EOD · INR</span></div>${data.portfolio
      .slice(0, 6)
      .map((c) => {
        const p = data.prices[c.symbol];
        return `<div class="watch-row"><div><strong>${e(c.symbol)}</strong><small>${e(c.sector)}</small></div>${p ? sparkline(p.history, (p.change_pct || 0) >= 0) : "<span>—</span>"}<div class="watch-price">${number(p?.close)}<small class="${p?.change_pct >= 0 ? "positive" : "negative"}">${signed(p?.change_pct)}</small></div></div>`;
      })
      .join(
        "",
      )}<button class="side-link" data-view="portfolio">View all ${data.portfolio.length} companies <span aria-hidden="true">→</span></button></section><section class="research-promo"><div class="eyebrow">FROM FILING TO UNDERSTANDING</div><h3>Good questions.<br>Grounded answers.</h3><p>Annual reports. Earnings calls. The evidence behind the business.</p><button class="button" data-view="research">Research a company <span aria-hidden="true">↗</span></button></section><p class="tiny-note">Your brief uses transparent priority rules. Supporting disclosures are collapsed, never discarded.</p></aside></div>`;
  $("#filing-list").insertAdjacentHTML("afterend", portfolioPulse() + deskAskBar());
  renderFilings();
  if (routineOpen && $("#filing-list .routine")) $("#filing-list .routine").open = true;
}
function renderPortfolio() {
  const { portfolio, prices } = state.data;
  const expanded = new Set(
    [...document.querySelectorAll(".watchlist-company[open]")].map((row) => row.dataset.companyCard),
  );
  const rows = portfolio.map((company) => {
    const price = prices[company.symbol];
    const hasClose = price?.close != null;
    const change = price?.change_pct;
    const direction = change > 0 ? "positive" : change < 0 ? "negative" : "";
    return `<details class="watchlist-company" data-company-card="${e(company.symbol)}"${expanded.has(company.symbol) ? " open" : ""}>
      <summary class="watchlist-summary">
        <span class="watchlist-identity">
          <strong>${e(company.symbol)}</strong>
          <span class="watchlist-name">${e(company.name)}</span>
        </span>
        <span class="watchlist-quote">
          <strong>${hasClose ? `₹${number(price.close, 2)}` : "—"}</strong>
          <span class="watchlist-move"><span class="${direction}">${hasClose ? signed(change) : "No quote"}</span>${price?.stale && hasClose ? " · Cached" : ""}</span>
        </span>
        <span class="watchlist-chevron" aria-hidden="true"></span>
      </summary>
      <div class="watchlist-details">
        <p><span class="tag">${e(company.sector)}</span> ${e(company.size)}</p>
        ${hasClose ? `
          ${sparkline(price.history, change >= 0)}
          <p>Volume ${number(price.volume)}${price.volume_ratio != null ? ` · ${number(price.volume_ratio, 2)}× average · ${number(price.baseline_sessions)} prior sessions` : ""}</p>
          <p>Close ${e(price.date)}${price.stale ? " · cached after a failed refresh" : ""} · ${external(price.source_url, price.source) || e(price.source)}</p>
        ` : "<p>Refresh sources to load end-of-day data.</p>"}
        <div class="watchlist-actions">
          <button type="button" class="button" data-research="${e(company.symbol)}">Research company ↗</button>
          <button type="button" class="text-button" data-remove="${e(company.symbol)}" aria-label="Remove ${e(company.symbol)} from watchlist">Remove</button>
        </div>
      </div>
    </details>`;
  }).join("");
  $("#content").innerHTML = `<section class="watchlist-view">
    <div class="section-heading"><div><h2>${portfolio.length} ${portfolio.length === 1 ? "company" : "companies"}</h2><p>NSE · End-of-day quotes</p></div><button id="add-company" class="button">+ Add company</button></div>
    ${rows ? `<div class="watchlist-list">${rows}</div>` : empty("Your watchlist is empty", "Add an NSE company to follow its filings and closing price.")}
  </section>`;
}
function renderResearch() {
  const busy = state.researching;
  const disabled = busy ? "disabled" : "";
  const model = state.data.model_name;
  const status = state.data.model_configured
    ? `${model || "Gemini"} · AI analysis may use API quota.`
    : "Source briefs are available. Set GEMINI_API_KEY to enable AI analysis.";
  $("#content").innerHTML =
    `<section class="panel">
      <form class="research-form" id="research-form">
        <label class="field">NSE symbol<input name="symbol" id="research-symbol" placeholder="e.g. TCS or INFY" value="${e(state.researchSymbol || state.report?.symbol || "")}" maxlength="28" required autocapitalize="characters" spellcheck="false" ${disabled}></label>
        <label class="field">Your question <span class="sr-only">optional for NSE research</span><input name="question" id="research-question" placeholder="Are profits turning into cash?" maxlength="500" value="${e(state.researchQuestion || "")}" ${disabled}></label>
        <button class="button primary" type="button" id="analyze-research" aria-describedby="research-model-status" ${busy || !state.data.model_configured ? "disabled" : ""}>Analyze with AI</button>
        <button class="button ${state.data.model_configured ? "" : "primary"}" type="submit" ${disabled}>Build source brief ↗</button>
      </form>
      <p id="research-model-status" class="tiny-note">${e(status)}</p>
      <div class="research-tools">
        <button type="button" id="research-stock-move" class="chip" ${disabled}>Check stock move ↗</button>
        <details class="research-method"><summary>How FINN answers</summary>
          <p>Gemini uses dated trading-session data for stock patterns and cited company documents for fundamentals.</p>
        </details>
      </div>
      <div class="suggestions"><span>Research shortcuts:</span>
        ${state.data.research_companies.map((c) => `<button class="chip" data-research="${e(c.symbol)}" ${disabled}>${e(c.symbol)}</button>`).join("")}
      </div>
      ${busy ? "" : researchPrompts()}
    </section>
    <div id="research-result">${busy ? `<div class="loading" role="status">${e(state.researchLoadingMessage)}</div>` : ""}</div>`;
  if (state.report && !busy) {
    if (state.report.kind === "market") renderMarketAnswer(state.report);
    else renderReport();
  }
  else if (!busy)
    $("#research-result").innerHTML =
      `<div class="research-landing"><div><div class="eyebrow">A RESEARCH DESK THAT SHOWS ITS WORK</div><h2>Read the business.<br>Question the story.</h2><p>Move from management's narrative to the numbers behind it. Each brief draws from annual reports and earnings-call transcripts, with the source a click away.</p></div><div class="research-list"><div><span>01</span>Understand the business and its economics</div><div><span>02</span>Follow earnings through to cash</div><div><span>03</span>Compare promises with performance</div><div><span>04</span>Read the case from both sides</div></div></div>`;
}
function renderMarketAnswer(answer) {
  $("#research-result").innerHTML = marketAnswerHtml(answer);
}
function marketAnswerHtml(answer) {
  const quote = answer.quote;
  const trend = answer.trend;
  const movement = quote?.change_pct;
  const direction = movement > 0 ? "positive" : movement < 0 ? "negative" : "";
  const rupees = (value) => `₹${number(value, 2)}`;
  return `
    <section class="panel market-answer" aria-labelledby="market-answer-title">
      <div class="eyebrow">${e(answer.symbol)} · NSE</div>
      <h2 id="market-answer-title">${trend || answer.analysis ? "Stock pattern" : "Latest completed session"}</h2>
      ${quote ? `<p class="market-session-date">${e(quote.date)} · Closing prices</p>
      <div class="market-answer-price"><strong>${rupees(quote.close)}</strong>
        <span class="${direction}">${movement == null ? "Change unavailable" : signed(movement)}</span></div>
      ${answer.analysis ? `<div class="market-analysis"><h3>Gemini analysis</h3><p>${e(answer.analysis.text)}</p></div>` : ""}
      ${trend ? `<div class="market-trend">
        <div class="market-trend-heading"><h3>${trend.sessions} completed sessions</h3><strong>${signed(trend.return_pct)}</strong></div>
        ${sparkline(trend.closes, trend.return_pct >= 0)}
        <dl class="market-answer-facts">
          <div><dt>Closing low</dt><dd>${rupees(trend.low_close)}</dd></div>
          <div><dt>Closing high</dt><dd>${rupees(trend.high_close)}</dd></div>
          ${trend.average_20_close != null ? `<div><dt>20-session average</dt><dd>${rupees(trend.average_20_close)}</dd></div>` : ""}
        </dl>
      </div>` : ""}
      <dl class="market-answer-facts">
        ${quote.previous_close != null ? `<div><dt>Previous close</dt><dd>${rupees(quote.previous_close)}</dd></div>
        <div><dt>Price change</dt><dd class="${direction}">${quote.change >= 0 ? "+" : "−"}${rupees(Math.abs(quote.change))}</dd></div>` : ""}
        ${(trend || answer.analysis) && quote.low != null && quote.high != null ? `<div><dt>Day range</dt><dd>${rupees(quote.low)}–${rupees(quote.high)}</dd></div>` : ""}
        ${quote.volume != null ? `<div><dt>Volume</dt><dd>${number(quote.volume)} shares</dd>
          ${quote.volume_ratio != null ? `<dd class="market-volume-context">${number(quote.volume_ratio, 2)}× 20-session average</dd>` : ""}</div>` : ""}
      </dl>
      ${external(quote.source_url, "Yahoo Finance quote")}` : ""}
      ${answer.notes.map((note) => `<p class="market-session-date">${e(note)}</p>`).join("")}
      ${quote?.previous_close != null ? `<details class="research-method"><summary>How the move was calculated</summary><p>(${rupees(quote.close)} ÷ ${rupees(quote.previous_close)} − 1) × 100 = ${signed(movement)}.</p></details>` : ""}
    </section>`;
}
function renderReport() {
  const r = state.report;
  const priority = ["Your question", "Financial snapshot", "Cash quality", "Guidance", "Business snapshot"];
  const highlights = priority
    .map((title) => r.sections.find((section) => section.title === title && (title === "Your question" || section.claims.length)))
    .filter(Boolean).slice(0, 3);
  const more = r.sections.filter((section) => !highlights.includes(section));
  const warnings = r.warnings.filter((warning) => warning !== r.analysis_notice);
  const comparisonsHtml = r.comparisons.length
    ? `${renderCredibilityScorecard(r.comparisons)}<div class="table-scroll"><table class="financial-table guidance-table"><thead><tr><th>Period / metric</th><th>Guidance</th><th>Actual</th><th>Outcome</th></tr></thead><tbody>${r.comparisons
        .map((c, index) => {
          const assessmentLower = (c.assessment || "").toLowerCase();
          const badgeClass = assessmentLower.includes("beat")
            ? "score-badge beat"
            : assessmentLower.includes("miss")
              ? "score-badge miss"
              : assessmentLower.includes("met")
                ? "score-badge met"
                : "score-badge";
          return `<tr>
          <td><strong>${e(c.period)}</strong><br><small class="mono-sub">${e(c.metric)}</small></td>
          <td><button type="button" class="guidance-evidence" data-comparison="${index}" data-evidence-role="promise" aria-label="${e(`Read guidance evidence for ${c.period}, ${c.metric}: ${c.promised}`)}">${e(c.promised)} <span aria-hidden="true">↗</span></button></td>
          <td><button type="button" class="guidance-evidence" data-comparison="${index}" data-evidence-role="actual" aria-label="${e(`Read actual evidence for ${c.period}, ${c.metric}: ${c.delivered}`)}">${e(c.delivered)} <span aria-hidden="true">↗</span></button></td>
          <td><span class="${badgeClass}">${e(c.assessment)}</span></td>
        </tr>`;
        })
        .join("")}</tbody></table></div>`
    : empty(
        "No verified comparison yet.",
        "Comparisons need cited guidance and actual results for the same metric and period.",
      );

  $("#research-result").innerHTML = `
    ${r.market ? marketAnswerHtml(r.market) : ""}
    <section class="company-overview panel" aria-label="Company overview">
      <div class="section-heading"><div><span class="tag">${e(r.symbol)} · NSE</span><h2>${e(r.name)}</h2></div>
      <button class="button" id="export-report">Export brief ↓</button></div>
      <div class="research-meta"><span>${r.sources.length} of ${r.discovered_count} documents read</span><span>${r.sections.some((s) => s.status === "analysis") || r.comparisons.length ? "Gemini analysis" : "Source excerpts"}</span><span>${r.cached ? "Cached · " : ""}${e(time(r.generated_at))}</span></div>
    </section>
    ${r.analysis_notice ? `<p class="warning research-notice">${e(r.analysis_notice)}</p>` : ""}
    ${warnings.length ? `<details class="research-coverage"><summary>Source coverage <span>${r.sources.length}/${r.discovered_count} read</span></summary>
      <ul>${warnings.map((warning) => `<li>${e(warning)}</li>`).join("")}</ul>
    </details>` : ""}
    <div class="report-switch" role="group" aria-label="Company research view">
      <button type="button" data-report-view="findings" aria-pressed="true">Findings</button>
      <button type="button" data-report-view="documents" aria-pressed="false">Documents · ${r.sources.length}</button>
    </div>
    <div id="report-findings">
      ${researchLensBar()}
      <div class="research-grid research-highlights">${highlights.map(renderResearchFinding).join("")}</div>
      ${more.length ? `<details class="research-more"><summary>More research topics</summary><div class="research-grid">${more.map(renderResearchFinding).join("")}</div></details>` : ""}
      <section class="comparison"><div class="section-heading"><div><h2>Guidance vs. results</h2><p>Four quarters compared by metric and reporting basis.</p></div></div>${comparisonsHtml}<p class="comparison-note">${e(r.comparison_note)}</p></section>
      ${r.network?.matches?.length ? `<details class="research-network">
        <summary><span>Network context</span><span>${r.network.matches.length} contact${r.network.matches.length === 1 ? "" : "s"}</span></summary>
        ${networkContext(r.network)}
      </details>` : ""}
    </div>
    <section id="report-documents" class="panel sources" hidden aria-labelledby="document-search-title">
      <h3 id="document-search-title">Search company documents</h3>
      <form id="source-search-form" class="source-search-form">
        <label class="field">Phrase<input name="q" type="search" placeholder="e.g. working capital" required minlength="2" maxlength="100" enterkeyhint="search"></label>
        <label class="field">Document type<select name="kind"><option value="transcript" ${r.sources.some((s) => s.kind === "transcript") ? "selected" : ""}>Earnings transcripts</option><option value="all" ${r.sources.some((s) => s.kind === "transcript") ? "" : "selected"}>All primary documents</option><option value="annual_report">Annual reports</option></select></label>
        <button class="button primary" type="submit">Search text</button>
      </form>
      <div id="source-search-results" aria-live="polite"></div>
      <h3 class="source-library-heading">Documents read</h3>
      <div class="source-list">${r.sources.map((s) => `<div>${external(s.url, s.title) || `<span>${e(s.title)}</span>`}<small>${s.page_count} pages · ${e(s.kind.replace("_", " "))}</small></div>`).join("")}</div>
    </section>`;
  applyResearchLens();
}

function renderResearchFinding(section) {
  const [claim] = section.claims;
  const citation = claim && state.report.citations[claim.citation];
  const missing = section.title === "Your question"
    ? "These company documents don’t support an answer. For trading data, use Check stock move."
    : "No supporting excerpt found.";
  return `<section class="research-section" data-research-section="${e(section.title)}">
    <h3>${e(section.title === "Your question" && section.status === "evidence" && claim ? "Source match for your question" : section.title)}</h3>
    <p class="research-takeaway">${claim ? (section.status === "analysis" ? e(claim.text) : highlightNumbers(claim.text)) : missing}</p>
    ${citation ? `<button type="button" class="research-citation" data-citation="${e(claim.citation)}" data-citation-section="${e(section.title)}" aria-label="${e(`Read source excerpt for ${section.title}, page ${citation.page}`)}">${section.status === "analysis" ? "Gemini · " : ""}Read excerpt · p. ${citation.page} ↗</button>` : ""}
  </section>`;
}

function setReportView(view) {
  $("#report-findings").hidden = view !== "findings";
  $("#report-documents").hidden = view !== "documents";
  document.querySelectorAll("[data-report-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.reportView === view));
  });
}

function sourcePage(url, page) {
  return url ? external(url.split("#")[0] + `#page=${page}`, `Open source · p. ${page}`) : "";
}

async function runSourceSearch(form) {
  const request = ++sourceSearchSequence;
  const output = $("#source-search-results");
  const params = new URLSearchParams(new FormData(form));
  const query = params.get("q").trim();
  if (query.length < 2) {
    output.textContent = "Enter at least two characters.";
    return;
  }
  output.textContent = "Searching downloaded documents…";
  try {
    const search = await api(`/api/research/${encodeURIComponent(state.report.symbol)}/sources/search?${params}`);
    if (request !== sourceSearchSequence || !output.isConnected) return;
    if (!search.documents) {
      output.textContent = "No downloaded documents of this type are available. Choose another type or rebuild the brief.";
      return;
    }
    output.innerHTML = `<p class="source-search-status">${search.results.length}${search.more ? "+" : ""} matching page${search.results.length === 1 && !search.more ? "" : "s"} across ${search.documents} searched document${search.documents === 1 ? "" : "s"}.</p>` +
      search.results.map((hit) => `<article class="source-hit"><h4>${e(hit.title)}</h4><small>${e(hit.kind.replace("_", " "))} · p. ${hit.page}</small>
        <blockquote>${e(hit.before)}<mark>${e(hit.match)}</mark>${e(hit.after)}</blockquote>
        ${sourcePage(hit.url, hit.page)}</article>`).join("");
  } catch (error) {
    if (request === sourceSearchSequence) output.textContent = error.message;
  }
}
async function runResearch(symbol, question = "", useAI = false, intent = "auto") {
  if (state.researching) return;
  state.researchSymbol = symbol;
  state.researchQuestion = question;
  state.researching = true;
  state.researchLoadingMessage = intent === "market"
    ? `Checking the latest completed session for ${symbol}…`
    : `Checking sources for ${symbol}…`;
  state.lens = "all";
  state.report = null;
  setView("research");
  let errorMessage;
  try {
    const report = await api("/api/research", {
      method: "POST",
      body: JSON.stringify({ symbol, question, mode: "live", use_ai: useAI, intent }),
      signal: AbortSignal.timeout(useAI ? 100000 : 60000),
    });
    if (report.mode !== "live") throw new Error("Public-source research is unavailable from this server.");
    state.report = report;
  } catch (error) {
    errorMessage = error.message;
  } finally {
    state.researching = false;
    if (state.view === "research") {
      renderResearch();
      if (errorMessage)
        $("#research-result").innerHTML = empty("Research could not be completed.", errorMessage);
      const result = $("#research-result");
      result.tabIndex = -1;
      result.focus({ preventScroll: true });
      result.scrollIntoView({ block: "start" });
    }
  }
}
async function openIndianCompany(company) {
  const request = ++profileRequest;
  showDialog(`<h2 id="dialog-title">${e(company.name)}</h2><div class="loading">Loading public quote…</div>`);
  try {
    const result = await api(`/api/companies/${encodeURIComponent(company.exchange)}/${encodeURIComponent(company.symbol)}`);
    if (request !== profileRequest || !$("#detail-dialog").open) return;
    const quote = result.quote;
    const identifiers = [
      result.exchange,
      result.symbol,
      result.code && `Scrip code ${result.code}`,
      result.isin,
    ].filter(Boolean).map(e).join(" · ");
    showDialog(`
      <h2 id="dialog-title">${e(result.name)}</h2>
      <p>${identifiers}</p>
      ${quote ? `<div class="company-profile-quote">
        <strong>${e(new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(quote.close))}</strong>
        ${quote.change_pct != null ? `<span class="${quote.change_pct >= 0 ? "positive" : "negative"}">${signed(quote.change_pct)}</span>` : ""}
        <small>Completed session ${e(quote.date)} · Volume ${number(quote.volume)}</small>
      </div>` : ""}
      ${result.warnings.map((warning) => `<p class="warning">${e(warning)}</p>`).join("")}
      <div class="company-profile-links">
        ${external(result.quote_url, "Yahoo Finance quote and history")}
        ${external(result.exchange_url, `${result.exchange} company page and disclosures`)}
      </div>
      ${result.research_symbol ? `<div class="network-profile-actions"><button class="button" type="button" data-research="${e(result.research_symbol)}">Build research brief ↗</button></div>` : '<p class="tiny-note">Research is available for listings with a matching NSE symbol.</p>'}
    `);
  } catch (error) {
    if (request === profileRequest && $("#detail-dialog").open)
      showDialog(`<h2 id="dialog-title">Company lookup unavailable</h2><p>${e(error.message)}</p>`);
  }
}

function renderAlerts() {
  const alerts = state.data.alerts;
  const unread = alerts.filter((alert) => !alert.read).length;
  const visible = state.alertFilter === "unread" ? alerts.filter((alert) => !alert.read) : alerts;
  const actions = (alert) =>
    `<div class="alert-actions">${alert.filing_id ? `<button type="button" data-filing="${e(alert.filing_id)}">View filing ↗</button>` : `<button type="button" data-alert-company="${e(alert.symbol)}">View market data ↗</button>`}<button type="button" data-alert-id="${e(alert.id)}" data-alert-read="${alert.read ? "false" : "true"}">${alert.read ? "Mark unread" : "Mark read"}</button></div>`;
  $("#content").innerHTML =
    `<div class="section-heading"><div><h2>${unread} unread signals</h2><p>Rules: ±${state.data.settings.price_threshold}% daily price · ${state.data.settings.volume_threshold}× prior 20-session volume.</p></div>${alerts.length ? `<button class="button" id="mark-all" data-alert-read="${unread ? "true" : "false"}">${unread ? "Mark all read" : "Mark all unread"}</button>` : ""}</div><div class="filters"><button class="chip ${state.alertFilter === "all" ? "selected" : ""}" data-alert-filter="all" aria-pressed="${state.alertFilter === "all"}">All</button><button class="chip ${state.alertFilter === "unread" ? "selected" : ""}" data-alert-filter="unread" aria-pressed="${state.alertFilter === "unread"}">Unread (${unread})</button><button class="chip" data-view="settings">Adjust my rules ↗</button><button class="chip" id="notifications">Enable browser notifications</button></div>${visible.length ? visible.map((a) => `<article class="alert-row ${a.read ? "read" : ""}"><div class="alert-icon" aria-hidden="true">${a.kind === "filing" ? "≡" : a.kind === "price" ? "↗" : "▥"}</div><div class="alert-body"><h3>${e(a.title)}</h3>${a.kind !== "filing" && a.detail ? `<p>${e(a.detail)}</p>` : ""}<div class="alert-meta"><span>${e(a.symbol)}</span><span>${e(a.date.slice(0, 10))}</span><span>${a.read ? "READ" : "UNREAD"}</span></div>${networkHint(a.network, a.filing_id)}</div>${actions(a)}</article>`).join("") : empty(state.alertFilter === "unread" ? "You're all caught up." : "Nothing crossed your thresholds.", state.alertFilter === "unread" ? "Choose All to revisit read signals." : "FINN will surface signals here when a refreshed filing or completed trading session matches your rules.")}<p class="tiny-note">Signals are evaluated after ingestion. Browser notifications work while this page is open; scheduled live refresh runs while the server is running. This prototype does not send mobile push notifications when the browser is closed.</p>`;
}
function renderSettings() {
  const s = state.data.settings;
  $("#content").innerHTML =
    `<form id="settings-form"><div class="settings-grid"><section class="panel"><h3>Unusual market moves</h3><p>Watch the latest completed trading session. Volume compares with the previous 20 sessions, excluding today.</p><label class="field">Daily price move (±%)<input type="number" name="price_threshold" min="0.1" max="50" step="0.1" value="${s.price_threshold}" required></label><label class="field">Volume multiple (× average)<input type="number" name="volume_threshold" min="1" max="20" step="0.1" value="${s.volume_threshold}" required></label><h3>Source refresh</h3><p>Automatic polling runs on the server. Public sources may rate-limit requests.</p><label class="field">Refresh interval (minutes)<input type="number" name="poll_minutes" min="5" max="1440" value="${s.poll_minutes}" required></label><label class="check"><input type="checkbox" name="auto_refresh" ${s.auto_refresh ? "checked" : ""}>Automatically refresh live sources</label></section><section class="panel"><h3>Announcements that matter to you</h3><p>Trigger alerts for material filings in these categories. Every category remains available in your digest.</p><div class="checklist">${state.data.categories.map((c) => `<label class="check"><input type="checkbox" name="category" value="${e(c.id)}" ${s.categories.includes(c.id) ? "checked" : ""}>${e(c.label)}</label>`).join("")}</div></section></div><div class="settings-actions"><p>Preferences and read states are saved in this workspace.</p><button class="button primary" type="submit">Save preferences</button></div></form>`;
}
async function filingDetails(identity, useAI = false) {
  const request = ++profileRequest;
  if (!useAI) showDialog(
    '<h2 id="dialog-title">Reading the filing</h2><div class="loading">Opening the original evidence…</div>',
  );
  try {
    const path = `/api/filings/${encodeURIComponent(identity)}`;
    const f = useAI ? await post(`${path}/analyze`, {}) : await api(path);
    if (request !== profileRequest || !$("#detail-dialog").open) return;
    if (f.mode !== "live") throw new Error("Public filing unavailable from this server.");
    const pct = (a, b) =>
      b > 0 && a != null ? signed((a / b - 1) * 100) : "N/M";
    const resultsBlock = f.results
      ? `<h3>Headline results & Margins</h3><p class="section-sub">${e(f.results.unit)} · QoQ and YoY comparisons on positive base. Margin trajectory in basis points (bps).</p>${typeof renderResultsAnalysis === "function" ? renderResultsAnalysis(f.results) : `<div class="table-scroll"><table><thead><tr><th>Metric</th>${f.results.periods.map((p) => `<th>${e(p)}</th>`).join("")}<th>QoQ</th><th>YoY</th></tr></thead><tbody>${f.results.rows.map((r) => `<tr><td>${e(r.metric)}</td><td>${number(r.current)}</td><td>${number(r.previous)}</td><td>${number(r.year_ago)}</td><td>${pct(r.current, r.previous)}</td><td>${pct(r.current, r.year_ago)}</td></tr>`).join("")}</tbody></table></div>`}`
      : "";

    const note = useAI ? $("#filing-note")?.value : undefined;
    showDialog(
      `<div class="filing-meta-top"><span class="tag ticker-tag">${e(f.symbol)}</span><span class="tag category-tag">${e(f.category)}</span><span class="timestamp">${e(time(f.published_at))}</span></div><h2 id="dialog-title">${e(f.title)}</h2><p class="filing-lead">${e(f.summary || f.reason)}</p>${resultsBlock}${f.management ? `<div class="management-card"><h3>${e(f.management.name)}</h3><span class="tag role-tag">${e(f.management.role)}</span><p class="management-bio">${e(f.management.background)}</p></div>` : ""}${f.extraction_note ? `<p class="extraction-note">${useAI && f.cached ? "Cached · " : ""}${e(f.extraction_note)}</p>` : ""}${!useAI && state.data.model_configured && f.evidence?.length ? `<p><button class="button" type="button" data-analyze-filing="${e(f.id)}">Analyze filing with AI</button> <small>May use model credits</small></p>` : ""}${f.evidence?.length ? `<details class="evidence-details" open><summary>Read extracted source evidence (${f.evidence.length} excerpts)</summary>${f.evidence.map((c) => `<h4>Page ${c.page}</h4><div class="source-quote">${highlightNumbers(c.text)}</div>`).join("")}</details>` : ""}<div class="filing-external-link">${external(f.source_url, "Open original filing")}</div>`,
    );
    $("#dialog-content").insertAdjacentHTML("beforeend", networkContext(f.network, f.id) + reviewForm(f));
    if (note !== undefined) $("#filing-note").value = note;
  } catch (error) {
    if (request !== profileRequest || !$("#detail-dialog").open) return;
    if (useAI) return toast(error.message);
    showDialog(
      `<h2 id="dialog-title">Filing unavailable</h2><p>${e(error.message)}</p>`,
    );
  }
}
function citationDetails(id, quote = "") {
  const c = state.report?.citations[id];
  if (!c) return;
  const excerpt = c.text.replace(/\s+/g, " ");
  const needle = quote.trim().replace(/\s+/g, " ");
  const pattern = needle && new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "iu");
  const match = pattern && pattern.exec(excerpt);
  const evidence = match
    ? `${e(excerpt.slice(0, match.index))}<mark class="evidence-quote-hl">${e(match[0])}</mark>${e(excerpt.slice(match.index + match[0].length))}`
    : highlightNumbers(c.text);
  profileRequest++;
  showDialog(
    `<span class="tag">Primary source · p. ${c.page}</span><h2 id="dialog-title">${e(c.title)}</h2><p class="citation-meta">${e(c.kind.replace("_", " "))}</p><div class="source-quote">${evidence}</div><p>${sourcePage(c.url, c.page) || "Source link unavailable."}</p>`,
  );
  if (match) $("#detail-dialog mark")?.scrollIntoView({ block: "nearest" });
}
const glossary = {
  Revenue: "Total sales: money earned from selling goods and services.",
  EBITDA:
    "Earnings before interest, tax, depreciation and amortisation; a rough measure of operating profitability.",
  PBT: "Profit before tax, after costs and interest.",
  PAT: "Profit after tax, also called net profit.",
  Margin: "A profit figure divided by revenue, expressed as a percentage.",
  QoQ: "Quarter-on-quarter: compared with the immediately previous quarter.",
  YoY: "Year-on-year: compared with the same period a year earlier.",
  "Annual report":
    "The company’s annual disclosure with business overview, audited statements, notes and auditor report.",
  "Quarterly results":
    "The company’s quarterly financial statements filed with the exchange.",
  "Concall transcript":
    "A written record of the earnings call: management commentary, guidance and analyst questions.",
  "Investor presentation":
    "Company slides describing strategy, performance and key metrics.",
  "Primary sources":
    "Documents published by the company or filed with the exchange. Research here excludes broker notes, news and outside model knowledge.",
  "Balance sheet":
    "Assets, liabilities and shareholders’ equity at a point in time.",
  "Debt / leverage":
    "Borrowed money, and the extent to which a company relies on it.",
  "Debt-to-equity": "Total debt divided by shareholders’ equity.",
  "Working-capital cycle":
    "Cash tied up in inventory and customer receivables, less supplier payables.",
  "Cash from operations": "Cash generated by core business operations.",
  "Cash conversion":
    "How well accounting profit becomes actual operating cash.",
  "Free cash flow": "Operating cash flow minus capital expenditure.",
  "ROCE / ROE": "Returns on capital employed or shareholders’ equity.",
  "Contingent liabilities":
    "Potential obligations such as disputed taxes or guarantees.",
  "Related-party transactions":
    "Deals with promoters, insiders or their other businesses.",
  "Auditor qualification":
    "A concern flagged by the auditor rather than an unqualified opinion.",
  "NSE / BSE": "India’s National Stock Exchange and Bombay Stock Exchange.",
  Ticker:
    "A stock’s exchange symbol. This prototype uses NSE symbols; Yahoo adds .NS.",
  "Market capitalisation": "Share price multiplied by the number of shares.",
  Promoter: "A controlling shareholder or founding group.",
  Pledging: "Using shares as collateral for a loan.",
  "Material announcement":
    "A disclosure important enough to affect the investment case.",
  Guidance: "Management’s forward expectations, not realised results.",
  Capex: "Spending on long-term assets such as plants or capacity.",
  Dividend: "Cash distributed to shareholders.",
  "Record date": "The cut-off date for eligibility for a corporate action.",
  "Bonus / split":
    "Share-count changes that do not themselves generate cash for investors.",
  Buyback: "The company repurchases its shares.",
  "Rights / QIP / preferential issue":
    "Ways to raise equity from existing holders, institutions or selected investors.",
  EOD: "End-of-day price and volume, after the trading session completes.",
  "Percentage points":
    "The absolute difference between percentages; 12% minus 10% is 2 percentage points.",
};
function showGlossary() {
  showDialog(
    `<h2 id="dialog-title">A little financial fluency.</h2><p>Plain-English definitions adapted from the challenge’s companion reference.</p><dl class="glossary">${Object.entries(
      glossary,
    )
      .map(([k, v]) => `<div><dt>${e(k)}</dt><dd>${e(v)}</dd></div>`)
      .join("")}</dl>`,
  );
}
function exportReport() {
  const r = state.report;
  let text = `# FINN — ${r.name}\n\nPrimary-source research. Verify cited evidence.\n\n${r.engine} · ${r.generated_at}\n`;
  for (const s of r.sections) {
    text += `\n## ${s.title}\n`;
    for (const c of s.claims) {
      const source = r.citations[c.citation];
      text += `\n${c.text}\n\nSource: ${source.title}, page ${source.page}${source.url ? " — " + source.url : ""}\n`;
    }
  }
  text += "\n## Promises vs performance\n";
  for (const c of r.comparisons)
    text += `\n${c.period} — ${c.metric}: ${c.promised} promised, ${c.delivered} delivered. ${c.assessment}. Evidence: ${c.promise_citation}, ${c.actual_citation}.\n`;
  text += `\n${r.comparison_note}\n\n${r.warnings.join("\n")}`;
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `FINN-${r.symbol}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function refresh() {
  const button = $("#refresh-button");
  if (button.disabled) return;
  const mobile = $("#mobile-refresh");
  button.disabled = true;
  mobile.disabled = true;
  mobile.setAttribute("aria-label", "Refreshing sources");
  button.textContent = "↻ Refreshing…";
  try {
    const days =
      state.hours === "custom" && state.start
        ? Math.min(
            90,
            Math.ceil((Date.now() - new Date(state.start)) / 86400000) + 1,
          )
        : Math.max(7, Math.ceil(Number(state.hours) / 24) || 7);
    await post("/api/refresh", { days, mode: "live" });
    await loadData();
    toast("Refresh finished. Check source notices for any coverage gaps.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    mobile.disabled = false;
    mobile.setAttribute("aria-label", "Refresh sources");
    button.textContent = "↻ Refresh sources";
  }
}
document.addEventListener("click", async (event) => {
  const b = event.target.closest("button");
  try {
    if (b?.id === "mobile-tools-button") {
      $("#mobile-theme-name").textContent = document.documentElement.dataset.theme === "dark" ? "Light" : "Dark";
      $("#mobile-tools").showModal();
      return;
    }
    if (b?.closest("#mobile-tools") && b.type !== "submit") {
      $("#mobile-tools").close();
      if (b.dataset.mobileTool === "theme") return toggleTheme();
      if (b.dataset.mobileTool === "glossary") return showGlossary();
    }
    if (await handleDeskClick(event, b) || !b || !state.data) return;
    if (b.dataset.view) setView(b.dataset.view);
    else if (b.dataset.networkPerson) await openNetworkProfile(b.dataset.networkPerson, b.dataset.networkFiling);
    else if (b.dataset.networkSpoken) await logNetworkConversation(b);
    else if (b.dataset.networkQuery) {
      if (b.closest("#detail-dialog")) $("#detail-dialog").close();
      await runNetwork(b.dataset.networkQuery);
    }
    else if (b.dataset.reportView) setReportView(b.dataset.reportView);
    else if (b.id === "workspace-updates") {
      renderSourceStatus();
      render();
      $("#main").focus({ preventScroll: true });
    }
    else if (b.dataset.digestWindow) {
      state.hours = b.dataset.digestWindow;
      await loadDigest();
      if (state.view === "brief") renderBrief();
    }
    else if (b.dataset.alertFilter) {
      state.alertFilter = b.dataset.alertFilter;
      renderAlerts();
    }
    else if (b.dataset.analyzeFiling) {
      if (b.disabled) return;
      b.disabled = true;
      b.textContent = "Analyzing filing…";
      try {
        await filingDetails(b.dataset.analyzeFiling, true);
      } finally {
        b.disabled = false;
        b.textContent = "Analyze filing with AI";
      }
    } else if (b.id === "analyze-research") {
      if ($("#research-form").reportValidity())
        await runResearch($("#research-symbol").value, $("#research-question").value, true);
    } else if (b.id === "research-stock-move") {
      const symbol = $("#research-symbol");
      if (symbol.reportValidity())
        await runResearch(symbol.value, $("#research-question").value, false, "market");
    } else if (b.dataset.filing) await filingDetails(b.dataset.filing);
    else if (b.dataset.research) {
      if (b.closest("#detail-dialog")) $("#detail-dialog").close();
      await runResearch(b.dataset.research);
    }
    else if (b.dataset.citation) {
      const section = state.report?.sections.find((item) => item.title === b.dataset.citationSection);
      citationDetails(b.dataset.citation, section?.claims[0]?.quote);
    }
    else if (b.dataset.comparison !== undefined) {
      const comparison = state.report?.comparisons[Number(b.dataset.comparison)];
      const role = b.dataset.evidenceRole;
      if (comparison) citationDetails(comparison[`${role}_citation`], comparison[`${role}_quote`]);
    }
    else if (b.dataset.alertCompany) {
      setView("portfolio");
      const card = [...document.querySelectorAll("[data-company-card]")].find(
        (item) => item.dataset.companyCard === b.dataset.alertCompany,
      );
      if (card) {
        card.open = true;
        card.querySelector("summary").focus({ preventScroll: true });
        card.scrollIntoView({ block: "center" });
      }
    } else if (b.dataset.alertId) {
      await post("/api/alerts/read", {
        ids: [b.dataset.alertId],
        read: b.dataset.alertRead === "true",
      });
      await loadData();
    } else if (b.dataset.remove) {
      await api(`/api/portfolio/${encodeURIComponent(b.dataset.remove)}`, {
        method: "DELETE",
      });
      await loadData();
      toast("Company removed from your watchlist.");
    } else if (["refresh-button", "mobile-refresh"].includes(b.id)) await refresh();
    else if (b.id === "close-dialog") $("#detail-dialog").close();
    else if (b.id === "glossary-button") showGlossary();
    else if (b.id === "export-report") exportReport();
    else if (b.id === "mark-all") {
      const read = b.dataset.alertRead === "true";
      await post("/api/alerts/read", {
        ids: state.data.alerts.map((a) => a.id),
        read,
      });
      await loadData();
      toast(`All signals marked ${read ? "read" : "unread"}.`);
    } else if (b.id === "add-company")
      showDialog(
        '<h2 id="dialog-title">Add to your portfolio</h2><p>Enter any NSE symbol. FINN checks it against the live price source before adding it.</p><form id="add-form" class="research-form"><label class="field">NSE symbol<input id="add-symbol" placeholder="e.g. HINDUNILVR" maxlength="28" required></label><button class="button primary" type="submit">Add company</button></form>',
      );
    else if (b.id === "notifications") {
      if (!("Notification" in window))
        return toast("Browser notifications are not supported here.");
      const permission = await Notification.requestPermission();
      localStorage.setItem(
        "finn-notify",
        permission === "granted" ? "yes" : "no",
      );
      toast(
        permission === "granted"
          ? "Enabled for new signals while this page is open."
          : "Permission was not granted. In-app alerts remain available.",
      );
    }
  } catch (error) {
    toast(error.message);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "research-question")
    state.researchQuestion = event.target.value;
  if (event.target.id === "research-symbol")
    state.researchSymbol = event.target.value;
  if (event.target.id === "filing-search") {
    state.query = event.target.value;
    renderFilings();
  }
});
document.addEventListener("change", async (event) => {
  try {
    if (event.target.id === "time-window") {
      state.hours = event.target.value;
      await loadDigest();
      if (state.view === "brief") renderBrief();
    } else if (event.target.id === "category-filter") {
      state.category = event.target.value;
      renderFilings();
    }
  } catch (error) {
    toast(error.message);
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (form.method === "dialog") return;
  event.preventDefault();
  try {
    if (form.id === "source-search-form") return await runSourceSearch(form);
    if (form.id === "network-form") return await runNetwork(new FormData(form).get("q"));
    if (form.id === "research-form")
      return await runResearch(
        $("#research-symbol").value,
        $("#research-question").value,
      );
    if (form.id === "settings-form") {
      const f = new FormData(form);
      await post(
        "/api/settings",
        {
          price_threshold: Number(f.get("price_threshold")),
          volume_threshold: Number(f.get("volume_threshold")),
          poll_minutes: Number(f.get("poll_minutes")),
          auto_refresh: f.has("auto_refresh"),
          categories: f.getAll("category"),
        },
        "PUT",
      );
      await loadData();
      toast("Preferences saved. Your rules are active.");
    }
    if (form.id === "window-form") {
      const start = $("#window-start").value,
        end = $("#window-end").value;
      const parsedStart = new Date(start),
        parsedEnd = new Date(end);
      if (parsedStart >= parsedEnd)
        throw new Error("The end must be after the start.");
      state.start = parsedStart.toISOString();
      state.end = parsedEnd.toISOString();
      state.startInput = start;
      state.endInput = end;
      await loadDigest();
      renderBrief();
    }
    if (form.id === "add-form") {
      const button = form.querySelector("button");
      button.disabled = true;
      button.textContent = "Checking symbol…";
      try {
        await post("/api/portfolio", { symbol: $("#add-symbol").value });
        $("#detail-dialog").close();
        await loadData();
        toast("Company added. Refresh to load its live filings.");
      } finally {
        button.disabled = false;
        button.textContent = "Add company";
      }
    }
  } catch (error) {
    toast(error.message);
  }
});
$("#detail-dialog").addEventListener("close", () => {
  $("#dialog-toast").classList.remove("show");
});
$("#detail-dialog").addEventListener("click", (event) => {
  if (event.target === $("#detail-dialog")) {
    const r = event.target.getBoundingClientRect();
    if (
      event.clientX < r.left ||
      event.clientX > r.right ||
      event.clientY < r.top ||
      event.clientY > r.bottom
    )
      event.target.close();
  }
});
$("#today").textContent = new Date().toLocaleDateString("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "long",
  timeZone: "Asia/Kolkata",
});
nav();
loadData()
  .then(() => {
    if (!state.data.updated_at) return refresh();
  })
  .catch((error) => {
    $("#content").innerHTML = empty(
      "Could not reach FINN.",
      error.message + " Check that the Python server is running and reload.",
    );
  });
let polling = false;
async function pollWorkspace() {
  if (
    polling || !state.data ||
    document.hidden ||
    state.researching ||
    document.querySelector("dialog[open]") ||
    $("#refresh-button").disabled
  )
    return;
  const previous = new Set(state.data.alerts.map((a) => a.id));
  const previousAlerts = JSON.stringify(state.data.alerts);
  const previousDigest = JSON.stringify(state.digest?.items);
  const previousRefresh = state.data.updated_at;
  polling = true;
  try {
    await loadData(false);
    const fresh = state.data.alerts.filter(
      (a) => !previous.has(a.id) && !a.read,
    );
    if (
      ["brief", "alerts"].includes(state.view) &&
      (state.data.updated_at !== previousRefresh ||
        JSON.stringify(state.data.alerts) !== previousAlerts ||
        JSON.stringify(state.digest?.items) !== previousDigest)
    ) {
      $("#workspace-updates").hidden = false;
    }
    if (fresh.length) {
      toast(
        `${fresh.length} new signal${fresh.length > 1 ? "s" : ""} in your workspace.`,
      );
      if (
        localStorage.getItem("finn-notify") === "yes" &&
        "Notification" in window &&
        Notification.permission === "granted"
      )
        new Notification("FINN · New signal", { body: fresh[0].title });
    }
  } catch {
    /* A temporary polling error must not erase the current view. */
  } finally {
    polling = false;
  }
}
setInterval(pollWorkspace, 30000);
