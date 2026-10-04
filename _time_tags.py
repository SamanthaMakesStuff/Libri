"""Find the slow step: time clean_desc and each regex over a small sample,
flushing immediately and flagging any single description that is slow."""
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C
import _tag_match as T
from _trope_match import clean_desc

conn = sqlite3.connect(C.DB_PATH, timeout=600)
rows = conn.execute("""SELECT b.id, b.title, COALESCE(w.description,o.description) d
    FROM books b JOIN enrichment_state s ON s.book_id=b.id
    LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
    LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
    WHERE s.book_class='fiction' AND (b.tags IS NULL OR b.tags='[]')
      AND COALESCE(w.description,o.description) IS NOT NULL
    LIMIT 800""").fetchall()
conn.close()
print(f"fetched {len(rows)} rows", flush=True)

# 1) time clean_desc per book, flag slow ones
t0 = time.time()
descs = []
for bid, title, d in rows:
    ts = time.time()
    cd = clean_desc(d, title)
    dt = time.time() - ts
    if dt > 0.2:
        print(f"  SLOW clean_desc {dt:.2f}s  {bid}  len(desc)={len(d)}  {title[:40]}", flush=True)
    if cd:
        descs.append(cd)
print(f"clean_desc total {time.time()-t0:.2f}s -> {len(descs)} kept", flush=True)

# 2) time each regex over the kept descriptions
comp = T.build_comp()
for slug, (rx, tier) in comp.items():
    t0 = time.time()
    for d in descs:
        rx.search(d)
    dt = time.time() - t0
    print(f"  {dt:7.3f}s  {slug}", flush=True)
print("done", flush=True)
