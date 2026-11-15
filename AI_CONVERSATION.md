# FINN — AI design conversation

## Daily brief and alerts

**User:** What should FINN cover for the Founding AI Engineer brief?

**Assistant:** Focus on three workflows for Indian equities: scan the day’s important filings and alerts, investigate a company using primary sources, and find a relevant contact. Keep NSE and BSE lookup in scope. Remove the partial U.S. stock flow so the demo stays focused on the assignment.

**User:** How should I adapt the reference design for a phone?

**Assistant:** Keep the compact layout and clear hierarchy. Lead with material filings, collapse routine disclosures, and let the reader open a source, save the item, or mark it reviewed from the filing view.

**User:** What makes a filing material?

**Assistant:** A material filing contains information that could change how an investor assesses the business. Results, a major acquisition, or a CFO resignation can warrant a closer look. FINN prioritises those events and keeps routine disclosures available in the digest.

**User:** What does a 2× volume alert mean?

**Assistant:** Volume is the number of shares traded. A 2× alert means the latest completed session traded at least twice the average volume of the prior 20 sessions. The latest session stays out of its own baseline. Unusual volume signals activity worth checking, and the price change shows the direction.

**User:** How can the audio brief be longer without adding filler?

**Assistant:** Start with the most important filing and one thing to check in it. Then cover unusual price or volume moves, followed by how the rest of the watchlist traded. Skip sections when the data is missing.

## Financial terms and results

**User:** What’s the difference between revenue and profit?

**Assistant:** Revenue is what a business earns from selling goods or services before expenses. Profit is what remains after the expenses included in the measure. Revenue can rise while profit falls if costs grow faster than sales.

**User:** What do EBITDA, PBT, and PAT tell me?

**Assistant:** EBITDA is earnings before interest, taxes, depreciation, and amortisation. PBT is profit before tax, and PAT is profit after tax. The three lines help you see whether a change comes from trading performance, costs such as interest or depreciation, or taxes. Check the company’s definition before comparing EBITDA figures across businesses.

**User:** How do I read a margin change in basis points?

**Assistant:** EBITDA margin is EBITDA divided by revenue, expressed as a percentage. A move from 15% to 16.5% is an increase of 1.5 percentage points, or 150 basis points. FINN shows margin changes in basis points so you can distinguish them from profit growth.

**User:** When should I look at QoQ and YoY?

**Assistant:** Quarter on quarter compares the latest quarter with the one immediately before it. Year on year compares it with the same quarter last year. Use QoQ to see recent momentum and YoY to check a similar seasonal period.

**User:** Why does the results table sometimes show N/M?

**Assistant:** N/M means the growth rate is not meaningful. A move from a ₹10 crore loss to a ₹5 crore profit is a ₹15 crore improvement, but a percentage growth rate based on the loss would be misleading. Read the two amounts directly, and check the source if a period is missing.

**User:** How can a profitable company have weak cash flow?

**Assistant:** Accounting profit can include sales customers haven’t paid for. Compare profit with operating cash flow across several periods to see how consistently profit turns into cash. A common free cash flow measure subtracts capital expenditure from operating cash flow.

**User:** What does working capital tell me?

**Assistant:** In cash flow analysis, look at inventory and customer receivables alongside amounts owed to suppliers. If inventory and receivables grow faster than sales, more cash may be tied up in the business. Check the report notes for seasonality, a deliberate inventory build, or slower collections.

**User:** Can I compare standalone and consolidated results?

**Assistant:** Use the same reporting basis for both periods. Standalone figures cover the parent company. Consolidated figures combine the parent and its subsidiaries as a group and remove transactions within that group. A mismatch can create an apparent jump in growth or margins.

**User:** What should I look for in the auditor’s report?

**Assistant:** Start with the audit opinion and the explanation for any qualification. A qualification flags a specific issue that affects the auditor’s opinion. Separately, read the notes for contingent liabilities, such as a disputed tax claim, and check the possible amount and uncertainty.

## Research and Gemini

**User:** Why did my Airtel stock question return report excerpts?

**Assistant:** “How did Airtel trade today?” needs market data. Use the latest completed session and show its date, price change, and volume. Questions about the business need filings or transcripts. For a mixed question, show both kinds of evidence and avoid assigning a cause to a price move without support.

**User:** Which source should I open for a research claim?

**Assistant:** Use the annual report for audited figures and notes, the exchange filing for quarterly results or a corporate event, and the earnings call transcript for what management said. FINN uses Screener to discover report and transcript links, then reads the original company or exchange documents.

**User:** Can I find where management discussed margins without Gemini?

**Assistant:** Yes. Search for “operating margin” in the earnings call source search. FINN shows matching passages from available transcripts and links to the relevant page, so you can read the surrounding remarks yourself.

**User:** How can research go beyond matching similar sentences?

**Assistant:** Use excerpts as evidence for a specific comparison. For example, compare management’s margin guidance with the reported result only when the metric, period, and basis match. Link the relevant pages and say what’s missing when the comparison can’t be made.

**User:** If a citation is valid, is the whole answer reliable?

**Assistant:** A valid citation shows where the quoted text came from. Check that the passage also supports the conclusion. For example, a quote about annual consolidated margins cannot establish that standalone margins rose in the latest quarter.

**User:** Where does Gemini add enough value to call it?

**Assistant:** Use it for requested synthesis, such as explaining a recent trading pattern or connecting related disclosures. Keep price calculations, filing priorities, and alert thresholds rule based. Reuse cached analysis for the same evidence and keep source excerpts available if Gemini fails.

## Network

**User:** How should FINN explain a possible introduction to an incoming CFO?

**Assistant:** Show the reason beside each suggested contact. In the fictional demo, a reported collaboration is stronger evidence than overlapping years at the same employer or school. Label an overlap as a possible introduction and keep fictional profiles separate from real executives.

**User:** If several contacts know a company, who should I call first?

**Assistant:** Match the contact’s experience to the question. A former employee might help explain how a division operates, and a supplier might help you understand the purchasing cycle. FINN shows why each fictional contact was suggested so you can choose.

**User:** What changes when I log a conversation?

**Assistant:** FINN saves the conversation date and uses it when suggesting who to reconnect with. Company research keeps its original citations. Personal notes and contact profiles stay outside Gemini prompts.

## Demo checks

**User:** What should FINN show if it can’t refresh stock prices?

**Assistant:** If a saved quote is available, show the session date and label it as saved. If there’s no usable quote, show that it’s unavailable. A dated close gives the reader enough context to decide whether it answers their question.

**User:** How can I check that company lookup goes beyond the watchlist?

**Assistant:** Search for an Indian listing that isn’t on the watchlist. Try a company name or NSE symbol, then try a BSE scrip code in Quick Jump. Open the profile and confirm that it points to the intended listing.

**User:** Which edge cases should I check before the demo?

**Assistant:** Try a stock question before the market closes, a question that needs both quotes and filings, and a model failure. Check that FINN dates the completed quote, shows both sources when needed, and still provides usable evidence if Gemini is unavailable.
