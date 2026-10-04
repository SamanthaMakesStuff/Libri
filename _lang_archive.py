"""Phase 1 (overnight): decide English / non-English per book from the TITLE and
archive the confident non-English ones. Conservative by design — a wrongly
archived English book is the failure we avoid, so anything short of a clear
signal is logged 'uncertain' for the step-4 external check, never archived.

Archive = set books.status='archived_nonenglish' (reversible; the recommender
skips status LIKE 'archived%'). A full backup of every archived row is written
first, and _lang_archive.py --rollback <backup> restores them.

Signals (per title):
  * non-Latin script (Cyrillic/CJK/Arabic/Indic/…)          -> archive
  * langdetect says non-English AND a strong marker is present
    (leading non-English article, or ñ/¿/¡/ß/ã/õ)            -> archive
  * langdetect non-English but NO strong marker (proper-noun
    risk, e.g. 'Artemis Fowl' -> 'de')                       -> uncertain
  * English, or too short to tell                            -> keep

  python _lang_archive.py            # apply
  python _lang_archive.py --dry      # counts only, no writes
  python _lang_archive.py --rollback lang_archive_backup_<ts>.json
"""
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C
from _detect_lang import classify, NONLATIN

# Leading determiners that do not exist as English title articles.
ARTICLE = re.compile(
    r"^\s*(la|le|les|el|los|las|il|gli|lo|une|una|uno|uns|unas|unos|uma|umas|"
    r"der|die|das|den|dem|des|ein|eine|einen|einem|het|een|l'|d'|dell'|el|els)\b",
    re.I)
STRONG_DIACRITIC = re.compile(r"[ñ¿¡ßãõœ]", re.I)


def decision(title, author, desc):
    """Return ('archive'|'uncertain'|'keep', lang)."""
    lang, english, basis = classify(title, author, desc)
    if basis == "script":
        return ("archive", lang)                 # non-Latin, unambiguous
    if english is True:
        return ("keep", "en")
    t = title or ""
    strong = bool(ARTICLE.search(t) or STRONG_DIACRITIC.search(t))
    if english is False and strong:
        return ("archive", lang)                 # confident + strong marker
    if english is False:                          # confident lang but proper-noun risk
        return ("uncertain", lang)
    if lang not in ("en", "?") and strong:        # low-conf but strong marker
        return ("uncertain", lang)               # let step 4 confirm before archiving
    return ("keep", lang)


def rollback(path):
    rows = json.load(open(path, encoding="utf-8"))
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    for r in rows:
        conn.execute("UPDATE books SET status=? WHERE id=?",
                     (r["status"], r["id"]))
    conn.commit()
    conn.close()
    print(f"restored status on {len(rows)} books from {path}")


def run(dry=False, chunk=3000):
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM books WHERE status IS NULL OR status NOT LIKE 'archived%'")]
    total = len(ids)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[lang] scanning {total:,} books (dry={dry})", flush=True)

    tally = Counter()
    archived_rows, uncertain_rows = [], []
    for i in range(0, total, chunk):
        batch = ids[i:i + chunk]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""SELECT b.id,b.title,b.author,b.genres,b.status,
                    COALESCE(w.description,o.description) AS descr
                FROM books b
                LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
                LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
                WHERE b.id IN ({ph})""", batch).fetchall()
        for r in rows:
            act, lang = decision(r["title"], r["author"], r["descr"])
            tally[act] += 1
            if act == "archive":
                archived_rows.append({"id": r["id"], "status": r["status"],
                                      "title": r["title"], "lang": lang})
            elif act == "uncertain":
                uncertain_rows.append({"book_id": r["id"], "title": r["title"] or "",
                                       "author": r["author"] or "", "lang_guess": lang,
                                       "genres": r["genres"] or "[]"})
        print(f"  ...{min(i+chunk,total):,}/{total:,} "
              f"archive={tally['archive']:,} uncertain={tally['uncertain']:,}", flush=True)

    # write logs
    import csv
    with open("lang_uncertain.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["book_id", "title", "author", "lang_guess", "genres"])
        w.writeheader()
        w.writerows(uncertain_rows)

    # Safety cap: if detection wants to archive an implausible share of the
    # catalog, something is wrong — abort the write and leave it for review.
    rate = len(archived_rows) / max(1, total)
    if not dry and rate > 0.30:
        json.dump(archived_rows, open(f"lang_archive_ABORTED_{ts}.json", "w",
                  encoding="utf-8"), ensure_ascii=False)
        print(f"[lang] ABORT: would archive {rate:.0%} of catalog "
              f"({len(archived_rows):,}) — too high, nothing written. "
              f"See lang_archive_ABORTED_{ts}.json", flush=True)
        conn.close()
        return tally

    if not dry and archived_rows:
        backup = f"lang_archive_backup_{ts}.json"
        json.dump(archived_rows, open(backup, "w", encoding="utf-8"), ensure_ascii=False)
        for i in range(0, len(archived_rows), 500):
            part = archived_rows[i:i + 500]
            conn.executemany("UPDATE books SET status='archived_nonenglish' WHERE id=?",
                             [(r["id"],) for r in part])
        conn.commit()
        print(f"[lang] archived {len(archived_rows):,} books -> backup {backup}")
    conn.close()
    print(f"[lang] DONE keep={tally['keep']:,} archive={tally['archive']:,} "
          f"uncertain={tally['uncertain']:,} -> lang_uncertain.csv", flush=True)
    return tally


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback(sys.argv[sys.argv.index("--rollback") + 1])
    else:
        run(dry="--dry" in sys.argv)
