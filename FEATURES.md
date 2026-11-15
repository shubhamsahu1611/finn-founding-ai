# FINN features and architecture

## Try the three workflows

| Workflow | What to try |
| --- | --- |
| **Push · Daily brief and alerts** | Open a priority filing from the **Daily brief**, save it or mark it reviewed. Switch to **Last 7 days** if the current window is quiet. Tap **Listen** for a brief that opens with the top finding and adds unusual moves and watchlist breadth when quotes are available. |
| **Pull · Research and quotes** | Enter **INFY** and tap **Check stock move** for the latest completed session. Ask about the stock’s recent pattern to see the closing-price history and, with Gemini enabled, an explanation grounded in that data. For fundamentals, build a source brief, open a cited page, or search an earnings call for “operating margin.” |
| **Network · People who can help** | Search **Who knows Ananya Rao?** to compare a reported collaboration with a possible introduction inferred from overlapping dates. Open a material filing or a company research brief to find sample contacts with relevant experience. |

The **Watchlist** uses compact expandable rows. **Quick Jump** finds Indian listings by name, NSE ticker, BSE scrip code, or ISIN. Search **526941** to open a BSE profile with links to the exchange and quote source.

## How it works

- **Market data and filings.** A FastAPI service refreshes completed Yahoo Finance sessions and NSE announcements into SQLite. Rule-based classification prioritises material filings. The default alerts cover closing moves of at least **3%** in either direction, volume of at least **2×** the preceding **20 trading sessions**, and matching material filings. Upstox instrument directories support NSE and BSE lookup.
- **Research and AI.** Screener is used to discover links. FINN fetches the original annual reports and transcripts from company or exchange sites, extracts page text and retrieves bounded excerpts. Gemini 3.1 Flash-Lite handles requested synthesis, selected filing details, and spoken scripts. Trading questions use dated closing data. Mixed questions receive both trading and document evidence. FINN checks cited quotes against their source text and keeps source-based output available during model failures. The phone browser supplies the speaking voice.
- **Network.** Fictional contact profiles contain roles, tenure and relationships. Matching links company and filing context to those records, with a visible explanation of each connection. SQLite stores the recorded conversation date by contact ID. Network profiles and personal notes stay out of model prompts.
- **Cloud and privacy.** A single Python process serves the responsive HTML, CSS and JavaScript and reads one SQLite database. Render can run the backend with Cloudflare providing HTTPS access. The shared demo is for fictional contacts. A real investor workspace would require consented imports, tenant-scoped access, encrypted storage, deletion controls and a retention policy.

Completed-session quotes support price and volume comparisons. Filing coverage and source dates are visible in the app. Browser notifications require opt-in and an open page. The next production steps would be private workspaces, monitored background ingestion, and stronger tests for financial interpretation across reporting periods.
