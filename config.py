"""
All the judgement calls in one place.

These are the assumptions of the scoring model. They are deliberately simple
and visible so a research analyst can disagree with one and change it.
"""

# ----------------------------------------------------------------------------
# Tags
# Tagged stories keep the tag from the source data. Untagged stories get one
# of the existing tags (marked "(u)" in the app):
#   1. Routine disclosures -> "routine/admin"
#   2. Otherwise, the tag most used by other stories with the same headline
#      wording (company name and numbers ignored)
#   3. Otherwise, a keyword rule below
# ----------------------------------------------------------------------------
ROUTINE_TAG = "routine/admin"
ROUTINE_PATTERNS = [
    r"trading window", r"general meeting notice", r"investor meeting", r"newspaper advertisement",
    r"registered office", r"committee composition", r"marathon", r"skill-development",
    r"sustainability certification", r"marketing award",
]
UNTAGGED_KEYWORD_FALLBACK = [   # (headline pattern, existing tag)
    (r"regulator seeks clarification", "regulatory review"),
    (r"wins order", "order win"),
    (r"quarterly profit", "earnings"),
    (r"capex", "capex"),
    (r"rating", "credit rating"),
    (r"arpu", "arpu"),
    (r"commissions new", "capacity expansion"),
    (r"rules|duty|framework|policy", "macro; sector development"),
]

# ----------------------------------------------------------------------------
# IMPORTANCE SCORE
# Built on the same dimensions commercial news-analytics products use
# (RavenPack, LSEG News Analytics): WHAT happened (event materiality),
# HOW BIG it is (magnitude),
# and WHO says so (source). Freshness is handled by date filters and sorting,
# not mixed into the score, so a story's importance doesn't change every day.
# ----------------------------------------------------------------------------

# 1. Event materiality tiers
#    Tier 1 - SEBI LODR Sched. III Para A ("deemed material", no threshold test)
#             AND strong market-reaction evidence
#    Tier 2 - Para B events (material if large) that are usually material,
#             plus sector-wide regulatory change
#    Tier 3 - Para B events that are often below the materiality bar, and
#             context (commentary, operating KPIs, industry trends)
#    Tier 4 - no new information (rating reaffirmed = no rating revision)
#    The tier of each tag is set in TAG_TIER below.
#    Routine - procedural / scheduled / unrelated to cash flows (score 0)
TAG_TIER = {
    # Tier 1
    "earnings": 1, "quarterly earnings": 1, "acquisition": 1,
    "regulatory review": 1, "regulatory inspection": 1,
    # Tier 2
    "litigation": 2, "project delay": 2, "project update": 2, "technology outage": 2,
    "maintenance": 2, "order win": 2, "deal win": 2, "contract": 2,
    "regulatory approval": 2, "clinical trial": 2, "client spending": 2,
    "regulation": 2, "spectrum": 2,
    # Tier 3
    "margin pressure": 3, "input cost": 3, "commodity input": 3, "capex": 3,
    "capacity expansion": 3, "branch expansion": 3, "network expansion": 3,
    "enterprise": 3, "financing": 3, "product launch": 3, "partnership": 3,
    "strategy": 3, "arpu": 3, "deposits": 3, "distribution": 3, "exports": 3,
    "inventory": 3, "sales": 3, "workforce": 3, "industry trend": 3,
    "industry demand": 3, "macro; sector development": 3, "promoter activity": 3,
    # Routine
    ROUTINE_TAG: 0,
}
# "credit rating" covers three very different events, so its tier is read from the headline:
RATING_DOWNGRADE = [r"downgrad", r"outlook revised to negative"]      # Tier 1
RATING_UPGRADE = [r"upgraded", r"outlook revised to positive"]        # Tier 2
#                                     anything else (reaffirmed etc.) -> Tier 4
TIER_POINTS = {1: 50, 2: 35, 3: 20, 4: 8, 0: 0}
TIER_LABEL = {
    1: "Tier 1 - deemed material",
    2: "Tier 2 - usually material",
    3: "Tier 3 - context",
    4: "Tier 4 - no change",
    0: "Routine",
}

# 2. Relevance to the analyst is deliberately NOT scored. The watchlist is used
#    as a filter (Watchlist brief, "Watchlist only"), so the priority label
#    describes the event itself, the same for every reader.

# 3. Magnitude - a big number in the story
W_MAGNITUDE = 10
BIG_PERCENT = 15          # e.g. profit +23%, realisation -26%
BIG_CRORE = 500           # ₹ crore (deal / order / capex size)
BIG_USD_MN = 250
BIG_BPS = 20              # margin change
BIG_DELAY_DAYS = 60       # project delay / shutdown length

# 4. Source - official disclosure vs media report
W_PRIMARY_SOURCE = 5

HIGH_FROM = 55            # Tier 1 from an official source or with a big number
MEDIUM_FROM = 35          # Tier 2, or Tier 3 with a big number from an official source

# Duplicates: only self-declared re-carries are merged (see pipeline.dedupe)
RECARRY_PATTERN = r"^A second public-market feed carried substantially the same development concerning [^.]+\.\s*"
BOILERPLATE = ("The update was published through a public-market information channel and would "
               "typically be reviewed alongside prior company disclosures and sector developments.")

# ----------------------------------------------------------------------------
# Source reliability
# ----------------------------------------------------------------------------
TIER_ORDER = ["Primary", "Rating agency", "Secondary"]
SOURCE_TIER = {
    "Exchange Disclosure Feed": "Primary",
    "Company IR Desk": "Primary",
    "Corporate Communications": "Primary",
    "Investor Relations": "Primary",
    "Quarterly Results Release": "Primary",
    "Earnings Call Update": "Primary",
    "Monthly Business Update": "Primary",
    "Operations Bulletin": "Primary",
    "Exchange Circular Digest": "Primary",
    "Regulatory Bulletin": "Primary",
    "Policy Monitor": "Primary",
    "Ratings Update Desk": "Rating agency",
    "Credit Review Note": "Rating agency",
    # Everything else (newswires, trade press, interviews) -> Secondary
}

# ----------------------------------------------------------------------------
# Which industries a macro theme affects (keyed by the feed's `industry` field)
# ----------------------------------------------------------------------------
MACRO_IMPACT = {
    "Metals": ["Specialty Metals", "Automobiles", "Engineering & EPC"],
    "Currency": ["IT Services", "Enterprise Software", "Pharmaceuticals"],
    "Monetary Policy": ["Private Sector Bank", "NBFC"],
    "Energy": ["Gas Transmission", "Automobiles", "Packaged Foods"],
    "Renewables": ["Renewable Power"],
    "Infrastructure": ["Engineering & EPC", "Railway Systems", "Industrial Automation"],
    "Technology": ["IT Services", "Enterprise Software", "Telecom"],
    "Electronics": ["Automobiles", "Railway Systems", "Telecom"],
    "Consumer": ["Packaged Foods", "Automobiles"],
}

# ----------------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------------
# Words in the same group find each other ("lawsuit" finds "litigation").
# Each word is reduced to its root first, so "grows"/"growing" are covered by "grow".
SEARCH_SYNONYMS = [
    ["grow", "growth", "rise", "increase", "lift", "expand", "improve"],
    ["fall", "decline", "drop", "decrease", "narrow", "soften", "weaken"],
    ["profit", "earnings", "ebitda", "pat", "income"],
    ["revenue", "sales", "topline"],
    ["result", "results", "quarterly", "earnings"],
    ["delay", "delayed", "postpone", "timeline", "slippage"],
    ["lawsuit", "litigation", "legal", "patent", "court", "sue"],
    ["acquisition", "acquire", "buy", "takeover", "merger", "m&a"],
    ["order", "contract", "deal", "agreement"],
    ["rating", "upgrade", "downgrade", "outlook", "credit"],
    ["regulator", "regulatory", "regulation", "inspection", "compliance", "supervisory"],
    ["debt", "financing", "borrowing", "leverage", "loan"],
    ["launch", "launches", "introduce", "product"],
    ["capex", "capacity", "plant", "expansion", "investment"],
    ["approval", "approve", "approved", "clearance"],
    ["cost", "costs", "input", "inflation", "commodity"],
    ["margin", "margins", "profitability"],
    ["outage", "disruption", "shutdown"],
    ["ai", "artificial", "agentic"],
    ["usa", "america", "united", "states"],
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "about",
    "is", "are", "was", "were", "be", "news", "any", "all", "show", "me", "what", "which",
    "from", "this", "that", "its", "has", "have", "did", "does", "latest", "recent",
}

# Relevance points
REL_HEADLINE_EXACT = 4    # the typed word (any form) is in the headline
REL_HEADLINE_SYNONYM = 3  # a synonym is in the headline
REL_TAG = 2               # matches the event type / tag / industry
REL_BODY = 1              # only in the article text
REL_ALL_WORDS = 3         # every keyword matched
REL_PHRASE = 3            # keywords appear in the same order in the headline
REL_ALIAS_USED = 5        # the story itself uses the alias that was typed
