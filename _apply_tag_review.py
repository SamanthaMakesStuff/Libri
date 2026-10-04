"""Turn a tag review CSV into a staged enrichment batch (tags edition).

Mirrors _apply_trope_review.py but writes the `tags` field. Groups matched tags
by book, emits an inline batch validated against the live taxonomy by
enrich_inline (which now enforces kind=tag), union-merged and rollback-able by
promote. All-tier-A -> confidence high; any tier-B tag -> medium. A `decision`
column of reject/no/drop removes that row.

  python _apply_tag_review.py tag_review.csv tags
"""
import csv
import json
import sys
from collections import defaultdict

SRC = sys.argv[1] if len(sys.argv) > 1 else "tag_review.csv"
TAG = sys.argv[2] if len(sys.argv) > 2 else "tags"
rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
by_book = defaultdict(lambda: {"tags": [], "tiers": set(), "title": ""})
dropped = 0
for r in rows:
    d = (r.get("decision(keep/blank)") or r.get("decision") or "").strip().lower()
    if d in ("reject", "no", "drop"):
        dropped += 1
        continue
    b = by_book[r["book_id"]]
    if r["tag"] not in b["tags"]:
        b["tags"].append(r["tag"])
    b["tiers"].add(r["tier"])
    b["title"] = r["title"]

batch = []
tier_count = {"high": 0, "medium": 0}
for bid, b in by_book.items():
    conf = "high" if b["tiers"] == {"A"} else "medium"
    tier_count[conf] += 1
    batch.append({"id": bid, "known": True, "book_class": "fiction",
                  "confidence": conf, "tropes": [], "tags": b["tags"][:12],
                  "_note": f"deterministic tag-match from description "
                           f"(tiers {'/'.join(sorted(b['tiers']))})"})

json.dump(batch, open(f"inline_batch_{TAG}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

with open(f"{TAG}_tag_decisions.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["decision", "book_id", "title"])
    for bid, b in by_book.items():
        w.writerow(["approve", bid, b["title"]])

print(f"books: {len(batch)}  (high={tier_count['high']}, medium={tier_count['medium']})")
print(f"rows dropped by a reject decision: {dropped}")
print(f"wrote inline_batch_{TAG}.json + {TAG}_tag_decisions.csv")
