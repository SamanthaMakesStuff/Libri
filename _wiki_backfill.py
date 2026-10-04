"""Overnight description backfill: fetch Wikipedia descriptions for active
FICTION books that currently have NO description, so they become enrichable by
the trope/tag matchers. Prioritises the genres that have deterministic packs
(mystery/thriller, romance, fantasy, sci-fi, horror) so a re-match afterward can
actually use the new text.

Reuses _wiki_fetch's proven search+verify+plot-extraction and its miss-marker
convention (a miss is stored as source='wikipedia_miss' so it is never retried).
Capped and resumable.

  python _wiki_backfill.py --cap 3000
"""
import json
import sqlite3
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C
import _wiki_fetch as W

PRIORITY_GENRES = ("Mystery", "crime", "Thriller", "Romance", "romance",
                   "Fantasy", "Sci-Fi", "Science Fiction", "Horror", "Romantasy")


def candidates(conn, limit):
    like = " OR ".join(f"b.genres LIKE '%{g}%'" for g in PRIORITY_GENRES)
    # active fiction, no usable description from any source, not already tried on Wikipedia
    rows = conn.execute(f"""SELECT b.id, b.title, b.author FROM books b
        JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source IN ('wikipedia','wikipedia_miss')
        LEFT JOIN book_metadata g ON g.book_id=b.id AND g.source='googlebooks'
        WHERE s.book_class='fiction'
          AND (b.status IS NULL OR b.status NOT LIKE 'archived%')
          AND b.author IS NOT NULL AND b.author!=''
          AND w.book_id IS NULL
          AND (o.description IS NULL OR TRIM(o.description)='')
          AND (g.description IS NULL OR TRIM(g.description)='')
          AND ({like})
        ORDER BY b.id LIMIT ?""", (limit,)).fetchall()
    return rows


def run(cap=3000):
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    rows = candidates(conn, cap)
    print(f"[backfill] {len(rows):,} description-less priority-genre fiction to try", flush=True)
    hits = 0
    for i, r in enumerate(rows, 1):
        try:
            page, kind, desc = W.best_description(r["title"], r["author"])
        except Exception:
            desc = None
        time.sleep(W.DELAY)
        if desc:
            hits += 1
            conn.execute("INSERT OR REPLACE INTO book_metadata "
                         "(book_id, source, description, subjects) VALUES (?, 'wikipedia', ?, ?)",
                         (r["id"], desc, json.dumps({"page": page, "kind": kind})))
        else:
            conn.execute("INSERT OR REPLACE INTO book_metadata "
                         "(book_id, source, description, subjects) VALUES (?, 'wikipedia_miss', '', '')",
                         (r["id"],))
        if i % 50 == 0:
            conn.commit()
            print(f"  ...{i}/{len(rows)} | {hits} descriptions found", flush=True)
    conn.commit(); conn.close()
    print(f"[backfill] DONE {hits}/{len(rows)} descriptions fetched", flush=True)
    return hits


if __name__ == "__main__":
    cap = int(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 3000
    run(cap=cap)
