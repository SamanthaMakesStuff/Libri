"""Sample a trope review CSV: N examples per trope, with matched phrase +
context, so precision can be judged before anything is promoted.

  python _audit_trope_csv.py trope_review_romance.csv 5 royalty virgin-heroine
  python _audit_trope_csv.py trope_review_romance.csv 3          # every trope
"""
import csv
import random
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
only = set(sys.argv[3:])

by = defaultdict(list)
for r in csv.DictReader(open(src, encoding="utf-8-sig")):
    by[r.get("trope") or r.get("tag")].append(r)

random.seed(7)
for trope in sorted(by, key=lambda t: -len(by[t])):
    if only and trope not in only:
        continue
    rows = by[trope]
    print(f"\n### [{rows[0]['tier']}] {trope}  ({len(rows)} matches)")
    for r in random.sample(rows, min(n, len(rows))):
        print(f"  - {r['title'][:60]} / {r['author'][:28]}")
        print(f"      phrase: {r['matched_phrase']!r}")
        print(f"      {r['context'][:200]}")
