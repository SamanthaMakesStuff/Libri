"""Phase 3a — Open Library dump ingestion (`enrich ol-ingest`). No LLM, no cost.

Streams the gzipped dumps line-by-line (never loads one into memory):
  pass 1  works    -> title-match against the catalog, collect description/subjects
  pass 2  authors  -> resolve ONLY the author keys those matches need, verify >=90
  pass 3  editions -> ISBNs, earliest publish year, page count (from combined dump)

Writes: book_metadata (description/subjects/isbns/ol_work_key), and fills
books.isbn / published_year / page_count ONLY where currently NULL.
Also emits dupes_review.csv for catalog ids sharing an ISBN (never auto-merged).
Resumable at pass granularity via ol_ingest_checkpoint.json.
"""
import csv
import gzip
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C
from app import normalize_author, normalize_title

SCHEMA = """
CREATE TABLE IF NOT EXISTS book_metadata (
  book_id TEXT NOT NULL, source TEXT NOT NULL,
  description TEXT, subjects TEXT, isbns TEXT, ol_work_key TEXT,
  published_year INTEGER, page_count INTEGER,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (book_id, source));
CREATE INDEX IF NOT EXISTS idx_meta_work ON book_metadata(ol_work_key);
"""


def _gzip_ok(path):
    """Cheap integrity guard: a truncated/incomplete download must not take down
    a multi-hour run (the 17GB combined dump arrived corrupt)."""
    try:
        with gzip.open(path, "rb") as f:
            f.read(4096)
        return True
    except Exception as e:
        print(f"  gzip check failed for {getattr(path, 'name', path)}: "
              f"{type(e).__name__}: {e}")
        return False


def _author_keys(rec):
    """Extract author keys. OL uses several shapes:
       {"author": {"key": "/authors/OL1A"}} | {"author": "/authors/OL1A"}
       | {"key": "/authors/OL1A"} | "/authors/OL1A"
    """
    out = []
    for a in (rec.get("authors") or []):
        k = None
        if isinstance(a, str):
            k = a
        elif isinstance(a, dict):
            inner = a.get("author", a)
            if isinstance(inner, str):
                k = inner
            elif isinstance(inner, dict):
                k = inner.get("key")
        if isinstance(k, str) and k.startswith("/authors/"):
            out.append(k)
    return out


def _desc(obj):
    d = obj.get("description")
    if isinstance(d, dict):
        d = d.get("value")
    d = (d or "").strip()
    return d or None


def _year(s):
    import re
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(s or ""))
    return int(m.group(1)) if m else None


def iter_dump(path, want_type=None, progress_every=4_000_000, label=""):
    """Yield parsed records from a gzipped OL dump, optionally filtered by type."""
    n = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            n += 1
            if n % progress_every == 0:
                print(f"    ...{label} {n:,} lines", flush=True)
            parts = line.split("\t", 4)
            if len(parts) < 5:
                continue
            if want_type and parts[0] != want_type:
                continue
            try:
                yield json.loads(parts[4])
            except (json.JSONDecodeError, ValueError):
                continue


def editions_only(dry_run=False):
    """Run ONLY the editions pass, reusing the work->book mapping already
    persisted by a previous passes-1/2 run. Saves ~45 min of re-scanning when
    the editions dump arrives later (e.g. after a corrupt download is replaced).
    """
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    work_to_book = {r["ol_work_key"]: r["book_id"] for r in conn.execute(
        "SELECT book_id, ol_work_key FROM book_metadata "
        "WHERE source='ol_dump' AND ol_work_key IS NOT NULL")}
    if not work_to_book:
        print("No stored work->book mapping. Run `enrich ol-ingest` first.")
        return
    print(f"reusing {len(work_to_book):,} work->book mappings from book_metadata")

    if not _gzip_ok(C.OL_EDITIONS):
        print(f"{C.OL_EDITIONS.name} still unreadable — aborting (nothing changed).")
        return

    isbns, years, pages = defaultdict(set), {}, {}
    seen_e, bad_e = 0, 0
    print("editions pass...")
    for rec in iter_dump(C.OL_EDITIONS, want_type="/type/edition", label="editions"):
        seen_e += 1
        try:
            wk = None
            for w in (rec.get("works") or []):
                k = w.get("key") if isinstance(w, dict) else w
                if isinstance(k, str) and k in work_to_book:
                    wk = k
                    break
            if not wk:
                continue
            bid = work_to_book[wk]
            for f in ("isbn_13", "isbn_10"):
                for v in (rec.get(f) or []):
                    v = str(v).replace("-", "").strip()
                    if v:
                        isbns[bid].add(v)
            y = _year(rec.get("publish_date"))
            if y and (bid not in years or y < years[bid]):
                years[bid] = y
            p = rec.get("number_of_pages")
            if isinstance(p, int) and p > 0 and bid not in pages:
                pages[bid] = p
        except Exception:
            bad_e += 1
    print(f"  {seen_e:,} editions scanned (skipped {bad_e:,} malformed); "
          f"ISBNs for {len(isbns):,} books, years {len(years):,}, pages {len(pages):,}")

    if dry_run:
        print("DRY RUN — nothing written.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    for bid in set(list(isbns) + list(years) + list(pages)):
        ilist = sorted(isbns.get(bid, []))
        conn.execute("""UPDATE book_metadata SET isbns=?, published_year=?,
                        page_count=?, fetched_at=? WHERE book_id=? AND source='ol_dump'""",
                     (json.dumps(ilist), years.get(bid), pages.get(bid), now, bid))
        isbn13 = next((i for i in ilist if len(i) == 13), None) or (ilist[0] if ilist else None)
        if isbn13:
            conn.execute("UPDATE books SET isbn=? WHERE id=? AND isbn IS NULL", (isbn13, bid))
        if years.get(bid):
            conn.execute("UPDATE books SET published_year=? WHERE id=? AND published_year IS NULL",
                         (years[bid], bid))
        if pages.get(bid):
            conn.execute("UPDATE books SET page_count=? WHERE id=? AND page_count IS NULL",
                         (pages[bid], bid))
    conn.commit()
    for col in ("isbn", "published_year", "page_count"):
        n = conn.execute(f"SELECT COUNT(*) FROM books WHERE {col} IS NOT NULL").fetchone()[0]
        print(f"  books.{col:<16} now non-NULL: {n:,}")
    conn.close()


def ingest(dry_run=False, skip_editions=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    # catalog index: norm_title -> [(book_id, norm_author)]
    index = defaultdict(list)
    for r in conn.execute("SELECT id, norm_title, norm_author FROM books"):
        if r["norm_title"]:
            index[r["norm_title"]].append((r["id"], r["norm_author"] or ""))
    print(f"catalog index: {len(index):,} distinct normalised titles")

    # ---------------- pass 1: works ----------------
    print("\npass 1/3: works dump (title match)...")
    matched = {}            # work_key -> dict
    needed_authors = set()
    seen = 0
    bad = 0
    for rec in iter_dump(C.OL_WORKS, label="works"):
        seen += 1
        try:
            title = rec.get("title")
            if not title or not isinstance(title, str):
                continue
            nt = normalize_title(title)
            if nt not in index:
                continue
            akeys = _author_keys(rec)
            subs = rec.get("subjects") or []
            matched[rec.get("key")] = {
                "nt": nt, "akeys": akeys,
                "description": _desc(rec),
                "subjects": [s for s in subs if isinstance(s, str)],
            }
            needed_authors.update(akeys)
        except Exception:
            bad += 1          # one malformed record must never kill a long run
            continue
    if bad:
        print(f"  (skipped {bad:,} malformed work records)")
    print(f"  {seen:,} works scanned -> {len(matched):,} title-matched, "
          f"{len(needed_authors):,} authors to resolve")

    # ---------------- pass 2: authors ----------------
    print("\npass 2/3: authors dump (resolve names)...")
    author_name = {}
    for rec in iter_dump(C.OL_AUTHORS, label="authors"):
        k = rec.get("key")
        if k in needed_authors:
            author_name[k] = rec.get("name")
            if len(author_name) == len(needed_authors):
                break
    print(f"  resolved {len(author_name):,}/{len(needed_authors):,}")

    # confirm work -> book by fuzzy author verification (>=90)
    work_to_book, book_meta = {}, {}
    stats = Counter()
    for wk, m in matched.items():
        names = [author_name.get(k) for k in m["akeys"]]
        na_ol = normalize_author(", ".join(n for n in names if n))
        for book_id, na_cat in index[m["nt"]]:
            if na_cat and na_ol and fuzz.token_sort_ratio(na_cat, na_ol) < C.AUTHOR_VERIFY_FUZZY:
                continue
            if not na_cat or not na_ol:
                stats["author_unverified"] += 1
            work_to_book[wk] = book_id
            prev = book_meta.get(book_id, {})
            book_meta[book_id] = {
                "ol_work_key": wk,
                "description": prev.get("description") or m["description"],
                "subjects": sorted(set(prev.get("subjects", [])) | set(m["subjects"])),
            }
            stats["confirmed"] += 1
            break
    print(f"  confirmed work->book matches: {len(work_to_book):,} "
          f"covering {len(book_meta):,} distinct books")

    # ---- PERSIST NOW: descriptions/subjects are the expensive result of
    # passes 1-2 and must survive any failure in the (optional) editions pass.
    if not dry_run and book_meta:
        now0 = datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            """INSERT INTO book_metadata (book_id, source, description, subjects,
                 isbns, ol_work_key, fetched_at)
               VALUES (?,'ol_dump',?,?,'[]',?,?)
               ON CONFLICT(book_id, source) DO UPDATE SET
                 description=COALESCE(excluded.description, book_metadata.description),
                 subjects=excluded.subjects, ol_work_key=excluded.ol_work_key,
                 fetched_at=excluded.fetched_at""",
            [(bid, m.get("description"), json.dumps(m.get("subjects", [])),
              m.get("ol_work_key"), now0) for bid, m in book_meta.items()])
        conn.commit()
        print(f"  [checkpoint] persisted {len(book_meta):,} books "
              f"(descriptions/subjects) before the editions pass")

    # ---------------- pass 3: editions ----------------
    isbns = defaultdict(set)
    years, pages = {}, {}
    if not skip_editions and not _gzip_ok(C.OL_EDITIONS):
        print(f"\nSKIPPING editions: {C.OL_EDITIONS.name} is not a readable gzip "
              f"(corrupt/incomplete download). ISBNs/page-counts unavailable; "
              f"descriptions and subjects above are unaffected.")
        skip_editions = True
    if not skip_editions:
        print("\npass 3/3: editions (from combined dump — this is the slow one)...")
        seen_e = 0
        bad_e = 0
        for rec in iter_dump(C.OL_EDITIONS, want_type="/type/edition",
                             label="editions"):
            seen_e += 1
            try:
                wk = None
                for w in (rec.get("works") or []):
                    k = w.get("key") if isinstance(w, dict) else w
                    if isinstance(k, str) and k in work_to_book:
                        wk = k
                        break
                if not wk:
                    continue
                bid = work_to_book[wk]
                for f in ("isbn_13", "isbn_10"):
                    for v in (rec.get(f) or []):
                        v = str(v).replace("-", "").strip()
                        if v:
                            isbns[bid].add(v)
                y = _year(rec.get("publish_date"))
                if y and (bid not in years or y < years[bid]):
                    years[bid] = y
                p = rec.get("number_of_pages")
                if isinstance(p, int) and p > 0 and bid not in pages:
                    pages[bid] = p
                if bid in book_meta and not book_meta[bid].get("description"):
                    d = _desc(rec)
                    if d:
                        book_meta[bid]["description"] = d
            except Exception:
                bad_e += 1
                continue
        if bad_e:
            print(f"  (skipped {bad_e:,} malformed edition records)")
        print(f"  {seen_e:,} editions scanned; ISBNs for {len(isbns):,} books, "
              f"years for {len(years):,}, pages for {len(pages):,}")

    # ---------------- write-back ----------------
    if dry_run:
        print("\nDRY RUN — nothing written.")
    else:
        now = datetime.now().isoformat(timespec="seconds")
        for bid, m in book_meta.items():
            ilist = sorted(isbns.get(bid, []))
            # editions data only; descriptions/subjects were already checkpointed
            conn.execute(
                """UPDATE book_metadata SET isbns=?, published_year=?, page_count=?,
                     fetched_at=? WHERE book_id=? AND source='ol_dump'""",
                (json.dumps(ilist), years.get(bid), pages.get(bid), now, bid))
            # fill NULLs only — never overwrite existing values
            isbn13 = next((i for i in ilist if len(i) == 13), None) or (ilist[0] if ilist else None)
            if isbn13:
                conn.execute("UPDATE books SET isbn=? WHERE id=? AND isbn IS NULL",
                             (isbn13, bid))
            if years.get(bid):
                conn.execute("UPDATE books SET published_year=? WHERE id=? AND published_year IS NULL",
                             (years[bid], bid))
            if pages.get(bid):
                conn.execute("UPDATE books SET page_count=? WHERE id=? AND page_count IS NULL",
                             (pages[bid], bid))
        conn.commit()

        # duplicate report — same ISBN on two catalog ids (never auto-merge)
        byisbn = defaultdict(list)
        for r in conn.execute("SELECT id, isbn, title, author FROM books WHERE isbn IS NOT NULL"):
            byisbn[r["isbn"]].append((r["id"], r["title"], r["author"]))
        dupes = {k: v for k, v in byisbn.items() if len(v) > 1}
        if dupes:
            with open(C.DUPES_REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["isbn", "book_id", "title", "author"])
                for isbn, items in dupes.items():
                    for bid, t, a in items:
                        w.writerow([isbn, bid, t, a])
        print(f"\nduplicate ISBNs across catalog ids: {len(dupes):,} "
              f"-> {C.DUPES_REVIEW_CSV.name}")

    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    print("\n=== ingestion report ===")
    print(f"  catalog matched:        {len(book_meta):,} / {total:,} "
          f"({len(book_meta)/total*100:.1f}%)")
    print(f"  gained description:     {sum(1 for m in book_meta.values() if m.get('description')):,}")
    print(f"  gained subjects:        {sum(1 for m in book_meta.values() if m.get('subjects')):,}")
    print(f"  gained ISBNs:           {len(isbns):,}")
    if not dry_run:
        for col in ("isbn", "published_year", "page_count"):
            n = conn.execute(f"SELECT COUNT(*) FROM books WHERE {col} IS NOT NULL").fetchone()[0]
            print(f"  books.{col:<16} now non-NULL: {n:,}")
    conn.close()
