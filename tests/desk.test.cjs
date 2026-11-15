// Test filtering independently of the DOM so focus never hides a missing signal by accident.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const context = vm.createContext({
  document: { addEventListener() {} },
  e: (value) => String(value),
  number: (value) => String(value),
});
vm.runInContext(fs.readFileSync("static/desk.js", "utf8"), context);
const select = (items, options, reviews = {}) =>
  JSON.parse(
    JSON.stringify(
      context.briefSelection(
        items,
        {
          category: "all",
          symbol: "",
          query: "",
          queue: "all",
          ...options,
        },
        reviews,
      ),
    ),
  );
const items = [
  {
    id: "a",
    symbol: "TCS",
    priority: 90,
    category: "results",
    title: "Results",
  },
  {
    id: "b",
    symbol: "INFY",
    priority: 85,
    category: "management_change",
    title: "CFO appointment",
  },
  {
    id: "c",
    symbol: "TCS",
    priority: 75,
    category: "capex",
    title: "Plant expansion",
  },
  {
    id: "d",
    symbol: "LT",
    priority: 60,
    category: "dividend",
    title: "Dividend",
  },
  {
    id: "e",
    symbol: "TCS",
    priority: 15,
    category: "unclassified",
    title: "Compliance",
  },
];
test("focus advances past reviewed filings and excludes routine paperwork", () => {
  assert.deepEqual(
    select(items, { queue: "focus" }, { a: { reviewed: true } }).map(
      (f) => f.id,
    ),
    ["b", "c", "d"],
  );
});
test("saving and reviewing are independent and compound filters still apply", () => {
  assert.deepEqual(
    select(
      items,
      { queue: "saved", symbol: "TCS" },
      { a: { saved: true, reviewed: true }, b: { saved: true } },
    ).map((f) => f.id),
    ["a"],
  );
  assert.deepEqual(
    select(
      items,
      { queue: "unreviewed", query: "cfo" },
      { a: { reviewed: true } },
    ).map((f) => f.id),
    ["b"],
  );
});
test("all filings remain reachable when the queue is complete", () => {
  const reviews = Object.fromEntries(
    items.map((f) => [f.id, { reviewed: true }]),
  );
  assert.equal(select(items, { queue: "focus" }, reviews).length, 0);
  assert.equal(select(items, { queue: "all" }, reviews).length, items.length);
});

test("desk questions map to existing data views without inventing an answer", () => {
  const portfolio = [
    { symbol: "TCS", name: "Tata Consultancy Services" },
    { symbol: "M&M", name: "Mahindra & Mahindra" },
  ];
  const parse = (question) =>
    JSON.parse(JSON.stringify(context.parseDeskQuestion(question, portfolio)));
  assert.deepEqual(parse("Show me filings for TCS this week"), {
    type: "filings",
    symbol: "TCS",
    hours: "168",
    category: "all",
  });
  assert.equal(parse("Which company had the biggest price move?").type, "move");
  assert.equal(parse("Show unread alerts").type, "alerts");
  assert.equal(parse("Give me a guaranteed winner").type, "unsupported");
});

test("result bars show reported nonnegative periods and skip incomplete metrics", () => {
  const html = context.resultBars({
    unit: "₹ crore",
    periods: ["Q2 FY27", "Q1 FY27", "Q2 FY26"],
    rows: [
      { metric: "Revenue", current: 120, previous: 110, year_ago: 100 },
      { metric: "PAT", current: 10, previous: null, year_ago: 8 },
    ],
  });
  assert.match(html, /Revenue/);
  assert.match(html, /Q2 FY26/);
  assert.doesNotMatch(html, /PAT|NaN/);
});

test("ticker links use the quote source and fall back to encoded NSE symbols", () => {
  const tape = {};
  context.document.getElementById = () => tape;
  context.safeURL = (url) => url;
  context.state = {
    mode: "live",
    data: {
      portfolio: [{ symbol: "TCS" }, { symbol: "M&M" }, { symbol: "RELIANCE" }],
      prices: {
        TCS: { close: 2442, source: "Yahoo Finance · NSE", source_url: "https://finance.yahoo.com/quote/TCS.NS/history/" },
        "M&M": { close: 1339.699951171875, date: "2026-11-12", source: "Yahoo Finance · NSE" },
        RELIANCE: { close: 3064.24, date: "2026-11-13", source: "Synthetic demo" },
      },
    },
  };
  context.renderMarketTape();
  assert.match(tape.innerHTML, /href="https:\/\/finance\.yahoo\.com\/quote\/TCS\.NS\/history\/" target="_blank"/);
  assert.match(tape.innerHTML, /href="https:\/\/finance\.yahoo\.com\/quote\/M%26M\.NS\/" target="_blank"/);
  assert.match(tape.innerHTML, /Closing price · 2026-11-12/);
  assert.match(tape.innerHTML, /₹1,339\.70/);
  assert.doesNotMatch(tape.innerHTML, /3,064\.24|Latest session 2026-11-13/);
  assert.doesNotMatch(tape.innerHTML, /<button/);

});

test("a reported loss has a negative bar and a visible zero line", () => {
  const html = context.resultBars({
    periods: ["Current", "Previous", "Year ago"],
    unit: "INR crore",
    rows: [{ metric: "PAT", current: -12.5, previous: 25, year_ago: 0 }],
  });
  assert.match(html, /class="result-bar-fill loss"/);
  assert.match(html, /class="result-bar-zero"/);
  assert.match(html, />-12\.5</);
  assert.doesNotMatch(html, /style=/);
});

test("empty Network matches do not break the filing renderer", () => {
  vm.runInContext(fs.readFileSync("static/network.js", "utf8"), context);
  assert.equal(context.networkHint({ matches: [] }, "f1"), "");
  assert.equal(context.networkContext({ matches: [] }, "f1"), "");
});
