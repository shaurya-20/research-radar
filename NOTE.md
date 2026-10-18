# Research Radar: Submission Note

**Live app:** _[add link]_ · **Code:** _[add GitHub link]_

## 1. What I built and why

The brief says the problem isn't access to information. It's that the few items that matter get lost among the many that don't. I built **Research Radar**, a small web app (Python + Streamlit) that does three things with the feed: **clean it, rank it, and make it easy to find and come back to.**

**Screens**

- **Watchlist brief.** Every story about the analyst's watchlist companies in the last *N* days (they type the number), most important first, with a one-line summary per company. This is the screen an analyst would open first thing in the morning. Other companies are left out on purpose: the analyst has already said what they cover.
- **Explore.** Search plus filters (company, sector, tag, priority, source type, date, watchlist only), sorted by relevance, priority or date.
- **Company view.** A profile, a timeline chart of the company's events, every story about it and the macro news that may affect it.
- **Saved.** A reading list with personal notes, downloadable as CSV.

**On every story:** a High / Medium / Low priority label with the exact reasons behind it, the original source document one click away, an **✓ Opened** marker once it has been read (with "Mark as unopened" to undo), any second source that carried the same story, and a ⚠ warning plus link if another report contradicts it.

## 2. One key decision: a transparent, research-based importance score instead of an AI model

I could have asked an LLM to rate each story's importance. I chose a rule-based score for three reasons:

- **Trust.** An analyst won't rely on a ranking they can't question. Every score here shows its reasons, and every weight sits in one file (`config.py`).
- **Consistency.** The same story always gets the same score.
- **Grounding.** Rather than invent weights, I based the structure on how regulators, data vendors and research define "important":

| Source | What it told me |
|---|---|
| **SEBI LODR, Reg. 30 / Schedule III** | India's disclosure law already ranks events. **Para A** events are *deemed material* and must always be disclosed (acquisitions, credit rating revisions, fraud or default, regulatory action, leadership changes). **Para B** events are material only above a size test, the lowest of 2% of turnover, 2% of net worth or 5% of average profit (orders, capacity, launches, tie-ups, disruptions, litigation, approvals). |
| **News-analytics vendors** (RavenPack, LSEG News Analytics, Bloomberg, AlphaSense) | They score news on separate dimensions: what the event is, how relevant it is to an entity, and how new it is. Watchlists and time filters decide what an analyst sees. |
| **Market-reaction research** | Rating *downgrades* move share prices significantly; *upgrades* barely do, and one study puts downgrades at about 14× the effect (Jorion & Zhang 2007; Holthausen & Leftwich 1986). Earnings days draw the most investor attention (Ben-Rephael et al. 2018). Stale, repeated news moves prices less (Tetlock 2011). |
| **Analyst-judgement benchmark** (2026) | Professional analysts label news by newness and importance to valuation. Recycled disclosures get *no* importance. |

**The score** (0–65) adds three things:

| Component | Points |
|---|---|
| **Event materiality** (from the story's tag) | Tier 1 *deemed material*, e.g. earnings, acquisition, regulatory review or inspection, rating downgrade: **50** · Tier 2 *usually material*, e.g. orders and contracts, project delays, approvals, clinical trials, litigation, sector regulation, rating upgrade: **35** · Tier 3 *context*, e.g. capex, launches, partnerships, operating metrics, strategy, industry and macro: **20** · Tier 4 *no change*, e.g. rating reaffirmed: **8** · routine: **0** |
| **Magnitude**: a big number (≥15%, ≥₹500 cr, ≥$250M, ≥20 bps, delay ≥60 days) | **+10** |
| **Source**: exchange filing, results release or rating agency | **+5** |

**High ≥ 55, Medium ≥ 35, otherwise Low.** Of the 235 stories: 43 High, 56 Medium, 126 Low, 10 routine.

Two things I deliberately left out of the score:

- **The watchlist.** An earlier version added points for watchlist companies. That pushed every story in the Watchlist brief into High or Medium, so the label stopped telling the analyst anything. The watchlist now decides *what you see*, and the score decides *how important it is*, the same way for everyone.
- **Recency.** Time is handled by the date filter, the "last N days" box and the "Newest" sort, so a story's importance doesn't change from one day to the next.

**Limits:** the research sets the *order* of the tiers; the exact point values are my calibration, since vendors don't publish theirs. SEBI measures size relative to the company, but the dataset has no financials, so the magnitude thresholds are fixed numbers.

## 3. How I handled the data

The README says the imperfections are intentional, so I treated each one as something to solve explicitly. Nothing is deleted. Every raw file stays linked.

| Issue | What I did |
|---|---|
| Source names with underscores (6) | `MarketWire_India` → `MarketWire India` |
| Aliases as company names (22) | Mapped to the official name using `company_master.csv` ("BluePeak", "VEL", "SRL" …) |
| Missing tickers (7) | Read from the headline (e.g. "Prakash Motion: Wins order…"). I checked every story for mentions of more than one company and found none, so each story has exactly one company. |
| No company (40) | Labelled *Macro* and linked to the industries they plausibly affect (e.g. steel prices → specialty metals; rupee → IT exporters). The mapping is my assumption and sits in `config.py`. |
| **Tags** | Kept the source tags as they are. The 20 untagged stories get an existing tag, marked **(u)**: 10 routine disclosures → `routine/admin`; 8 take the tag used by other stories with the same headline wording; 2 by a keyword rule. All 10 routine items in the dataset were among the untagged ones. |
| **Duplicates** | Merged only where I could **prove** it (below): 15 stories. 250 raw → 235 shown. |
| **Conflicting reports** | Flagged, not resolved. The tool can't know which is right. |
| **Routine disclosures** (10) | Hidden by default (one toggle shows them) |

**Duplicate rule.** A story is a duplicate only if all four hold:

1. Its text declares it is a re-carry ("A second public-market feed carried substantially the same development concerning…").
2. It is about the same company.
3. Its text is character-for-character identical to the original once that sentence and a generic closing sentence are removed.
4. It was published the same day.

Exactly 15 stories carry that sentence, and each matches exactly one original from an official source. The original stays, and the copy is listed under "also reported by".

**What I chose *not* to merge.** 26 other groups share identical wording but are days or months apart. The text contains no date or reference that can separate a re-report from a genuinely new event with the same outcome: two rate-policy meetings that both held rates, a follow-up project update, a continuing trend like "steel prices soften". A wrong merge hides real news, so these stay separate.

**Conflict rule.** Two reports conflict when they concern the same company, appear on the same day, and share the same headline wording but carry different figures. One pair exists: Aranya Bank profit **+23%** vs **+17%** (RF0001 / RF0009). Both carry a ⚠ marker linking to the other, so the analyst checks the primary source.

**Routine disclosures.** I classed a story as routine if it is **procedural or scheduled**, so it carries nothing new: a trading-window closure (required every quarter before results), an AGM notice, a newspaper ad, an investor-meeting schedule, director rotation, an office-address change. Or if it has **no plausible link to earnings, cash flow or risk**: CSR events, awards, certifications.

## 4. Search

Analysts don't type exact headlines, so search is built to tolerate how people actually search:

- **Companies:** recognises company names, tickers and aliases ("SRL" finds Suryanet).
- **Word forms:** reduces words to their root ("grow", "grows" and "growth" match).
- **Typos:** fixes them against words that actually appear in the feed ("revnue" → revenue).
- **Synonyms:** expands common finance terms ("lawsuit" finds litigation).
- **Filler words:** ignores them, so "acquisitions by Synaptix" works.

Results can be sorted by **relevance**: a match in the headline counts more than one in the tag, which counts more than one in the body. Matching every word, matching in headline order, and a story using the exact alias typed all add points. So "revenue grows" and "grow revenue" return the same stories, ranked slightly differently. The app always shows how it read the query.

## 5. What I would improve with more time

- **Context for every number.** Show a metric's history on the card: "Revenue +17% (previous: +14% in Feb, +7% in Jan)". That answers "is this good or bad?" at a glance. For a feed with consistent wording like this one, it can be done by matching headline patterns. For free-form news, an LLM would pull out (company, metric, value, period) into a table first.
- **Size relative to the company.** Add basic financials so "big" means what SEBI means: ₹500 crore is huge for one company and minor for another.
- **Tone.** Mark news as positive or negative. A simple word list misread cases like "attrition falls" (good news), so I left it out rather than ship something unreliable. A finance-specific model or an LLM, checked against analyst labels, would do this properly.
- **AI where it helps.** Short "what changed this quarter" summaries per company, and a second opinion on borderline scores.
- **Link follow-ups to originals.** E.g. connect a project-delay update to the capex approval it refers to.
- **Learn from the analyst.** Use what they save, open or dismiss to tune the weights over time.
- **Live data and alerts.** Ingest exchange filings and news APIs on a schedule; send email or Slack alerts for High-priority watchlist items.
- **Persistence.** Store saved items, notes and opened history per user in a database; on the free hosting they reset when the app restarts.

---

*Sources: SEBI LODR Regulations 2015, Reg. 30 & Schedule III (as amended 2023); RavenPack and LSEG News Analytics product documentation; Jorion & Zhang (2007); Holthausen & Leftwich (1986); Ben-Rephael, Da, Easton & Israelsen (2018), "Who Pays Attention to SEC Form 8-K?"; Tetlock (2011), "All the News That's Fit to Reprint"; "Frontier Financial Judgement" benchmark (arXiv 2607.20645, 2026).*
