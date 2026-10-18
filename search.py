"""
Search for Research Radar.

Plain keyword search fails on everyday queries: a typo ("revnue"), a different
word form ("grow" vs "grows" vs "growth"), a synonym ("lawsuit" vs
"litigation") or a company alias ("SRL"). This module handles those, and
gives every result a relevance score so the best matches come first.

Steps for a query:
  1. Find company names / aliases / tickers in it  ->  company filter
  2. Split the rest into keywords, drop filler words ("the", "for", ...)
  3. Reduce each word to its root ("grows", "growing" -> "grow")
  4. Fix typos by matching against words that actually exist in the feed
  5. Expand with synonyms from config.SEARCH_SYNONYMS
  6. Score each story. Show stories matching every keyword; if there are
     none, fall back to stories matching at least half of them
"""
from __future__ import annotations

import difflib
import math
import re

import pandas as pd
import snowballstemmer

import config as C

_stemmer = snowballstemmer.stemmer("english")


# Words the stemmer gets wrong for finance ("rating" -> "rate" would match "policy rate")
_OVERRIDES = {"rating": "rating", "ratings": "rating", "rated": "rating"}


def stem(word: str) -> str:
    w = word.lower()
    return _OVERRIDES.get(w) or _stemmer.stemWord(w)


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


def stems(text: str) -> list[str]:
    out = []
    for t in tokens(text):
        out.append(stem(t))
        if "-" in t:  # "input-cost" also matches "input" and "cost"
            out.extend(stem(p) for p in t.split("-"))
    return out


# Synonym groups, stored by root word: {"grow": {"grow","growth","rise",...}, ...}
_SYN: dict[str, set[str]] = {}
for group in C.SEARCH_SYNONYMS:
    roots = {stem(w) for w in group}
    for r in roots:
        _SYN.setdefault(r, set()).update(roots)


class SearchIndex:
    def __init__(self, df: pd.DataFrame, companies: pd.DataFrame):
        self.df = df
        # Alias table: lower-case name -> (ticker, name as typed in the master file)
        self.aliases: dict[str, tuple[str, str]] = {}
        for _, c in companies.iterrows():
            for name in [c["company"], c["ticker"]] + [a.strip() for a in c["aliases"].split(";")]:
                if name:
                    self.aliases[name.lower()] = (c["ticker"], name)
        self.ticker_name = dict(zip(companies["ticker"], companies["company"]))

        # Per-story word roots for each field (headline matters most)
        self.f_head = {i: stems(r["headline"]) for i, r in df.iterrows()}
        self.f_tags = {i: set(stems(f"{r['event_type']} {r['tags']} {r['industry']} {r['source_type']}")) for i, r in df.iterrows()}
        self.f_body = {i: set(stems(r["content"])) for i, r in df.iterrows()}
        # root -> a real word from the feed, to show the user ("revenu" -> "revenue")
        self.surface: dict[str, str] = {}
        for text in pd.concat([df["headline"], df["content"]]):
            for t in tokens(text):
                self.surface.setdefault(stem(t), t)
        self.vocab = sorted(set().union(*[set(v) for v in self.f_head.values()], *self.f_tags.values(), *self.f_body.values()))

    # ------------------------------------------------------------------
    def parse(self, query: str):
        """Turn the query into (companies, keyword groups, notes for the user)."""
        notes = []
        words = tokens(query)
        found: list[tuple[str, str]] = []  # (ticker, alias as typed)

        # 1. Company names / aliases: longest phrase first (e.g. "aranya bank" before "bank")
        i = 0
        rest = []
        while i < len(words):
            hit = None
            for n in (4, 3, 2, 1):
                phrase = " ".join(words[i:i + n])
                if len(words[i:i + n]) == n and phrase in self.aliases:
                    hit = (n, self.aliases[phrase])
                    break
            if hit:
                n, (ticker, alias) = hit
                found.append((ticker, alias))
                notes.append(f"**{alias}** → {self.ticker_name[ticker]}")
                i += n
            else:
                rest.append(words[i])
                i += 1

        # 2-5. Keywords
        groups = []  # each: (word as typed, set of acceptable roots)
        for w in rest:
            if w in C.STOPWORDS or len(w) < 2:
                continue
            root = stem(w)
            if root not in self.vocab and root not in _SYN and len(w) >= 4:
                close = difflib.get_close_matches(root, self.vocab + list(_SYN), n=1, cutoff=0.75)
                if close:
                    notes.append(f"'{w}' read as '{self.surface.get(close[0], close[0])}'")
                    root = close[0]
            accepted = {root} | _SYN.get(root, set())
            groups.append((w, root, accepted))
        return found, groups, notes

    # ------------------------------------------------------------------
    def run(self, subset: pd.DataFrame, query: str):
        """Return (matching rows with a `relevance` column, notes)."""
        found, groups, notes = self.parse(query)
        out = subset.copy()
        if not found and not groups:
            out["relevance"] = 0.0
            return out, notes

        if found:
            out = out[out["ticker"].isin({t for t, _ in found})]

        phrase = [g[1] for g in groups]
        rel, keep, full = [], [], []
        for i, r in out.iterrows():
            s, matched = 0.0, 0
            head = self.f_head[i]
            head_set = set(head)
            for _, root, accepted in groups:
                if root in head_set:
                    s += C.REL_HEADLINE_EXACT       # the exact word (any form) in the headline
                    matched += 1
                elif accepted & head_set:
                    s += C.REL_HEADLINE_SYNONYM     # a synonym in the headline
                    matched += 1
                elif accepted & self.f_tags[i]:
                    s += C.REL_TAG                  # event type / tag / industry
                    matched += 1
                elif accepted & self.f_body[i]:
                    s += C.REL_BODY                 # only in the article text
                    matched += 1
            if groups and matched < math.ceil(len(groups) / 2):
                continue
            is_full = matched == len(groups)
            if groups and is_full:
                s += C.REL_ALL_WORDS
            # Words typed in the same order as the headline ("revenue grows")
            if len(phrase) >= 2 and _contains_sequence(head, phrase):
                s += C.REL_PHRASE
            # The story uses the exact alias that was typed (e.g. "SRL")
            for _, alias in found:
                if re.search(r"\b" + re.escape(alias.lower()) + r"\b", f"{r['company_raw']} {r['headline']}".lower()):
                    s += C.REL_ALIAS_USED
                    break
            rel.append(s)
            keep.append(i)
            full.append(is_full)
        out = out.loc[keep]
        out["relevance"] = rel
        # If some stories match every keyword, show only those. Otherwise fall back
        # to stories matching at least half of them, so long queries still work.
        full = pd.Series(full, index=out.index, dtype=bool)
        if full.any():
            out = out[full]
        elif len(out):
            notes.append("no story matched every word - showing closest matches")
        return out, notes


def _contains_sequence(seq: list[str], sub: list[str]) -> bool:
    n = len(sub)
    return any(seq[k:k + n] == sub for k in range(len(seq) - n + 1))
