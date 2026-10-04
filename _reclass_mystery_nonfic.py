"""Find mystery/crime/thriller books that are actually NON-FICTION and fix them.

All 5,449 are currently classed 'fiction' (they carry a crime genre label), but a
chunk are true-crime, criminology, memoirs, or scholarship about the genre.

Precision-first, because flipping a real novel to nonfiction is exactly the kind
of error to avoid (The Housemaid, a bestselling thriller, has a housekeeping
manual's subjects attached by a metadata mismatch):

  FLIP to nonfiction only when ALL hold:
    1. subjects contain a DECISIVE scholarly/biographical marker
       (biography, memoir, 'history and criticism', 'case studies', ...)
    2. subjects contain NO fiction marker (fiction / novel / stories / comic)
    3. the description, if present, contains NO fiction cue ('novel',
       'fictional', 'novella') - this is what vetoes the graphic-novel case
  A book with NO description AND only a weak marker (handbooks, home economics)
  is NOT flipped - that's the wrong-book-metadata trap; it goes to review.

Output: auto-flips the confident set, writes the rest to
mystery_reclass_review.csv for a human call. Reversible via a backup.

  python _reclass_mystery_nonfic.py --dry-run
  python _reclass_mystery_nonfic.py
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

DRY = "--dry-run" in sys.argv

DECISIVE_NF = ("biography", "autobiography", "autobiographies", "memoir",
               "criticism and interpretation", "history and criticism",
               "case studies", "study and teaching", "personal narratives",
               "historiography", "biographies")
WEAK_NF = ("handbooks", "manuals", "essays", "sources", "correspondence",
           "encyclopedias", "dictionaries", "true crime", "interviews",
           "anecdotes", "history", "politics and government", "social conditions")
FIC_SUBJ = ("fiction", "novel", "novels", "stories", "comic", "graphic novel",
            "romans", "fictional")
FIC_DESC = re.compile(r"\b(novel|novella|fictional|novelist)\b", re.I)


def has(keys, text):
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in keys)


conn = sqlite3.connect(C.DB_PATH, timeout=180)
conn.row_factory = sqlite3.Row
GEN = ("(b.genres LIKE '%Mystery%' OR b.genres LIKE '%crime%' "
       "OR b.genres LIKE '%Thriller%' OR b.genres LIKE '%mystery%')")
rows = conn.execute(f"""SELECT b.id, b.title, m.subjects, m.description, s.book_class
                        FROM books b JOIN enrichment_state s ON s.book_id=b.id
                        LEFT JOIN book_metadata m ON m.book_id=b.id AND m.source='ol_dump'
                        WHERE {GEN} AND s.book_class != 'nonfiction'""").fetchall()

flips, review = [], []
stats = Counter()
for r in rows:
    subs = " || ".join(str(x).lower() for x in json.loads(r["subjects"] or "[]"))
    desc = r["description"] or ""
    if not subs:
        stats["no_subjects"] += 1
        continue

    fic_subj = has(FIC_SUBJ, subs)
    fic_desc = bool(FIC_DESC.search(desc))
    decisive = has(DECISIVE_NF, subs)
    weak = sum(1 for k in WEAK_NF if re.search(r"\b" + re.escape(k) + r"\b", subs))

    if fic_subj or fic_desc:
        stats["kept_fiction_signal"] += 1
        continue

    if decisive:
        flips.append((r["id"], r["title"], subs[:80]))
        stats["flip_decisive"] += 1
    elif weak >= 2 and desc:
        # weak markers WITH a description we can't veto -> borderline, review it
        review.append((r["id"], r["title"], subs[:90],
                       " ".join(desc.split())[:160]))
        stats["review_weak_with_desc"] += 1
    elif weak >= 1 and not desc:
        # weak marker, no description = classic wrong-book-metadata trap -> review
        review.append((r["id"], r["title"], subs[:90], "(no description)"))
        stats["review_weak_no_desc"] += 1
    else:
        stats["left_fiction"] += 1

if not DRY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (C.ROOT / f"mystery_reclass_backup_{ts}.json").write_text(
        json.dumps([{"id": i, "was": "fiction"} for i, _, _ in flips]),
        encoding="utf-8")
    for bid, _, _ in flips:
        conn.execute("UPDATE enrichment_state SET book_class='nonfiction' WHERE book_id=?", (bid,))
    conn.commit()
    with open("mystery_reclass_review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["decision(nonfiction/blank)", "book_id", "title", "subjects", "description"])
        for bid, t, s, d in review:
            w.writerow(["", bid, t, s, d])
    print(f"backup -> mystery_reclass_backup_{ts}.json")
    print(f"review list -> mystery_reclass_review.csv ({len(review)} rows)")

print(f"\n{'DRY RUN - ' if DRY else ''}scanned {len(rows):,} mystery/crime/thriller books")
for k, v in stats.most_common():
    print(f"  {k:<24} {v:>6,}")
print(f"\n  -> auto-flip to nonfiction: {len(flips):,}")
print(f"  -> held for review        : {len(review):,}")
print("\n  sample auto-flips:")
for _, t, s in flips[:10]:
    print(f"     {t[:40]:<42} {s}")
conn.close()
