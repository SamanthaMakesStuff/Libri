"""Phase 1 — clean existing book data (`enrich clean`).

Normalisation only (no generation): re-map every tropes/tags element through
taxonomy_alias, drop blocklisted junk, slugify the rest, dedupe, and put each
concept in exactly one field (trope-kind slugs in `tropes`, everything else in
`tags`). Pacing values that leaked into tags are moved to the `pacing` column.

Every changed book is logged to clean_log.jsonl (with a before-image, so the
change is auditable and reversible). --dry-run prints a diff sample and writes
nothing.
"""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C
from enrich_taxonomy import is_blocked, normalize_raw, slugify

# tag values that are really `pacing` column values
PACING_TAGS = {"fast-paced": "Fast", "fast paced": "Fast", "fastpaced": "Fast",
               "medium-paced": "Medium", "medium paced": "Medium",
               "slow-paced": "Slow", "slow paced": "Slow", "slowpaced": "Slow"}


def clean(dry_run=False, sample=12):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row

    alias = {r["alias"]: r["slug"] for r in
             conn.execute("SELECT alias, slug FROM taxonomy_alias")}
    kind = {r["slug"]: r["kind"] for r in
            conn.execute("SELECT slug, kind FROM taxonomy")}

    def resolve(raw):
        """raw term -> canonical slug, or None if it should be dropped."""
        n = normalize_raw(raw)
        if n in alias:
            return alias[n]
        if is_blocked(raw):
            return None
        s = slugify(raw)
        return s or None

    stats = Counter()
    changed_rows, samples = 0, []
    # append, never truncate: a re-run must not destroy earlier before-images
    logf = None if dry_run else open(C.CLEAN_LOG, "a", encoding="utf-8")

    rows = conn.execute(
        "SELECT id, tropes, tags, pacing FROM books "
        "WHERE tropes != '[]' OR tags != '[]'").fetchall()
    print(f"scanning {len(rows):,} books that have tropes/tags...")

    for r in rows:
        before_tropes = json.loads(r["tropes"] or "[]")
        before_tags = json.loads(r["tags"] or "[]")
        pacing = r["pacing"]

        tropes, tags = [], []
        for raw in before_tropes + before_tags:
            if not isinstance(raw, str) or not raw.strip():
                continue
            n = normalize_raw(raw)
            if n in PACING_TAGS:                      # pacing lives in its own column
                if not pacing:
                    pacing = PACING_TAGS[n]
                    stats["pacing_filled"] += 1
                stats["pacing_tag_moved"] += 1
                continue
            slug = resolve(raw)
            if slug is None:
                stats["dropped_junk"] += 1
                continue
            # each concept in exactly one field, decided by its taxonomy kind
            target = tropes if kind.get(slug) == "trope" else tags
            if slug not in target:
                target.append(slug)

        stats["books_scanned"] += 1
        if (tropes != before_tropes or tags != before_tags
                or pacing != r["pacing"]):
            changed_rows += 1
            if len(samples) < sample:
                samples.append((r["id"], before_tropes, before_tags,
                                tropes, tags, r["pacing"], pacing))
            if not dry_run:
                logf.write(json.dumps({
                    "book_id": r["id"],
                    "before": {"tropes": before_tropes, "tags": before_tags,
                               "pacing": r["pacing"]},
                    "after": {"tropes": tropes, "tags": tags, "pacing": pacing},
                }) + "\n")
                conn.execute(
                    "UPDATE books SET tropes=?, tags=?, pacing=? WHERE id=?",
                    (json.dumps(tropes), json.dumps(tags), pacing, r["id"]))

    if not dry_run:
        conn.commit()
        logf.close()

    print(f"\n{'DRY RUN — ' if dry_run else ''}books changed: {changed_rows:,}"
          f" of {len(rows):,}")
    for k, v in stats.most_common():
        print(f"  {k:<20} {v:>8,}")

    print(f"\n=== diff sample ({len(samples)}) ===")
    for bid, bt, bg, at, ag, bp, ap in samples:
        print(f"\n  {bid}")
        print(f"    tropes: {bt[:5]}\n         -> {at[:5]}")
        print(f"    tags:   {bg[:6]}\n         -> {ag[:6]}")
        if bp != ap:
            print(f"    pacing: {bp} -> {ap}")

    # post-conditions worth proving
    if not dry_run:
        raw_left = 0
        for r in conn.execute("SELECT tropes, tags FROM books"):
            for v in json.loads(r["tropes"] or "[]") + json.loads(r["tags"] or "[]"):
                if v != slugify(v):
                    raw_left += 1
        print(f"\nnon-slug terms remaining in books: {raw_left}")
        n_pacing = conn.execute(
            "SELECT COUNT(*) FROM books WHERE pacing IS NOT NULL").fetchone()[0]
        print(f"books with pacing: {n_pacing:,}")
    conn.close()
