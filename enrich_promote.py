"""Phase 7 — promote (`enrich promote`).

Applies approved enrichment_review rows to `books`:
  * UNION arrays (tropes/tags/content_warnings) — existing data is never deleted
  * pacing/focus/spice filled ONLY when currently NULL
  * books.source set to 'enrichment_llm' (existing 'reclassified' rows keep theirs
    unless this run actually changes them)
  * review row marked approved, enrichment_state.stage='promoted'

Selection:
  --auto-approve            promote confidence='high' rows
  --include-medium          also promote confidence='medium'
  --decisions review.csv    honour a human-edited `decision` column
                            (approve / reject; blank = leave pending)

Reversal:
  --rollback <run_id>       restore every book touched by that run from its
                            stored before_image, and return rows to pending.
  --list-runs               show previous promote runs
"""
import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C

ARRAY_FIELDS = ("tropes", "tags", "content_warnings")


def _ensure_columns(conn):
    cols = {c[1] for c in conn.execute("PRAGMA table_info(enrichment_review)")}
    for name, decl in [("promote_run", "TEXT"), ("promoted_at", "TEXT")]:
        if name not in cols:
            conn.execute(f"ALTER TABLE enrichment_review ADD COLUMN {name} {decl}")
    conn.commit()


def _union(existing_json, new_list):
    cur = json.loads(existing_json or "[]")
    seen = {str(x).strip().lower() for x in cur}
    added = 0
    for v in new_list or []:
        if str(v).strip().lower() not in seen:
            cur.append(v)
            seen.add(str(v).strip().lower())
            added += 1
    return cur, added


def list_runs():
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_columns(conn)
    rows = conn.execute("""SELECT promote_run, COUNT(*) n, MIN(promoted_at) at
                           FROM enrichment_review WHERE promote_run IS NOT NULL
                           GROUP BY promote_run ORDER BY at DESC""").fetchall()
    if not rows:
        print("no promote runs yet")
    for r in rows:
        print(f"  {r['promote_run']}   {r['n']:>6} books   {r['at']}")
    conn.close()


def rollback(run_id, dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_columns(conn)
    rows = conn.execute("""SELECT book_id, before_image FROM enrichment_review
                           WHERE promote_run=?""", (run_id,)).fetchall()
    if not rows:
        print(f"no rows for run {run_id!r}")
        return
    print(f"{'DRY RUN — ' if dry_run else ''}rolling back {len(rows):,} books "
          f"from run {run_id}")
    if dry_run:
        return
    for r in rows:
        b = json.loads(r["before_image"] or "{}")
        conn.execute("""UPDATE books SET tropes=?, tags=?, pacing=?, spice_level=?,
                          focus=?, content_warnings=? WHERE id=?""",
                     (b.get("tropes", "[]"), b.get("tags", "[]"), b.get("pacing"),
                      b.get("spice_level"), b.get("focus"),
                      b.get("content_warnings", "[]"), r["book_id"]))
        conn.execute("""UPDATE enrichment_review SET status='pending', approved=0,
                          promote_run=NULL, promoted_at=NULL WHERE book_id=?""",
                     (r["book_id"],))
        conn.execute("""UPDATE enrichment_state SET stage='enriched' WHERE book_id=?""",
                     (r["book_id"],))
    conn.commit()
    print("rollback complete — books restored to their pre-promotion values")
    conn.close()


def promote(auto_approve=False, include_medium=False, decisions_csv=None,
            dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_columns(conn)

    decisions = {}
    if decisions_csv:
        for row in csv.DictReader(open(decisions_csv, encoding="utf-8-sig")):
            d = (row.get("decision") or "").strip().lower()
            if d:
                decisions[row["book_id"]] = d
        print(f"loaded {len(decisions)} human decisions from {decisions_csv}")

    rows = conn.execute("""SELECT book_id, enriched_data, confidence
                           FROM enrichment_review WHERE status='pending'""").fetchall()
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    now = datetime.now().isoformat(timespec="seconds")
    stats = Counter()
    added_tot = Counter()

    for r in rows:
        bid = r["book_id"]
        d = json.loads(r["enriched_data"] or "{}")
        decision = decisions.get(bid)

        if decision == "reject":
            stats["rejected"] += 1
            if not dry_run:
                conn.execute("""UPDATE enrichment_review SET status='rejected'
                                WHERE book_id=?""", (bid,))
                conn.execute("""UPDATE enrichment_state SET stage='skipped'
                                WHERE book_id=?""", (bid,))
            continue
        if decision != "approve":
            ok = (auto_approve and (r["confidence"] == "high" or
                                    (include_medium and r["confidence"] == "medium")))
            if not ok:
                stats["left_pending"] += 1
                continue
        if not d.get("known", True):
            stats["skipped_unknown_book"] += 1
            continue

        cur = conn.execute("""SELECT tropes, tags, content_warnings, pacing,
                                spice_level, focus FROM books WHERE id=?""",
                           (bid,)).fetchone()
        if cur is None:
            stats["missing_book"] += 1
            continue

        new_vals, changed = {}, False
        for f in ARRAY_FIELDS:
            merged, added = _union(cur[f], d.get(f))
            new_vals[f] = json.dumps(merged, ensure_ascii=False)
            if added:
                changed = True
                added_tot[f] += added
        # scalar fields fill NULLs only
        for f, key in (("pacing", "pacing"), ("focus", "focus"),
                       ("spice_level", "spice_level")):
            val = cur[f]
            if (val is None or val == "" or (f == "spice_level" and val == "N/A")) \
                    and d.get(key):
                new_vals[f] = d[key]
                changed = True
                added_tot[f] += 1
            else:
                new_vals[f] = val

        if not dry_run:
            conn.execute("""UPDATE books SET tropes=?, tags=?, content_warnings=?,
                              pacing=?, spice_level=?, focus=?, source='enrichment_llm'
                            WHERE id=?""",
                         (new_vals["tropes"], new_vals["tags"],
                          new_vals["content_warnings"], new_vals["pacing"],
                          new_vals["spice_level"], new_vals["focus"], bid))
            conn.execute("""UPDATE enrichment_review SET status='approved', approved=1,
                              promote_run=?, promoted_at=? WHERE book_id=?""",
                         (run_id, now, bid))
            conn.execute("""UPDATE enrichment_state SET stage='promoted' WHERE book_id=?""",
                         (bid,))
        stats["promoted" if changed else "promoted_no_change"] += 1

    if not dry_run:
        conn.commit()
    print(f"\n{'DRY RUN — ' if dry_run else ''}run {run_id}")
    for k, v in stats.most_common():
        print(f"  {k:<24} {v:>6,}")
    if added_tot:
        print("\n  values added:")
        for k, v in added_tot.most_common():
            print(f"    {k:<20} {v:>6,}")
    if not dry_run and stats.get("promoted"):
        print(f"\n  rollback with:  python enrich.py promote --rollback {run_id}")
    conn.close()
