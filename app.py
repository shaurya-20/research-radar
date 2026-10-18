"""
Research Radar - a lightweight research intelligence tool.

Run locally:   streamlit run app.py
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import config as C
import pipeline as P
from search import SearchIndex

st.set_page_config(page_title="Research Radar", page_icon="📡", layout="wide")

SAVED_FILE = Path(__file__).parent / "saved_items.json"
READ_FILE = Path(__file__).parent / "opened_items.json"
PRIORITY_ORDER = ["High", "Medium", "Low", "Routine"]
BADGE = {
    "High": ("#d64545", "rgba(214,69,69,0.14)"),
    "Medium": ("#c27c0e", "rgba(194,124,14,0.14)"),
    "Low": ("#5b6b7a", "rgba(91,107,122,0.14)"),
    "Routine": ("#8a8f96", "rgba(138,143,150,0.10)"),
}

st.markdown(
    """
    <style>
      .badge {display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;margin-right:6px}
      .meta {color:var(--text-color);opacity:0.65;font-size:0.82rem}
      .headline {font-size:1.02rem;font-weight:600;margin:2px 0 2px 0}
      .why {font-size:0.8rem;opacity:0.75}
      div[data-testid="stMetricValue"] {font-size:1.6rem}
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# Data (cached: the pipeline runs once, scoring re-runs when settings change)
# ----------------------------------------------------------------------------
@st.cache_data
def load():
    return P.build()


@st.cache_resource
def search_index(_df, _companies, cache_key: int):
    return SearchIndex(_df, _companies)


@st.cache_data
def scored(_df, watch: tuple, as_of: pd.Timestamp, cache_key: int):
    return P.score(_df, set(watch), as_of)


base, companies, watchlist_df, cleaning_log = load()
alias_text = {
    r["ticker"]: f"{r['company']} {r['ticker']} {r['aliases'].replace(';', ' ')}".lower()
    for _, r in companies.iterrows()
}
ticker_name = dict(zip(companies["ticker"], companies["company"]))


# ----------------------------------------------------------------------------
# Saved items (simple JSON file so the reading list survives restarts)
# ----------------------------------------------------------------------------
def load_saved() -> dict:
    try:
        return json.loads(SAVED_FILE.read_text())
    except Exception:
        return {}


def write_saved(saved: dict):
    try:
        SAVED_FILE.write_text(json.dumps(saved, indent=2))
    except Exception:
        pass  # read-only hosting: keep it in session only


if "saved" not in st.session_state:
    st.session_state.saved = load_saved()


# Opened stories: a story counts as opened once its source is expanded
def load_opened() -> dict:
    try:
        return json.loads(READ_FILE.read_text())
    except Exception:
        return {}


def _write_opened():
    try:
        READ_FILE.write_text(json.dumps(st.session_state.opened, indent=2))
    except Exception:
        pass


def mark_opened(rid: str, widget_key: str):
    # Fires when the source panel is toggled; only count it when it is being opened
    if st.session_state.get(widget_key) and rid not in st.session_state.opened:
        st.session_state.opened[rid] = str(pd.Timestamp.now().floor("s"))
        _write_opened()


def mark_unopened(rid: str):
    st.session_state.opened.pop(rid, None)
    _write_opened()


if "opened" not in st.session_state:
    st.session_state.opened = load_opened()


# ----------------------------------------------------------------------------
# Sidebar: settings that change what "important" means
# ----------------------------------------------------------------------------
with st.sidebar:
    st.title("📡 Research Radar")
    st.caption("Find, filter and prioritise research news.")

    latest = base["published_at"].max()
    as_of = pd.Timestamp(
        st.date_input("As of date", value=latest.date(), help="The dataset is a snapshot ending on this date. Periods like 'last 30 days' count back from here.")
    )

    watch = st.multiselect(
        "My watchlist",
        options=companies["ticker"].tolist(),
        default=watchlist_df["ticker"].tolist(),
        help="Defaults to watchlist.csv. Used to filter (Watchlist brief, Watchlist only); it does not change priority.",
    )

    st.divider()
    st.caption("**Tag (u)** = the story had no tag in the source data; the tag was assigned by this tool.")
    hide_routine = st.toggle("Hide routine disclosures", value=True, help="Trading window, AGM notices, awards, CSR etc.")

    with st.expander("How is priority calculated?"):
        st.markdown(
            f"""
Score = **what happened** + **how big** + **who says so**. Your watchlist decides what you see, not the priority.

**1. Event materiality** (based on SEBI's disclosure rules and market-reaction research)
- Tier 1 · deemed material: earnings, acquisition, regulatory review / inspection, rating downgrade → **+{C.TIER_POINTS[1]}**
- Tier 2 · usually material: order / deal win, contract, project delay / update, approvals, clinical trial, litigation, regulation, rating upgrade → **+{C.TIER_POINTS[2]}**
- Tier 3 · context: capex, launches, partnerships, operating metrics, strategy, cost pressure, industry & macro → **+{C.TIER_POINTS[3]}**
- Tier 4 · no change: rating reaffirmed → **+{C.TIER_POINTS[4]}**
- routine/admin → **0**

**2. Magnitude:** a big number (≥{C.BIG_PERCENT}%, ≥₹{C.BIG_CRORE} cr, ≥${C.BIG_USD_MN}M, ≥{C.BIG_BPS} bps, delay ≥{C.BIG_DELAY_DAYS} days) **+{C.W_MAGNITUDE}**

**3. Source:** official filing or rating agency **+{C.W_PRIMARY_SOURCE}**

**High** ≥ {C.HIGH_FROM} · **Medium** ≥ {C.MEDIUM_FROM} · otherwise **Low**.
Every story shows its exact reasons. All weights live in `config.py`.
""".replace("$", "\\$")
        )

df = scored(base, tuple(sorted(watch)), as_of, len(base))
df = df[df["published_at"] <= as_of + timedelta(days=1)]
view = df[~df["is_duplicate"]].copy()  # provable re-carries are merged into their original
if hide_routine:
    view = view[view["priority"] != "Routine"]


# ----------------------------------------------------------------------------
# Rendering helpers
# ----------------------------------------------------------------------------
def esc(s: str) -> str:
    """Stop Streamlit reading '$480 million ... $2200' as a LaTeX formula."""
    return str(s).replace("$", "\\$")


def badge(priority: str) -> str:
    fg, bg = BADGE[priority]
    return f'<span class="badge" style="color:{fg};background:{bg}">{priority}</span>'


def related_items(r, n=6) -> pd.DataFrame:
    if r["is_macro"]:
        rel = df[(df["is_macro"]) & (df["industry"] == r["industry"])]
    else:
        rel = df[df["ticker"] == r["ticker"]]
    rel = rel[(rel["record_id"] != r["record_id"]) & (~rel["is_duplicate"])]
    return rel.sort_values("published_at", ascending=False).head(n)


def item_card(r, key: str):
    with st.container(border=True):
        who = f"{ticker_name.get(r['ticker'], '')} ({r['ticker']})" if r["ticker"] else "Macro · " + r["industry"]
        star = " ⭐" if r["ticker"] in watch else ""
        is_opened = r["record_id"] in st.session_state.opened
        body, side = st.columns([6, 1], vertical_alignment="top")
        if is_opened:
            side.button("Mark as unopened", key=f"unopen_{key}", on_click=mark_unopened,
                        args=(r["record_id"],), type="tertiary", width="stretch")
        body.markdown(
            f"{badge(r['priority'])}"
            + ("<span class='badge' style='color:#5b6b7a;background:rgba(91,107,122,0.12)'>✓ Opened</span>"
               if r["record_id"] in st.session_state.opened else "")
            + f"<span class='meta'>{r['published_at']:%d %b %Y} · {who}{star} · "
            f"Tag: {r['event_type']} · {r['source_name']}</span>"
            f"<div class='headline'>{esc(r['headline'])}</div>"
            f"<div class='why'>Why: {esc(' · '.join(r['reasons']))}"
            + (f" &nbsp;|&nbsp; Search match: {r['relevance']:g}" if r.get("relevance", 0) else "")
            + "</div>",
            unsafe_allow_html=True,
        )
        if r["conflicts_with"]:
            links = ", ".join(f'<a href="?story={x}" target="_self">{x}</a>' for x in r["conflicts_with"])
            st.markdown(
                f"<div style='color:#c27c0e;font-size:0.85rem;font-weight:600'>⚠ Report conflicting with {links}</div>",
                unsafe_allow_html=True,
            )
        if r["is_macro"] and r["affects"]:
            st.caption("May affect: " + ", ".join(t + (" ⭐" if t in watch else "") for t in r["affects"]))
        with st.expander("Open source & context", key=f"x_{key}", on_change=mark_opened, args=(r["record_id"], f"x_{key}")):
            st.text(P.read_source(P.DATA_DIR, r["source_path"]))
            st.caption(f"Source file: `{r['source_path']}` · Source type: {r['source_type']} ({r['source_tier']})")
            if r["also_reported_by"]:
                st.markdown("**Also reported by:** " + ", ".join(r["also_reported_by"]))
            rel = related_items(r)
            if len(rel):
                st.markdown("**Recent history for this " + ("theme" if r["is_macro"] else "company") + ":**")
                for _, x in rel.iterrows():
                    st.markdown(f"- {x['published_at']:%d %b %Y} · {badge(x['priority'])} {esc(x['headline'])}", unsafe_allow_html=True)
            saved = st.session_state.saved
            rid = r["record_id"]
            if rid in saved:
                note = st.text_input("Note", value=saved[rid].get("note", ""), key=f"note_{key}")
                c1, c2 = st.columns(2)
                if c1.button("Update note", key=f"upd_{key}"):
                    saved[rid]["note"] = note
                    write_saved(saved)
                    st.toast("Note saved")
                if c2.button("Remove from saved", key=f"rm_{key}"):
                    saved.pop(rid)
                    write_saved(saved)
                    st.rerun()
            else:
                note = st.text_input("Add a note (optional)", key=f"note_{key}", placeholder="e.g. check impact on FY27 margins")
                if st.button("⭐ Save for later", key=f"save_{key}"):
                    saved[rid] = {"note": note, "saved_on": str(pd.Timestamp.now().date())}
                    write_saved(saved)
                    st.toast("Saved to your reading list")
                    st.rerun()


def sort_feed(d: pd.DataFrame, by="Priority") -> pd.DataFrame:
    if by == "Relevance" and "relevance" in d:
        return d.sort_values(["relevance", "score", "published_at"], ascending=False)
    if by == "Newest":
        return d.sort_values("published_at", ascending=False)
    return d.sort_values(["score", "published_at"], ascending=False)


# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------
opened = st.query_params.get("story")
if opened:
    hit = df[df["record_id"] == opened]
    if len(hit):
        h1, h2 = st.columns([5, 1])
        h1.markdown(f"##### Opened story {opened}")
        if h2.button("Close", key="close_story"):
            st.query_params.clear()
            st.rerun()
        item_card(hit.iloc[0], f"open_{opened}")
        st.divider()

tab_brief, tab_explore, tab_company, tab_saved = st.tabs(
    ["Watchlist brief", "Explore", "Company view", f"Saved ({len(st.session_state.saved)})"]
)

# ---------------- Watchlist brief ----------------
with tab_brief:
    c1, c2 = st.columns([3, 1])
    c1.subheader("My watchlist brief")
    c1.caption("Every story about your watchlist companies in the chosen period, most important first. Edit the watchlist in the sidebar.")
    days = int(c2.number_input("Last N days", min_value=1, max_value=400, value=30, step=1, key="brief_days"))
    period = view[view["ticker"].isin(watch) & (view["published_at"] > as_of - timedelta(days=days))]
    period_label = f"last {days} days"

    if not watch:
        st.info("Your watchlist is empty. Add companies in the sidebar.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Stories ({period_label})", len(period))
        m2.metric("High priority", int((period["priority"] == "High").sum()))
        m3.metric("Companies with news", f"{period['ticker'].nunique()} of {len(watch)}")

        rows = []
        for t in watch:
            d = period[period["ticker"] == t]
            rows.append({
                "Company": f"{t} · {ticker_name[t]}",
                "Stories": len(d),
                "High": int((d["priority"] == "High").sum()),
                "Medium": int((d["priority"] == "Medium").sum()),
                "Latest": "-" if d.empty else f"{d['published_at'].max():%d %b} · {d.sort_values('published_at').iloc[-1]['headline']}",
            })
        with st.expander("Summary by company", expanded=False):
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        if period.empty:
            st.info(f"No watchlist stories ({period_label}).")
        for _, r in sort_feed(period).iterrows():
            item_card(r, f"brief_{r['record_id']}")

# ---------------- Explore ----------------
with tab_explore:
    q = st.text_input("Search", placeholder="Try: litigation, rating, SRL, order win, margin, Helixora approval…")
    f1, f2, f3, f4 = st.columns(4)
    sel_co = f1.multiselect("Company", companies["ticker"].tolist() + ["Macro"], format_func=lambda t: t if t == "Macro" else f"{t} · {ticker_name[t]}")
    sel_sector = f2.multiselect("Sector", sorted(view["sector"].unique()))
    sel_event = f3.multiselect("Tag", sorted(view["tag"].unique()), help="(u) on a story = it had no tag in the source data; the tag was assigned by this tool.")
    sel_prio = f4.multiselect("Priority", [p for p in PRIORITY_ORDER if p in set(view["priority"])])
    g1, g3, g4 = st.columns([1, 1, 1])
    sel_src = g1.multiselect("Source type", sorted(view["source_type"].unique()))
    dmin, dmax = df["published_at"].min().date(), as_of.date()
    dr = g3.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
    sort_by = g4.radio("Sort by", ["Relevance", "Priority", "Newest"], horizontal=True,
                       help="Relevance = how well a story matches what you typed (needs a search). Priority = importance score.")
    if sort_by == "Relevance" and not q.strip():
        g4.caption("Relevance applies once you search - sorted by priority for now.")
    w1, w2 = st.columns(2)
    only_watch = w1.checkbox("Watchlist only (incl. macro that affects it)")
    only_unopened = w2.checkbox("Hide stories I've opened")

    res, notes = search_index(base, companies, len(base)).run(view, q)
    if notes:
        st.caption("Search understood: " + " · ".join(notes))
    if sel_co:
        res = res[res["ticker"].isin(sel_co) | (res["is_macro"] & ("Macro" in sel_co))]
    if sel_sector:
        res = res[res["sector"].isin(sel_sector)]
    if sel_event:
        res = res[res["tag"].isin(sel_event)]
    if sel_prio:
        res = res[res["priority"].isin(sel_prio)]
    if sel_src:
        res = res[res["source_type"].isin(sel_src)]
    if isinstance(dr, tuple) and len(dr) == 2:
        res = res[(res["published_at"].dt.date >= dr[0]) & (res["published_at"].dt.date <= dr[1])]
    if only_unopened:
        res = res[~res["record_id"].isin(set(st.session_state.opened))]
    if only_watch:
        res = res[res["affects"].apply(lambda a: any(t in watch for t in a))]

    res = sort_feed(res, sort_by)
    if q.strip() and res.empty:
        st.info("No stories match all of that. Try fewer words, or check the filters above.")
    st.caption(f"{len(res)} stories · " + " · ".join(f"{p}: {(res['priority'] == p).sum()}" for p in PRIORITY_ORDER if (res['priority'] == p).any()))
    page_size = 20
    pages = max(1, -(-len(res) // page_size))
    page = st.number_input("Page", 1, pages, 1) if pages > 1 else 1
    for _, r in res.iloc[(page - 1) * page_size: page * page_size].iterrows():
        item_card(r, f"exp_{r['record_id']}")

# ---------------- Company view ----------------
with tab_company:
    default = watch[0] if watch else companies["ticker"].iloc[0]
    t = st.selectbox("Company", companies["ticker"].tolist(), index=companies["ticker"].tolist().index(default),
                     format_func=lambda x: f"{x} · {ticker_name[x]}" + (" ⭐" if x in watch else ""))
    info = companies.set_index("ticker").loc[t]
    st.markdown(f"### {info['company']}")
    st.caption(f"{info['sector']} · {info['industry']} · Also known as: {info['aliases']}")
    st.write(info["description"])

    cd = view[view["ticker"] == t]
    macro_for = view[view["is_macro"] & view["affects"].apply(lambda a: t in a)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Stories", len(cd))
    k2.metric("High priority", int((cd["priority"] == "High").sum()))
    k3.metric("Tier 1 events", int((cd["tier"] == 1).sum()))
    k4.metric("Relevant macro items", len(macro_for))

    if len(cd):
        chart = (
            alt.Chart(cd.assign(size=cd["score"]))
            .mark_circle(opacity=0.85)
            .encode(
                x=alt.X("published_at:T", title=None),
                y=alt.Y("tag:N", title=None, axis=alt.Axis(labelLimit=220)),
                size=alt.Size("score:Q", legend=None, scale=alt.Scale(range=[40, 400])),
                color=alt.Color("priority:N", title="Priority",
                                scale=alt.Scale(domain=PRIORITY_ORDER, range=[BADGE[p][0] for p in PRIORITY_ORDER])),
                tooltip=[alt.Tooltip("published_at:T", title="Date"), "headline:N", "priority:N", "score:Q"],
            )
            .properties(height=max(180, 32 * cd["tag"].nunique()), title="Timeline (bubble size = priority score)")
        )
        st.altair_chart(chart, width="stretch")

    st.markdown("##### All stories, newest first")
    for _, r in cd.sort_values("published_at", ascending=False).iterrows():
        item_card(r, f"co_{r['record_id']}")
    if len(macro_for):
        with st.expander(f"Macro / sector news that may affect {t} ({len(macro_for)})"):
            for _, r in sort_feed(macro_for, "Newest").iterrows():
                st.markdown(f"- {r['published_at']:%d %b %Y} · {badge(r['priority'])} {esc(r['headline'])}", unsafe_allow_html=True)

# ---------------- Saved ----------------
with tab_saved:
    saved = st.session_state.saved
    st.subheader("Saved for later")
    if not saved:
        st.info("Open any story and click **Save for later** to build a reading list. Notes are kept with each item.")
    else:
        sd = df[df["record_id"].isin(saved.keys())].copy()
        sd["note"] = sd["record_id"].map(lambda x: saved[x].get("note", ""))
        st.download_button(
            "Download reading list (CSV)",
            sd[["record_id", "published_at", "company", "headline", "priority", "note", "source_path"]].to_csv(index=False),
            "reading_list.csv",
        )
        for _, r in sd.sort_values("published_at", ascending=False).iterrows():
            if r["note"]:
                st.caption(f"📝 {esc(r['note'])}")
            item_card(r, f"sv_{r['record_id']}")
