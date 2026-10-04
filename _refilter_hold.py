"""Re-apply the (now strengthened) nonfiction guard to the held tag rows.

Reads tag_review_hold.csv, pulls each book's real description, and keeps a row
only if the book's description survives clean_desc + the strengthened
NONFICTION_SIGNAL. Much faster than re-scanning 22k books. Writes
tag_review_hold_clean.csv and reports what was dropped.
"""
import csv
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C
from _trope_match import clean_desc
from _tag_match import NONFICTION_SIGNAL

rows = list(csv.DictReader(open("tag_review_hold.csv", encoding="utf-8-sig")))
ids = sorted({r["book_id"] for r in rows})

conn = sqlite3.connect(C.DB_PATH, timeout=600)
conn.row_factory = sqlite3.Row
desc = {}
for i in range(0, len(ids), 500):
    batch = ids[i:i + 500]
    ph = ",".join("?" * len(batch))
    for r in conn.execute(
            f"""SELECT b.id, b.title, COALESCE(w.description,o.description) d
                FROM books b
                LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
                LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
                WHERE b.id IN ({ph})""", batch):
        desc[r["id"]] = (r["title"], r["d"] or "")
conn.close()

keep, dropped = [], Counter()
dropped_books = set()
for r in rows:
    title, d = desc.get(r["book_id"], ("", ""))
    cd = clean_desc(d, title)
    if cd is None or NONFICTION_SIGNAL.search(cd):
        dropped[r["tag"]] += 1
        dropped_books.add(r["book_id"])
        continue
    keep.append(r)

with open("tag_review_hold_clean.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(keep)

print(f"kept {len(keep)} rows over {len({r['book_id'] for r in keep})} books")
print(f"dropped {sum(dropped.values())} rows over {len(dropped_books)} books as nonfiction")
print("dropped by tag:", dict(dropped.most_common()))
print("kept by tag:", dict(Counter(r['tag'] for r in keep).most_common()))
