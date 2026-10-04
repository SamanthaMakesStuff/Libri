"""Split tag_review.csv into a clean-to-promote set and a hold set.

CLEAN = concrete-noun tags that audited with essentially no nonfiction leakage.
HOLD  = identity + abstract tags still polluted by mis-shelved academic books
        (gender-studies readers, lit-crit, film criticism); these wait for a
        stronger nonfiction guard before promotion.
"""
import csv
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLEAN = {"vampires", "ghosts", "witches", "pirates", "mermaids", "zombies",
         "aliens", "space", "spies", "steampunk", "occult", "noir",
         "superheroes", "supernatural", "paranormal"}
rows = list(csv.DictReader(open("tag_review.csv", encoding="utf-8-sig")))
clean = [r for r in rows if r["tag"] in CLEAN]
hold = [r for r in rows if r["tag"] not in CLEAN]

for name, rs in (("tag_review_clean.csv", clean), ("tag_review_hold.csv", hold)):
    with open(name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rs)

print(f"clean rows: {len(clean)}  over {len({r['book_id'] for r in clean})} books "
      f"-> tag_review_clean.csv")
print(f"hold  rows: {len(hold)}   over {len({r['book_id'] for r in hold})} books "
      f"-> tag_review_hold.csv")
print("hold tag counts:", dict(Counter(r["tag"] for r in hold)))
