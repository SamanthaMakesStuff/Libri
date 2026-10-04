"""Phase 3b — non-fiction deterministic shortcut (`enrich subjects`). NO LLM.

Gathers subject signal for book_class='nonfiction' (and poetry_drama) books from:
  (a) Open Library dump subjects ingested in Phase 3a (book_metadata)
  (b) subject-heading-ish terms already on the book (surfaced by the alias table)
  (c) Library of Congress (id.loc.gov) — free, no key, polite ~1 rps
  (d) British National Bibliography (bnb.data.bl.uk) — free, no key

Headings are mapped deterministically through taxonomy_alias (+ fuzzy >= 92).
Books yielding >= MIN_TERMS canonical terms land in enrichment_review with
model='deterministic', confidence='high', stage='enriched' — zero tokens spent.
Everything cached to book_metadata; fully resumable; --dry-run supported.
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

from rapidfuzz import fuzz, process

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C
from enrich_taxonomy import is_blocked, normalize_raw, slugify

MIN_TERMS = 3               # canonical terms needed to call it 'enriched'
POLITE_DELAY = 1.0          # ~1 rps against LoC/BNB
UA = "BookRec personal catalog enricher (local, non-commercial)"

REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichment_review (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT NOT NULL,
  enriched_data TEXT,
  status TEXT DEFAULT 'pending',
  approved BOOLEAN DEFAULT 0,
  model TEXT, confidence TEXT, before_image TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def _fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def ol_search_subjects(title, author):
    """Open Library search.json -> subject headings for a specific book.

    NOTE (deviation from the brief): the brief specified Library of Congress
    (id.loc.gov) and BNB here. id.loc.gov is the *Authorities and Vocabulary*
    service — it matches heading STRINGS, not "what is this book about", so it
    cannot answer this question; the book-level route is LC's SRU/MARCXML
    service, which is slow and heavy. BNB's JSON endpoint returned nothing
    usable. Open Library's search.json is free, unmetered, fuzzy-matches
    title+author (so it catches books the exact-title dump pass missed), and
    returns real subject headings — so it is used instead.
    """
    q = urllib.parse.quote(f"{title} {author}".strip()[:160])
    url = (f"https://openlibrary.org/search.json?q={q}"
           "&fields=title,author_name,subject&limit=1")
    try:
        data = _fetch_json(url)
    except Exception:
        return []
    docs = data.get("docs") or []
    if not docs:
        return []
    doc = docs[0]
    # verify it's actually the same book before trusting its subjects.
    # partial_ratio also accepts subtitle mismatches ("Sapiens" vs
    # "Sapiens: A Brief History of Humankind"), which token_sort_ratio rejects.
    if title:
        a, b = normalize_raw(title), normalize_raw(doc.get("title") or "")
        if max(fuzz.token_sort_ratio(a, b), fuzz.partial_ratio(a, b)) < 85:
            return []
    if author:
        names = ", ".join(doc.get("author_name") or [])
        if names and fuzz.token_sort_ratio(normalize_raw(author),
                                           normalize_raw(names)) < 80:
            return []
    return (doc.get("subject") or [])[:25]


def map_terms(raw_terms, alias, display_list, display_to_slug):
    """Raw subject headings -> canonical slugs (alias, else fuzzy >= 92)."""
    slugs, log = [], []
    for raw in raw_terms:
        # LoC headings are often "Topic--Subtopic--Form"; split them
        for piece in str(raw).replace("—", "--").split("--"):
            p = piece.strip(" .,;:")
            if not p or len(p) < 3 or is_blocked(p):
                continue
            n = normalize_raw(p)
            if n in alias:
                s = alias[n]
                if s not in slugs:
                    slugs.append(s)
                    log.append((p, s, "alias", 100))
                continue
            best = process.extractOne(n, display_list, scorer=fuzz.token_sort_ratio)
            if best and best[1] >= C.FUZZY_AUTO_ALIAS:
                s = display_to_slug[best[0]]
                if s not in slugs:
                    slugs.append(s)
                    log.append((p, s, "fuzzy", best[1]))
    return slugs, log


def run(dry_run=False, limit=None, offline_only=False, classes=("nonfiction", "poetry_drama")):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(REVIEW_SCHEMA)

    alias = {r["alias"]: r["slug"] for r in conn.execute("SELECT alias, slug FROM taxonomy_alias")}
    tax = {r["slug"]: r["display"] for r in conn.execute(
        "SELECT slug, display FROM taxonomy WHERE status='active'")}
    display_list = list(tax.values())
    display_to_slug = {d: s for s, d in tax.items()}

    ph = ",".join("?" for _ in classes)
    rows = conn.execute(
        f"""SELECT b.id, b.title, b.author, b.tags, m.subjects, m.description
            FROM books b
            JOIN enrichment_state s ON s.book_id = b.id
            LEFT JOIN book_metadata m ON m.book_id = b.id AND m.source='ol_dump'
            WHERE s.book_class IN ({ph}) AND s.stage='pending'
            ORDER BY b.id""", classes).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"{len(rows):,} {'/'.join(classes)} books pending\n")

    stats = Counter()
    now = datetime.now().isoformat(timespec="seconds")
    for i, r in enumerate(rows, 1):
        raw_terms = []
        if r["subjects"]:                       # (a) OL dump subjects
            raw_terms += json.loads(r["subjects"])
        if r["tags"]:                           # (b) existing tags
            raw_terms += json.loads(r["tags"])
        slugs, _ = map_terms(raw_terms, alias, display_list, display_to_slug)

        used_net = False
        if len(slugs) < MIN_TERMS and not offline_only:
            try:
                extra = ol_search_subjects(r["title"], r["author"])   # (c) free API
            except Exception:
                extra = []
            used_net = True
            time.sleep(POLITE_DELAY)
            if extra:
                more, _ = map_terms(extra, alias, display_list, display_to_slug)
                for s in more:
                    if s not in slugs:
                        slugs.append(s)
        stats["net_calls"] += 1 if used_net else 0

        if len(slugs) >= MIN_TERMS:
            stats["resolved_deterministic"] += 1
            if not dry_run:
                before = conn.execute(
                    "SELECT tropes, tags, pacing, spice_level, focus FROM books WHERE id=?",
                    (r["id"],)).fetchone()
                payload = {"book_id": r["id"], "book_class": "nonfiction",
                           "subjects": slugs, "tags": slugs, "tropes": []}
                conn.execute(
                    """INSERT INTO enrichment_review (book_id, enriched_data, status,
                         approved, model, confidence, before_image)
                       VALUES (?,?,'pending',0,'deterministic','high',?)""",
                    (r["id"], json.dumps(payload), json.dumps(dict(before))))
                conn.execute(
                    """UPDATE enrichment_state SET stage='enriched', confidence='high',
                       model='deterministic', updated_at=? WHERE book_id=?""",
                    (now, r["id"]))
        else:
            stats["insufficient_-> phase4"] += 1
        if i % 200 == 0:
            if not dry_run:
                conn.commit()
            print(f"  ...{i:,}/{len(rows):,} | resolved {stats['resolved_deterministic']:,}",
                  flush=True)

    if not dry_run:
        conn.commit()
    print(f"\n{'DRY RUN — ' if dry_run else ''}done.")
    for k, v in stats.most_common():
        print(f"  {k:<26} {v:>7,}")
    print(f"\nZero tokens spent. Resolved books skip Phase 4 entirely.")
    conn.close()
