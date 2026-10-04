"""Turn trope_review_mystery.csv into a staged enrichment batch, per the user's
'promote tiers A and B' instruction.

Groups matched tropes by book, emits an inline batch (validated against the live
taxonomy by enrich_inline, union-merged and rollback-able by promote). A book is
tagged confidence 'high' only if ALL its tropes are tier A; any tier-B trope
drops it to 'medium'. Both are promoted, but the distinction is preserved in the
record. Honours a `decision` column if present (reject drops that row).
"""
import csv
import json
import sys
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else "trope_review_mystery.csv"
TAG = sys.argv[2] if len(sys.argv) > 2 else "mystery"
rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
by_book = defaultdict(lambda: {"tropes": [], "tiers": set(), "title": ""})
dropped = 0
for r in rows:
    d = (r.get("decision(keep/blank)") or r.get("decision") or "").strip().lower()
    if d in ("reject", "no", "drop"):
        dropped += 1
        continue
    b = by_book[r["book_id"]]
    if r["trope"] not in b["tropes"]:
        b["tropes"].append(r["trope"])
    b["tiers"].add(r["tier"])
    b["title"] = r["title"]

batch = []
tier_count = {"high": 0, "medium": 0}
for bid, b in by_book.items():
    conf = "high" if b["tiers"] == {"A"} else "medium"
    tier_count[conf] += 1
    batch.append({"id": bid, "known": True, "book_class": "fiction",
                  "confidence": conf, "tropes": b["tropes"][:8], "tags": [],
                  "_note": f"deterministic trope-match from description "
                           f"(tiers {'/'.join(sorted(b['tiers']))})"})

json.dump(batch, open(f"inline_batch_{TAG}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# decisions CSV scoped to exactly these books, so promote touches nothing else
with open(f"{TAG}_trope_decisions.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["decision", "book_id", "title"])
    for bid, b in by_book.items():
        w.writerow(["approve", bid, b["title"]])

print(f"books: {len(batch)}  (high={tier_count['high']}, medium={tier_count['medium']})")
print(f"rows dropped by a reject decision: {dropped}")
print(f"wrote inline_batch_{TAG}.json + {TAG}_trope_decisions.csv")
