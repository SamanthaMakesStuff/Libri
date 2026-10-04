"""Activate reviewed community vocabulary (`enrich vocab-apply`).

Reads vocab_decisions_final.csv (slug, kind) and:
  * kind in trope/tag/mood/subject -> taxonomy row becomes status='active'
    with that kind, source='user_review'
  * kind == 'drop'                 -> status='rejected'; the term is stripped
                                      from every book's tropes/tags
Then re-files each book's terms so a slug now classed as a trope moves from
`tags` into `tropes` (Phase 1's rule, re-applied for the newly-active terms).

Idempotent; --dry-run supported.
"""
import csv
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C

DECISIONS = C.ROOT / "vocab_decisions_final.csv"


def apply_vocab(dry_run=False, hold=()):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = list(csv.DictReader(open(DECISIONS, encoding="utf-8-sig")))
    decided, dropped = {}, set()
    held = []
    for r in rows:
        slug, kind = r["slug"].strip(), r["kind"].strip().lower()
        if slug in hold:
            held.append((slug, kind))
            continue
        if kind == "drop":
            dropped.add(slug)
        elif kind in ("trope", "tag", "mood", "subject", "warning"):
            decided[slug] = kind

    print(f"{len(decided)} terms to activate, {len(dropped)} to drop")
    if held:
        print(f"HELD (not applied, awaiting confirmation): "
              f"{', '.join(s + '=' + k for s, k in held)}")

    if not dry_run:
        for slug, kind in decided.items():
            conn.execute(
                """INSERT INTO taxonomy (slug, display, kind, applies_to, status, source)
                   VALUES (?,?,?,'both','active','user_review')
                   ON CONFLICT(slug) DO UPDATE SET
                     kind=excluded.kind, status='active', source='user_review'""",
                (slug, slug.replace("-", " "), kind))
        for slug in dropped:
            conn.execute("""UPDATE taxonomy SET status='rejected' WHERE slug=?""", (slug,))
        conn.commit()

    # ---- re-file terms on every book according to the new kinds ----------
    # Merge the decisions over the DB kinds so --dry-run reflects the same
    # state a real run would produce (the taxonomy writes above are skipped
    # when dry-running, so reading the DB alone would report stale kinds).
    kinds = {r["slug"]: r["kind"] for r in
             conn.execute("SELECT slug, kind FROM taxonomy WHERE status='active'")}
    kinds.update(decided)
    stats = Counter()
    changed = 0
    for r in conn.execute("SELECT id, tropes, tags FROM books").fetchall():
        old_tr = json.loads(r["tropes"] or "[]")
        old_tg = json.loads(r["tags"] or "[]")
        tr, tg = [], []
        for t in old_tr + old_tg:
            if t in dropped:
                stats["dropped_terms"] += 1
                continue
            target = tr if kinds.get(t) == "trope" else tg
            if t not in target:
                target.append(t)
        if tr != old_tr or tg != old_tg:
            changed += 1
            moved = len(set(tr) - set(old_tr))
            stats["books_changed"] += 1
            stats["terms_promoted_to_trope"] += moved
            if not dry_run:
                conn.execute("UPDATE books SET tropes=?, tags=? WHERE id=?",
                             (json.dumps(tr, ensure_ascii=False),
                              json.dumps(tg, ensure_ascii=False), r["id"]))
    if not dry_run:
        conn.commit()

    print(f"\n{'DRY RUN — ' if dry_run else ''}re-filed vocabulary:")
    for k, v in stats.most_common():
        print(f"  {k:<28} {v:>8,}")

    n_trope_books = conn.execute(
        "SELECT COUNT(*) FROM books WHERE tropes != '[]'").fetchone()[0]
    print(f"\nbooks with at least one trope: {n_trope_books:,}")
    conn.close()
