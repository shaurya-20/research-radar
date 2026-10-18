# Research Radar

A lightweight research intelligence tool: a searchable, prioritised view of the research feed, built around the analyst's watchlist.

**Live app:** _add your Streamlit link here_
**Design note:** see `NOTE.md` (what was built and why, key decisions, data handling, scoring methodology).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Files

| File | What it does |
|---|---|
| `app.py` | The interface: Watchlist brief, Explore, Company view, Saved |
| `pipeline.py` | Loads and cleans the feed, assigns tags, scores importance |
| `search.py` | Search: aliases, typos, word forms, synonyms, relevance ranking |
| `config.py` | Every rule and weight in one place |
| `data/` | The assignment data pack |
