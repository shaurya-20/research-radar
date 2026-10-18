"""
Data pipeline for the Research Radar app.

Raw feed  ->  clean  ->  enrich (event type, key numbers, macro links)
          ->  de-duplicate  ->  score (priority + reasons)

Everything here is plain, rule-based Python so that an analyst can see
exactly why an item was ranked the way it was. All rules live in
config.py so they can be tuned without touching this logic.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

import config as C

DATA_DIR = Path(__file__).parent / "data"


# ----------------------------------------------------------------------------
# 1. Load
# ----------------------------------------------------------------------------
def load_raw(data_dir: Path = DATA_DIR):
    feed = pd.read_csv(data_dir / "research_feed.csv", encoding="utf-8-sig", dtype=str).fillna("")
    companies = pd.read_csv(data_dir / "company_master.csv", encoding="utf-8-sig", dtype=str).fillna("")
    watchlist = pd.read_csv(data_dir / "watchlist.csv", encoding="utf-8-sig", dtype=str).fillna("")
    return feed, companies, watchlist


# ----------------------------------------------------------------------------
# 2. Clean
# ----------------------------------------------------------------------------
def _alias_lookup(companies: pd.DataFrame) -> dict[str, str]:
    """Map every known name / alias / ticker (lower-case) -> ticker."""
    lookup = {}
    for _, row in companies.iterrows():
        names = [row["company"], row["ticker"]] + [a.strip() for a in row["aliases"].split(";")]
        for n in names:
            if n:
                lookup[n.lower()] = row["ticker"]
    return lookup


def _headline_subject(headline: str) -> tuple[str, str]:
    """Split 'Company: event' or 'Company - event' into (company_part, event_part)."""
    m = re.match(r"^(.{2,60}?)(?::\s| - )(.*)$", headline)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", headline.strip()


def clean(feed: pd.DataFrame, companies: pd.DataFrame, log: list) -> pd.DataFrame:
    df = feed.copy()
    df["company_raw"] = df["company"]  # keep the name exactly as the source wrote it
    lookup = _alias_lookup(companies)
    by_ticker = companies.set_index("ticker")

    # Dates
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")

    # Source names: 'MarketWire_India' -> 'MarketWire India'
    fixed = df["source_name"].str.contains("_").sum()
    df["source_name"] = df["source_name"].str.replace("_", " ").str.strip()
    log.append(("Standardised source names", f"{fixed} items used underscores (e.g. MarketWire_India)"))

    # Resolve company from ticker -> company field -> headline prefix
    subj = df["headline"].apply(_headline_subject)
    df["subject"] = subj.str[0]
    df["event_text"] = subj.str[1]

    inferred, renamed = 0, 0
    tickers = []
    for _, r in df.iterrows():
        t = r["ticker"]
        if not t:
            t = lookup.get(r["company"].lower(), "") or lookup.get(r["subject"].lower(), "")
            if t:
                inferred += 1
        tickers.append(t)
    df["ticker"] = tickers
    for i, r in df.iterrows():
        if r["ticker"]:
            canon = by_ticker.loc[r["ticker"]]
            if r["company"] != canon["company"]:
                renamed += 1
            df.at[i, "company"] = canon["company"]
            df.at[i, "sector"] = canon["sector"]
            df.at[i, "industry"] = canon["industry"]
    log.append(("Mapped aliases to official company names", f"{renamed} items used a short name / alias (e.g. 'BluePeak', 'Vardhan Engg')"))
    log.append(("Filled missing tickers from the headline", f"{inferred} company items had no ticker (e.g. 'Prakash Motion: Wins order...')"))

    # Items with no company are market / macro news
    df["is_macro"] = df["ticker"] == ""
    missing_sector = ((df["sector"] == "") & df["is_macro"]).sum()
    df.loc[df["is_macro"], "sector"] = "Macro"
    df.loc[df["is_macro"], "company"] = ""
    log.append(("Labelled market-wide items as Macro", f"{int(df['is_macro'].sum())} items have no company; {missing_sector} also had a blank sector"))

    return df


# ----------------------------------------------------------------------------
# 3. Enrich
# ----------------------------------------------------------------------------
def _template(event_text: str) -> str:
    """Headline wording with numbers removed, to find stories of the same kind."""
    t = re.sub(r"[\d.,]+", "#", event_text.lower())
    return re.sub(r"[^a-z# ]", "", t).strip()


def assign_tags(df: pd.DataFrame, log: list) -> pd.DataFrame:
    """Keep the source tag. Give untagged stories an existing tag, marked as such."""
    df = df.copy()
    df["tag"] = df["tags"].str.strip()
    df["tag_untagged"] = df["tag"] == ""
    df["_tpl"] = df["event_text"].apply(_template)
    tagged = df[~df["tag_untagged"]]
    by_template = tagged.groupby("_tpl")["tag"].agg(lambda s: s.value_counts().index[0]).to_dict()

    how = {"routine": 0, "same wording": 0, "keyword": 0}
    for i in df[df["tag_untagged"]].index:
        h = df.at[i, "headline"].lower()
        if any(re.search(p, h) for p in C.ROUTINE_PATTERNS):
            df.at[i, "tag"] = C.ROUTINE_TAG
            how["routine"] += 1
        elif df.at[i, "_tpl"] in by_template:
            df.at[i, "tag"] = by_template[df.at[i, "_tpl"]]
            how["same wording"] += 1
        else:
            for pattern, tag in C.UNTAGGED_KEYWORD_FALLBACK:
                if re.search(pattern, h):
                    df.at[i, "tag"] = tag
                    how["keyword"] += 1
                    break
    df["event_type"] = df["tag"] + df["tag_untagged"].map({True: " (u)", False: ""})
    log.append(("Tagged untagged stories", f"{int(df['tag_untagged'].sum())} untagged: {how['routine']} routine, {how['same wording']} from stories with the same wording, {how['keyword']} by keyword"))
    return df.drop(columns="_tpl")


def tier_of(tag: str, headline: str) -> int:
    if tag == "credit rating":
        h = headline.lower()
        if any(re.search(p, h) for p in C.RATING_DOWNGRADE):
            return 1
        if any(re.search(p, h) for p in C.RATING_UPGRADE):
            return 2
        return 4
    return C.TAG_TIER.get(tag, 3)


def extract_magnitude(text: str) -> list[str]:
    """Pull out the numbers that make an event big or small."""
    flags = []
    for p in re.findall(r"(\d+(?:\.\d+)?)\s?%", text):
        if float(p) >= C.BIG_PERCENT:
            flags.append(f"{p}% move")
            break
    for v in re.findall(r"₹\s?([\d,]+)\s?crore", text):
        if float(v.replace(",", "")) >= C.BIG_CRORE:
            flags.append(f"₹{v} crore")
            break
    for v in re.findall(r"\$\s?([\d,]+)\s?million", text):
        if float(v.replace(",", "")) >= C.BIG_USD_MN:
            flags.append(f"${v} million")
            break
    for v in re.findall(r"(\d+)\s?bps", text):
        if float(v) >= C.BIG_BPS:
            flags.append(f"{v} bps")
            break
    for v in re.findall(r"(\d+)\s?(weeks|days)", text):
        n = int(v[0]) * (7 if v[1] == "weeks" else 1)
        if n >= C.BIG_DELAY_DAYS:
            flags.append(f"{v[0]} {v[1]}")
            break
    return flags


def macro_links(row, companies: pd.DataFrame) -> list[str]:
    """Which companies does a macro item plausibly affect? (analyst-defined map)"""
    industries = C.MACRO_IMPACT.get(row["industry"], [])
    return companies.loc[companies["industry"].isin(industries), "ticker"].tolist()


def enrich(df: pd.DataFrame, companies: pd.DataFrame, log: list) -> pd.DataFrame:
    df = df.copy()
    text = df["headline"] + " " + df["content"]
    df["magnitude"] = text.apply(extract_magnitude)
    df["source_tier"] = df["source_name"].apply(lambda s: C.SOURCE_TIER.get(s, "Secondary"))
    df["is_follow_up"] = df["headline"].str.contains(r"previously announced|follow-up", case=False)
    df["affects"] = df.apply(lambda r: macro_links(r, companies) if r["is_macro"] else [r["ticker"]], axis=1)
    log.append(("Linked macro items to affected companies", "e.g. steel-price news -> specialty metals; rupee moves -> IT exporters (see config.MACRO_IMPACT)"))
    return df


# ----------------------------------------------------------------------------
# 4. De-duplicate
# ----------------------------------------------------------------------------
def dedupe(df: pd.DataFrame, log: list) -> pd.DataFrame:
    """
    Merge only PROVABLE duplicates. A story is a duplicate of another if all hold:
      1. it declares itself a re-carry ("A second public-market feed carried
         substantially the same development concerning ...")
      2. same company
      3. identical text once that opening sentence and the generic closing
         sentence are removed
      4. published the same day
    The original (the story without the re-carry sentence) is kept and lists the
    copy under "also reported by". Same-wording stories on different days are
    NOT merged: the text alone cannot prove they are the same event.
    """
    df = df.copy()
    df["is_duplicate"] = False
    df["duplicate_of"] = ""
    df["also_reported_by"] = [[] for _ in range(len(df))]

    def core(text: str) -> str:
        text = re.sub(C.RECARRY_PATTERN, "", text)
        return text.replace(C.BOILERPLATE, "").strip()

    cores = df["content"].map(core)
    days = df["published_at"].dt.date
    copies = df[df["content"].str.contains(C.RECARRY_PATTERN, regex=True)]
    n_dup = 0
    for i, c in copies.iterrows():
        match = df[
            (df.index != i)
            & (df["ticker"] == c["ticker"])
            & (cores == cores[i])
            & (days == days[i])
            & ~df["content"].str.contains(C.RECARRY_PATTERN, regex=True)
        ]
        if len(match) == 1:
            o = match.index[0]
            df.at[i, "is_duplicate"] = True
            df.at[i, "duplicate_of"] = df.at[o, "record_id"]
            df.at[o, "also_reported_by"] = df.at[o, "also_reported_by"] + [f"{c['source_name']} ({c['record_id']})"]
            n_dup += 1
    log.append(("Merged provable duplicates", f"{n_dup} of {len(copies)} self-declared re-carries matched exactly one same-day original"))
    return df


def find_conflicts(df: pd.DataFrame, log: list) -> pd.DataFrame:
    """
    Flag reports that contradict each other: same company, same day, same kind of
    headline, but different figures (e.g. profit +23% vs +17%). Duplicates are ignored.
    """
    df = df.copy()
    df["conflicts_with"] = [[] for _ in range(len(df))]
    live = df[~df["is_duplicate"] & ~df["is_macro"]]
    keys = live["event_text"].map(_template)
    nums = live["event_text"].map(lambda t: tuple(re.findall(r"[\d.]+", t)))
    groups = live.assign(_k=keys, _n=nums, _d=live["published_at"].dt.date).groupby(["ticker", "_d", "_k"])
    n = 0
    for _, g in groups:
        if len(g) > 1 and g["_n"].nunique() > 1:
            for i in g.index:
                df.at[i, "conflicts_with"] = [df.at[j, "record_id"] for j in g.index if j != i]
                n += 1
    log.append(("Flagged conflicting reports", f"{n} stories contradict another report on the same day"))
    return df


# ----------------------------------------------------------------------------
# 5. Score
# ----------------------------------------------------------------------------
def score(df: pd.DataFrame, watchlist: set[str], as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """
    Importance = event materiality + magnitude + source.
    The watchlist is NOT part of the score: it decides which stories you see
    (Watchlist brief, "Watchlist only" filter), not how important an event is.
    """
    df = df.copy()
    scores, reasons_all, tiers = [], [], []
    for _, r in df.iterrows():
        tier = tier_of(r["tag"], r["headline"])
        tiers.append(tier)
        if tier == 0:
            scores.append(0)
            reasons_all.append(["Routine disclosure - procedural, no new information about the business"])
            continue

        s = C.TIER_POINTS[tier]
        reasons = [f"{r['tag']}: {C.TIER_LABEL[tier]} (+{s})"]

        if r["magnitude"]:
            s += C.W_MAGNITUDE
            reasons.append(f"Large number: {', '.join(r['magnitude'])} (+{C.W_MAGNITUDE})")

        if r["source_tier"] in ("Primary", "Rating agency"):
            s += C.W_PRIMARY_SOURCE
            reasons.append(f"Official source (+{C.W_PRIMARY_SOURCE})")

        if r["is_follow_up"]:
            reasons.append("Follow-up to an earlier update - see history")

        scores.append(min(100, s))
        reasons_all.append(reasons)

    df["tier"] = tiers
    df["score"] = scores
    df["reasons"] = reasons_all
    df["priority"] = pd.cut(
        df["score"], bins=[-1, 0, C.MEDIUM_FROM - 1, C.HIGH_FROM - 1, 101],
        labels=["Routine", "Low", "Medium", "High"],
    ).astype(str)
    return df


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------
def build(data_dir: Path = DATA_DIR):
    """Run the whole pipeline once. Scoring is done separately (depends on user settings)."""
    feed, companies, watchlist = load_raw(data_dir)
    log: list[tuple[str, str]] = [("Loaded raw feed", f"{len(feed)} items, {len(companies)} companies, {len(watchlist)} on watchlist")]
    df = clean(feed, companies, log)
    df = enrich(df, companies, log)
    df = assign_tags(df, log)
    df = dedupe(df, log)
    df = find_conflicts(df, log)
    routine = ((df["tag"] == C.ROUTINE_TAG) & ~df["is_duplicate"]).sum()
    log.append(("Identified routine / admin noise", f"{routine} items (trading window, AGM notice, awards, CSR...) are kept but hidden by default"))
    unique = (~df["is_duplicate"]).sum()
    log.append(("Result", f"{len(df)} raw items -> {unique} unique stories, {unique - routine} of them substantive"))
    return df, companies, watchlist, log


def read_source(data_dir: Path, source_path: str) -> str:
    p = data_dir / source_path
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "(Source document not found)"
