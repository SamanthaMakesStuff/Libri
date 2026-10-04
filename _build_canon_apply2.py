"""Validated apply-set for the second batch of reviewed genre CSVs
(crime, romance, sci-fi, self-help, thriller & mystery, young adult).

Same treatment as batch 1: accept/reject -> activate/drop, dead merge targets
resolved or created, extra merges found by scanning, opposites left alone.
"""
import csv

FILES = ["canon_crime.csv", "canon_romance.csv", "canon_sci-fi.csv",
         "canon_self-help.csv", "canon_thriller-&-mystery.csv",
         "canon_young-adult.csv"]

KEEP = {"accept", "activate", "approve", "keep", "yes"}
KILL = {"reject", "drop", "no", "delete"}

# dead merge targets -> the real slug. KEYED BY THE BAD TARGET.
RETARGET = {
    "apocylyptic": "apocalyptic",        # typo; `apocalyptic` is an active subgenre
    "classic": "classics",               # `classics` is the activated form
    "comedy-romance": "romantic-comedy",  # active subgenre, same concept
}

# targets that genuinely don't exist and are worth creating
CREATE = {
    "climate": "tag",                 # climatic-changes -> a climate topic tag
    "north-korea": "tag",             # symmetry with the activated south-korea
    "trans-main-character": "tag",    # trans rep - no trans term existed at all
}

# merges found by scanning what was kept
EXTRA_MERGE = {
    "alien": "aliens",
    "zombie": "zombies",
    "rusia": "russia",                                   # misspelling
    "mythic": "mythical",
    "life-on-other-planets-fiction": "life-on-other-planets",  # library "-fiction" noise
    "body-mind-and-spirit": "mind-and-spirit",
}

# high fuzzy score but WRONG to merge:
#   stalker-protagonist ~ male-protagonist (85) - unrelated concepts
#   technology-gone-wrong ~ biotechnology-gone-wrong (93) - merging the broad
#     term into the narrow one loses meaning; keep the general term standalone
DO_NOT_MERGE = {"stalker-protagonist", "technology-gone-wrong"}

rows_out, seen = [], set()
stats = {"activate": 0, "drop": 0, "merge": 0, "retargeted": 0,
         "extra_merge": 0, "created": 0, "unparsed": 0}

for f in FILES:
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        d = (r.get("decision") or "").strip()
        term = r["term"]
        if not d or term in seen:
            continue
        low = d.lower()
        if low in KEEP:
            if term in EXTRA_MERGE and term not in DO_NOT_MERGE:
                out = f"merge:{EXTRA_MERGE[term]}"
                stats["extra_merge"] += 1
            else:
                out = "activate"
                stats["activate"] += 1
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
            stats["unparsed"] += 1
            continue
        seen.add(term)
        rows_out.append({"decision": out, "term": term,
                         "kind": r.get("kind") or "tag",
                         "genre_bucket": r.get("genre_bucket") or ""})

for slug, kind in CREATE.items():
    if slug not in seen:
        rows_out.append({"decision": "activate", "term": slug, "kind": kind,
                         "genre_bucket": ""})
        seen.add(slug)
        stats["created"] += 1

with open("canon_apply2.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket"])
    w.writeheader()
    w.writerows(rows_out)

print(f"wrote canon_apply2.csv ({len(rows_out)} decisions)")
for k, v in stats.items():
    print(f"  {k:<14} {v:>5}")
print(f"\n  created: {', '.join(sorted(CREATE))}")
print(f"  not merged (wrong to): {', '.join(sorted(DO_NOT_MERGE))}")
