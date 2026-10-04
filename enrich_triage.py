"""Phase 2 — triage (`enrich triage`).

Populate enrichment_state for every book: classify book_class from the existing
genres array with a deterministic rule table, and decide needs_enrichment.
Books already carrying >=3 canonical tropes AND >=3 canonical tags AND pacing
are marked stage='skipped' (still eligible for a later top-up run).
Idempotent: re-running re-triages without duplicating rows.
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C

POETRY_DRAMA = {"Poetry", "Drama"}
CHILDRENS = {"Children's", "Childrens", "Children"}
# genres that are age-categories/forms, not enough on their own to call fiction
NEUTRAL = {"Young Adult", "Short Stories", "Graphic Novel", "Anthology"}


def classify(genres):
    """genres list -> book_class per the brief's rule table."""
    g = {str(x).strip() for x in genres if x}
    if not g:
        return "ambiguous"
    if g & CHILDRENS:
        return "childrens"
    fiction = g & C.FICTION_GENRES
    nonfiction = g & C.NONFICTION_GENRES
    if (g & POETRY_DRAMA) and not fiction:
        return "poetry_drama"
    if nonfiction and not fiction:
        return "nonfiction"
    if fiction and not nonfiction:
        return "fiction"
    if fiction and nonfiction:
        return "ambiguous"          # e.g. History|Literary Fiction
    if g & NEUTRAL:
        return "ambiguous"
    return "ambiguous"


def triage(dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row

    trope_slugs = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE kind='trope' AND status='active'")}
    active = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE status='active'")}

    census, skip_reasons = Counter(), Counter()
    rows = conn.execute(
        "SELECT id, genres, tropes, tags, pacing FROM books").fetchall()
    now = datetime.now().isoformat(timespec="seconds")

    payload = []
    for r in rows:
        genres = json.loads(r["genres"] or "[]")
        klass = classify(genres)
        tropes = [t for t in json.loads(r["tropes"] or "[]") if t in trope_slugs]
        tags = [t for t in json.loads(r["tags"] or "[]") if t in active]

        well_covered = (len(tropes) >= 3 and len(tags) >= 3 and bool(r["pacing"]))
        needs = 0 if well_covered else 1
        stage = "skipped" if well_covered else "pending"

        census[klass] += 1
        if well_covered:
            skip_reasons[klass] += 1
        payload.append((r["id"], klass, needs, stage, now))

    if not dry_run:
        conn.executemany(
            """INSERT INTO enrichment_state (book_id, book_class, needs_enrichment,
                 stage, updated_at) VALUES (?,?,?,?,?)
               ON CONFLICT(book_id) DO UPDATE SET
                 book_class=excluded.book_class,
                 needs_enrichment=excluded.needs_enrichment,
                 stage=CASE WHEN enrichment_state.stage IN
                       ('enriched','grounded','promoted','unverifiable')
                       THEN enrichment_state.stage ELSE excluded.stage END,
                 updated_at=excluded.updated_at""", payload)
        conn.commit()

    total = len(rows)
    print(f"{'DRY RUN — ' if dry_run else ''}triaged {total:,} books\n")
    print("=== census by book_class ===")
    for k, n in census.most_common():
        skipped = skip_reasons.get(k, 0)
        print(f"  {k:<14} {n:>7,}  ({n/total*100:4.1f}%)   already-covered/skipped: {skipped:,}")
    need = sum(census.values()) - sum(skip_reasons.values())
    print(f"\nneeds_enrichment: {need:,}  |  skipped (already well covered): "
          f"{sum(skip_reasons.values()):,}")

    # what the LLM phase would actually cost, by class
    print("\n=== Phase 4 scope implication ===")
    fiction_like = census["fiction"] + census["childrens"] + census["ambiguous"]
    print(f"  fiction/childrens/ambiguous (get tropes): {fiction_like:,}")
    print(f"  nonfiction/poetry_drama (subjects+moods only): "
          f"{census['nonfiction'] + census['poetry_drama']:,}")

    if not dry_run:
        print("\n=== enrichment_state by stage ===")
        for r in conn.execute("SELECT stage, COUNT(*) n FROM enrichment_state "
                              "GROUP BY stage ORDER BY n DESC"):
            print(f"  {r['stage']:<14} {r['n']:>7,}")
    conn.close()
