"""Emit priority-slice books that HAVE a description, for grounded enrichment."""
import json
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
count = int(sys.argv[2]) if len(sys.argv) > 2 else 12

c = sqlite3.connect(C.DB_PATH)
c.row_factory = sqlite3.Row
sl = json.loads((C.ROOT / "priority_slice.json").read_text(encoding="utf-8"))

grounded = []
for b in sl:
    r = c.execute("""SELECT m.description, m.subjects, s.stage, s.book_class
                     FROM book_metadata m
                     LEFT JOIN enrichment_state s ON s.book_id=m.book_id
                     WHERE m.book_id=? AND m.source='ol_dump'""", (b["id"],)).fetchone()
    if r and (r["description"] or "").strip() and r["stage"] in (None, "pending", "needs_escalation"):
        grounded.append((b, r))

print(f"# {len(grounded)} priority books have a description and are not yet enriched")
print(f"# showing {start}..{start+count}\n")
for b, r in grounded[start:start + count]:
    dlen = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    desc = " ".join((r["description"] or "").split())[:dlen]
    subs = [s for s in json.loads(r["subjects"] or "[]")][:8]
    print(f'ID: {b["id"]}')
    print(f'   TITLE : {b["title"]}  |  AUTHOR: {b["author"]}')
    print(f'   CLASS : {r["book_class"]}  |  GENRES: {b["genres"]}')
    print(f'   SUBJ  : {subs}')
    print(f'   DESC  : {desc}')
    print()
