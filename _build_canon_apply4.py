"""Validated apply-set for canon_(none).csv.

The user observed these look mostly non-fiction, and the term list bears that
out (python-programming-language, diet-and-nutrition, statistics, veganism...).
So the clearly technical/practical/academic terms are scoped applies_to=
'nonfiction'; genuinely dual-use ones (culture, childhood, censorship,
language, television) stay 'both'.
"""
import csv

SRC = "canon_(none).csv"
KEEP = {"accept", "activate", "approve", "keep", "yes"}
KILL = {"reject", "drop", "no", "delete"}

RETARGET = {
    "essays": "essay",                    # `essay` is the canonical form we merged to
    "christian-romance": "christian-living",  # no such term; christian-living is kept here
}

EXTRA_MERGE = {
    "c-computer-program-language": "c-programming-language",   # same language
    "cognitive-psychology-and-cognition": "cognitive-psychology",
    "computers-and-information-technology": "computers-and-technology",
    "diets": "diet",
    "computer-algorithms": "algorithms",
    "language-and-languages": "language",
    "probability-and-statistics": "statistics",
}

# The fuzzy scan paired the programming languages with each other at 73-89
# (c / rust / python / javascript). They are DIFFERENT languages - never merge.
DO_NOT_MERGE = {"python-programming-language", "rust-programming-language",
                "javascript-programming-language", "c-programming-language",
                "web-programming", "computers", "computer-science"}

NONFICTION = {
    "algorithms", "alternative-and-complementary-medicine", "animal-behavior",
    "application-software", "applied-psychology", "big-data",
    "c-programming-language", "cognitive-psychology", "computer-science",
    "computers", "computers-and-technology", "consumer-behavior", "data-science",
    "developmental", "diet", "diet-and-nutrition", "economics-and-trade",
    "fitness", "gardening", "genetics", "how-to", "human-computer-interaction",
    "industrial-management", "internet", "javascript-programming-language",
    "marketing", "networking", "personal-and-practical-guides", "programming",
    "python-programming-language", "rust-programming-language", "security",
    "social-psychology-and-interactions", "software-development-and-engineering",
    "statistics", "tech", "veganism", "web-programming", "christian-living",
    "spiritual-life", "logic", "future-studies", "urbanism",
}

rows_out, seen = [], set()
stats = {"activate": 0, "drop": 0, "merge": 0, "retargeted": 0,
         "extra_merge": 0, "nonfiction_scoped": 0}

for r in csv.DictReader(open(SRC, encoding="utf-8-sig")):
    d = (r.get("decision") or "").strip()
    term = r["term"]
    if not d or term in seen:
        continue
    low = d.lower()
    applies = ""
    if low in KEEP:
        if term in EXTRA_MERGE and term not in DO_NOT_MERGE:
            out = f"merge:{EXTRA_MERGE[term]}"
            stats["extra_merge"] += 1
        else:
            out = "activate"
            stats["activate"] += 1
            if term in NONFICTION:
                applies = "nonfiction"
                stats["nonfiction_scoped"] += 1
    elif low in KILL:
        out = "drop"
        stats["drop"] += 1
    elif low.startswith("merge"):
        tgt = d.split(":", 1)[1].strip() if ":" in d else ""
        if tgt in RETARGET:
            tgt = RETARGET[tgt]
            stats["retargeted"] += 1
        out = f"merge:{tgt}"
        stats["merge"] += 1
    else:
        continue
    seen.add(term)
    rows_out.append({"decision": out, "term": term, "kind": r.get("kind") or "tag",
                     "genre_bucket": "", "applies_to": applies})

with open("canon_apply4.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket", "applies_to"])
    w.writeheader()
    w.writerows(rows_out)

print(f"wrote canon_apply4.csv ({len(rows_out)} decisions)")
for k, v in stats.items():
    print(f"  {k:<18} {v:>4}")
print(f"\n  NOT merged (different languages / distinct concepts): "
      f"{', '.join(sorted(DO_NOT_MERGE))}")
