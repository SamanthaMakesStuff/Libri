"""Turn the user's reviewed genre CSVs into one validated apply-set.

Handles, per the user's request to use best judgement:
  1. verb syntax   - they wrote accept/reject; the tool expects activate/drop
  2. merge targets that don't exist - resolved to a real slug, or the target is
     created where several terms clearly want it (e.g. 5 terms -> male-male-romance)
  3. new merge opportunities found by scanning what they kept
  4. deliberate NON-merges: loyalty/royalty, female-/male-author and
     female-/male-protagonist are opposites, not duplicates - fuzzy score is a
     trap there, so they are left alone.
"""
import csv

FILES = ["canon_adventure.csv", "canon_biography-memoir.csv",
         "canon_business-&-economics.csv", "canon_crime.csv",
         "canon_fantasy.csv", "canon_cross-genre.csv"]

KEEP = {"accept", "activate", "approve", "keep", "yes"}
KILL = {"reject", "drop", "no", "delete"}

# merge targets that don't exist -> a real, semantically correct slug.
# KEYED BY THE BAD TARGET (not the term), because that is what we look up.
RETARGET = {
    "contemporary-fiction": "contemporary",                    # active tag
    "protective-male-protagonist": "touch-her-and-die-possessive-protective-hero",
}

# targets worth CREATING because several terms clearly want them
CREATE = {
    "male-male-romance": "subgenre",    # wanted by danmei, mm, m-m-romance, mm-romance, mmromance
    "male-female-romance": "subgenre",  # parallel to the above
    "korean": "tag",                    # consistent with active american / british
    "african": "tag",
}

# merges I found by scanning the kept terms (singular/plural, spelling, variants)
EXTRA_MERGE = {
    "angst": "angsty",
    "autobiographies": "autobiography",
    "faerie-courts": "fae-courts",
    "memoirs": "memoir",
    "musicians": "musician",
    "politicians": "politics",
    "humour": "humor",              # UK/US - they chose `humor` as canonical
    "retellings": "retelling",
    "essays": "essay",
    "australia": "australian",      # adjectival, like active american/british
    "educational": "education",
}
# scored >=84 by fuzzy but semantically OPPOSITE - never merge these
DO_NOT_MERGE = {"loyalty", "female-author", "male-author",
                "female-protagonist", "male-protagonist"}

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
            # a kept term may still be a better merge than a standalone entry
            if term in EXTRA_MERGE and term not in DO_NOT_MERGE:
                out, stats["extra_merge"] = f"merge:{EXTRA_MERGE[term]}", stats["extra_merge"] + 1
            else:
                out, stats["activate"] = "activate", stats["activate"] + 1
        elif low in KILL:
            out, stats["drop"] = "drop", stats["drop"] + 1
        elif low.startswith("merge"):
            tgt = d.split(":", 1)[1].strip() if ":" in d else ""
            if tgt in RETARGET:
                tgt, stats["retargeted"] = RETARGET[tgt], stats["retargeted"] + 1
            out, stats["merge"] = f"merge:{tgt}", stats["merge"] + 1
        else:
            stats["unparsed"] += 1
            continue
        seen.add(term)
        rows_out.append({"decision": out, "term": term,
                         "kind": r.get("kind") or "tag",
                         "genre_bucket": r.get("genre_bucket") or ""})

# synthesise activation rows for targets that must exist before merges resolve
for slug, kind in CREATE.items():
    if slug not in seen:
        rows_out.append({"decision": "activate", "term": slug, "kind": kind,
                         "genre_bucket": ""})
        seen.add(slug)
        stats["created"] += 1

with open("canon_apply.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket"])
    w.writeheader()
    w.writerows(rows_out)

print(f"wrote canon_apply.csv ({len(rows_out)} decisions)")
for k, v in stats.items():
    print(f"  {k:<14} {v:>5}")
print(f"\n  created targets: {', '.join(sorted(CREATE))}")
print(f"  left un-merged on purpose (opposites): {', '.join(sorted(DO_NOT_MERGE))}")
