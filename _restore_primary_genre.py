"""Restore each book's PRIMARY genre where the old reclassify() bug dropped it.

The catalogue genre array is ordered by prominence - catalog[0] is reliably the
true primary (verified: Gerald's Game->Horror, Six of Crows->Fantasy,
Dune->Sci-Fi, Mistborn->Fantasy). So restoring only catalog[0], only when it is
missing, is a precise 1-genre-per-book fix rather than dumping the whole noisy
shelf aggregation back in.

EXCLUDED: books whose DB genres already carry a romance subgenre / Romantasy.
reclassify() only adds 'Romantasy' when the source genres contained fantasy AND
the book is a romance, which flags a cluster of lesfic contemporary romances
whose catalogue genre is simply wrong (The Headmistress, Charming The Vicar...).
Restoring those would import a bad source value.

Nothing is deleted - the primary is prepended to the existing genres.

  python _restore_primary_genre.py --dry-run
  python _restore_primary_genre.py
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

DRY = "--dry-run" in sys.argv

ROMSUB = {"romantasy", "contemporary romance", "historical romance",
          "paranormal romance", "romantic suspense", "small-town romance",
          "sports romance", "holiday romance", "fantasy romance",
          "sci-fi romance", "erotica", "dark romance", "second chance romance"}

cat = {b.get("id"): b for b in json.load(open("bookCatalog.json", encoding="utf-8"))
       if b.get("id")}
conn = sqlite3.connect(C.DB_PATH, timeout=900)
conn.row_factory = sqlite3.Row

fixes, stats, restored = [], Counter(), Counter()
for r in conn.execute("SELECT id, title, genres FROM books"):
    cb = cat.get(r["id"])
    if not cb:
        continue
    raw = cb.get("genre")
    src = [x for x in ([raw] if isinstance(raw, str) else (raw or [])) if x]
    if not src:
        continue
    try:
        db = json.loads(r["genres"] or "[]")
    except Exception:
        continue
    dbl = {x.lower() for x in db}
    primary = src[0]
    if primary.lower() in dbl:
        stats["already_present"] += 1
        continue
    if dbl & ROMSUB:
        stats["excluded_romance_subgenre"] += 1
        continue
    new = [primary] + db                       # prepend; never delete
    fixes.append((r["id"], r["genres"], json.dumps(new, ensure_ascii=False)))
    restored[primary] += 1
    stats["restored"] += 1

if not DRY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (C.ROOT / f"primary_genre_backup_{ts}.json").write_text(
        json.dumps([{"id": i, "genres": old} for i, old, _ in fixes],
                   ensure_ascii=False), encoding="utf-8")
    for bid, _, new in fixes:
        conn.execute("UPDATE books SET genres=? WHERE id=?", (new, bid))
    conn.commit()
    print(f"backup -> primary_genre_backup_{ts}.json")

print(f"\n{'DRY RUN - ' if DRY else ''}primary-genre restore")
for k, v in stats.most_common():
    print(f"  {k:<28} {v:>7,}")
print("\n  restored (top 10):")
for g, n in restored.most_common(10):
    print(f"     {n:>5}  {g}")
conn.close()
