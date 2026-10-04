"""Read-only: active tag slugs by current usage, plus the reachable pool.

Tags carry 40% of the recommendation score (vs 30% for tropes), so a tag pack
is worth more per match than a trope pack. This picks the targets.
"""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

conn = sqlite3.connect(C.DB_PATH, timeout=600)
use = Counter()
for (t,) in conn.execute("SELECT tags FROM books WHERE tags IS NOT NULL AND tags!='[]'"):
    try:
        for s in json.loads(t):
            use[s] += 1
    except Exception:
        pass
active = {r[0] for r in conn.execute(
    "SELECT slug FROM taxonomy WHERE kind='tag' AND status='active'")}

row = conn.execute("""SELECT COUNT(*) FROM books b JOIN enrichment_state s ON s.book_id=b.id
    LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
    LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
    WHERE s.book_class='fiction' AND (b.tags IS NULL OR b.tags='[]')
      AND COALESCE(w.description,o.description) IS NOT NULL
      AND TRIM(COALESCE(w.description,o.description))!=''""").fetchone()
print(f"fiction with a description and NO tags at all: {row[0]:,}")
conn.close()

with open("logs/tag_usage.txt", "w", encoding="utf-8") as f:
    f.write(f"active tags: {len(active)}\n\nACTIVE TAGS IN USE (by count):\n")
    for s, n in use.most_common():
        if s in active:
            f.write(f"{n:>5}  {s}\n")
    unused = sorted(active - set(use))
    f.write(f"\n\nACTIVE TAGS NEVER USED ({len(unused)}):\n")
    for s in unused:
        f.write(f"    {s}\n")
print(f"active tags={len(active)}, in use={len(set(use) & active)} -> logs/tag_usage.txt")
print("\ntop 60 active tags in use:")
for s, n in [(s, n) for s, n in use.most_common() if s in active][:60]:
    print(f"  {n:>5}  {s}")
