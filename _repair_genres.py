"""Repair genres destroyed by the old reclassify() bug.

reclassify() emitted only [primary, subgenre], silently discarding every other
genre the catalogue supplied. This restores them from bookCatalog.json (which
still holds the correct values) using the FIXED reclassify.

Only books that actually LOST a source genre are touched, and only the `genres`
column is written - tropes/tags/spice have been enriched since and must not be
recomputed from the stale catalogue.

  python _repair_genres.py --dry-run
  python _repair_genres.py
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C
from reclassify import reclassify

DRY = "--dry-run" in sys.argv

cat = {b.get("id"): b for b in json.load(open("bookCatalog.json", encoding="utf-8"))
       if b.get("id")}
conn = sqlite3.connect(C.DB_PATH, timeout=900)
conn.row_factory = sqlite3.Row

fixes, stats, restored = [], Counter(), Counter()
for r in conn.execute("SELECT id, title, genres FROM books"):
    cb = cat.get(r["id"])
    if not cb:
        stats["not_in_catalog"] += 1
        continue
    raw = cb.get("genre")
    src = [g for g in ([raw] if isinstance(raw, str) else (raw or [])) if g]
    if not src:
        continue
    try:
        db = json.loads(r["genres"] or "[]")
    except Exception:
        db = []
    # Repair ONLY genuine corruption: the DB genres share NOTHING with the
    # catalogue, i.e. the book's identity was replaced (Fantasy -> Mystery/crime).
    # Books that merely have FEWER genres than the catalogue are left alone -
    # the catalogue arrays are noisy shelf aggregations (Six of Crows is listed
    # as Fantasy+Sci-Fi+Thriller+Mystery+Romance), and restoring all of that
    # would flood the genre signal with junk.
    if set(db) & set(src):
        stats["ok_shares_a_genre"] += 1
        continue
    # source of truth first, then whatever the DB already had (never delete)
    new = list(src) + [g for g in db if g not in src]
    if new == db:
        stats["no_change"] += 1
        continue
    stats["repaired"] += 1
    for g in src:
        restored[g] += 1
    fixes.append((r["id"], r["genres"], json.dumps(new, ensure_ascii=False),
                  r["title"], db, new))

if not DRY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (C.ROOT / f"genre_repair_backup_{ts}.json").write_text(
        json.dumps([{"id": i, "genres": old} for i, old, _, _, _, _ in fixes],
                   ensure_ascii=False), encoding="utf-8")
    for bid, _, new, _, _, _ in fixes:
        conn.execute("UPDATE books SET genres=? WHERE id=?", (new, bid))
    conn.commit()
    print(f"backup -> genre_repair_backup_{ts}.json")

print(f"\n{'DRY RUN - ' if DRY else ''}genre repair")
for k, v in stats.most_common():
    print(f"  {k:<18} {v:>7,}")
print("\n  genres restored (top 12):")
for g, n in restored.most_common(12):
    print(f"     {n:>6}  {g}")
print("\n  sample repairs:")
for _, _, _, title, db, new in fixes[:8]:
    print(f"     {title[:30]:<32} {db} -> {new}")
conn.close()
