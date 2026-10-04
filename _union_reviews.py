"""Union the per-genre trope review CSVs into one, de-duplicating (book, trope).

A romantasy title is gated into both the romance and fantasy pools, so the
packs legitimately overlap; promoting each CSV separately would stage the same
book twice. Highest tier wins per (book, trope) pair.
"""
import csv
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRCS = sys.argv[1:-1] or ["trope_review_romance.csv", "trope_review_fantasy.csv",
                          "trope_review_sci-fi.csv", "trope_review_horror.csv"]
OUT = sys.argv[-1] if len(sys.argv) > 1 and sys.argv[-1].endswith(".csv") \
    else "trope_review_all.csv"
if OUT in SRCS:
    SRCS = [s for s in SRCS if s != OUT]

seen, rows, per_src = {}, [], Counter()
for src in SRCS:
    for r in csv.DictReader(open(src, encoding="utf-8-sig")):
        per_src[src] += 1
        key = (r["book_id"], r["trope"])
        if key in seen:
            if r["tier"] == "A" and seen[key]["tier"] == "B":
                seen[key].update(r)   # keep the stronger evidence
            continue
        seen[key] = r
        rows.append(r)

rows.sort(key=lambda x: (x["tier"], x["trope"]))
with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

books = {r["book_id"] for r in rows}
tiers = Counter(r["tier"] for r in rows)
for s, n in per_src.items():
    print(f"  {s:<32} {n:>6,} rows")
print(f"\nunion: {len(rows):,} assignments over {len(books):,} distinct books "
      f"(tier A={tiers['A']:,}, B={tiers['B']:,})")
print(f"deduplicated {sum(per_src.values()) - len(rows):,} overlapping rows")
print(f"-> {OUT}")
