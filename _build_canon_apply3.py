"""Validated apply-set for the third batch of reviewed genre CSVs
(psychology, mystery, history, graphic novel, general fiction).
"""
import csv

FILES = ["canon_psychology.csv", "canon_mystery.csv", "canon_history.csv",
         "canon_graphic-novel.csv", "canon_general-fiction.csv"]

KEEP = {"accept", "activate", "approve", "keep", "yes"}
KILL = {"reject", "drop", "no", "delete"}

# dead merge targets -> real slugs. KEYED BY THE BAD TARGET.
RETARGET = {
    # 3 BISAC-style headings all pointed here. Both `thriller` and `mystery`
    # already exist as genres, so inventing a `thriller-crime` compound would
    # duplicate them. `crime` is an active tag and is the shared concept.
    "thriller&crime": "crime",
    # `history-roman` is Ancient Rome. The active `greek-and-roman` tag is the
    # exact home. NB fuzzy suggested `romance` (83) - that would be very wrong.
    "roman": "greek-and-roman",
}

CREATE = {
    "jewish": "tag",   # `jews` had nowhere to go; consistent with american/korean/african
}

EXTRA_MERGE = {
    "forests": "forest",                              # singular/plural
    "private-investigator": "private-investigators",  # active form is plural
}

DO_NOT_MERGE = set()

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

with open("canon_apply3.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket"])
    w.writeheader()
    w.writerows(rows_out)

print(f"wrote canon_apply3.csv ({len(rows_out)} decisions)")
for k, v in stats.items():
    print(f"  {k:<14} {v:>5}")
print(f"\n  created: {', '.join(sorted(CREATE)) or '(none)'}")
