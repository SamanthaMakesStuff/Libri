"""Build a review CSV of MoodReads vocabulary that has no taxonomy home.

These are the terms the scoped merge could NOT map to a canonical slug, so they
were dropped rather than injected raw. They are reader-facing mood/trope words
from a romantasy site, so several are likely worth adopting.

Same shape as the canon_*.csv files, so the existing workflow applies:
  edit `decision` -> merge:<slug> | activate | drop | (blank)
  then: python enrich.py canonicalise --apply moodreads_terms_review.csv
"""
import csv
import json
import sqlite3
from collections import Counter

from rapidfuzz import fuzz, process

import config as C
from enrich_taxonomy import normalize_raw, slugify

MIN_FREQ = 2

conn = sqlite3.connect(C.DB_PATH, timeout=120)
conn.row_factory = sqlite3.Row
active = {r["slug"]: r["kind"] for r in
          conn.execute("SELECT slug, kind FROM taxonomy WHERE status='active'")}
display = {r["display"]: r["slug"] for r in
           conn.execute("SELECT slug, display FROM taxonomy WHERE status='active'")
           if r["display"]}
alias = {r["alias"]: r["slug"] for r in
         conn.execute("SELECT alias, slug FROM taxonomy_alias")}
rejected = {r["slug"] for r in
            conn.execute("SELECT slug FROM taxonomy WHERE status='rejected'")}


def canon(term):
    s = slugify(term)
    if s in active:
        return s
    a = alias.get(normalize_raw(term)) or alias.get(s)
    return a if a and a in active else None


catalog = [b for b in json.load(open("bookCatalog.json", encoding="utf-8"))
           if "MoodReads" in (b.get("verifiedSource") or "")]

freq, examples, fields = Counter(), {}, {}
for b in catalog:
    for f in ("tropes", "tags", "contentWarnings"):
        for t in (b.get(f) or []):
            if canon(t):
                continue
            freq[t] += 1
            fields.setdefault(t, Counter())[f] += 1
            examples.setdefault(t, [])
            if len(examples[t]) < 3:
                examples[t].append(b.get("title", "")[:40])

choices = list(display.keys()) + list(active.keys())
rows = []
for term, n in freq.most_common():
    if n < MIN_FREQ or slugify(term) in rejected:
        continue
    cands = process.extract(normalize_raw(term), choices,
                            scorer=fuzz.token_sort_ratio, limit=3)
    near = []
    for cand, score, _ in cands:
        near += [display.get(cand, cand), int(score)]
    near += [""] * (6 - len(near))
    src = fields[term].most_common(1)[0][0]
    rows.append({
        "decision": "", "term": slugify(term), "raw_term": term, "books": n,
        "kind": "warning" if src == "contentWarnings" else "tag",
        "from_field": src,
        "nearest_1": near[0], "score_1": near[1],
        "nearest_2": near[2], "score_2": near[3],
        "nearest_3": near[4], "score_3": near[5],
        "example_books": " | ".join(examples[term]),
    })

out = "moodreads_terms_review.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

skipped = sum(1 for t, n in freq.items() if n < MIN_FREQ)
print(f"wrote {out} ({len(rows)} terms on >={MIN_FREQ} books)")
print(f"  singletons skipped as noise: {skipped}")
print(f"  by source field: {dict(Counter(r['from_field'] for r in rows))}")
print(f"  with a >=80 fuzzy match to an existing slug: "
      f"{sum(1 for r in rows if r['score_1'] and int(r['score_1']) >= 80)}")
