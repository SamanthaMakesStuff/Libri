"""Apply taxonomy_decisions.csv -> taxonomy_alias / taxonomy.

accept        -> alias(raw) = suggested_slug
remap:<slug>  -> alias(raw) = <slug>   (validated against active taxonomy)
reject        -> raw becomes its own status='proposed' term (nothing is lost)
Idempotent: safe to re-run.
"""
import csv
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C
from enrich_taxonomy import normalize_raw, slugify

DECISIONS_CSV = C.ROOT / "taxonomy_decisions.csv"


def apply_decisions(dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    active = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE status='active'")}

    rows = list(csv.DictReader(open(DECISIONS_CSV, encoding="utf-8")))
    stats, bad_targets, created_targets = Counter(), [], []

    for r in rows:
        raw, decision = r["raw_term"], r["decision"].strip()
        norm = normalize_raw(raw)
        if decision == "accept":
            target = r["suggested_slug"]
        elif decision.startswith("remap:"):
            target = decision.split(":", 1)[1].strip()
        else:                                   # reject -> own proposed term
            if not dry_run:
                conn.execute(
                    """INSERT OR IGNORE INTO taxonomy (slug, display, kind, applies_to,
                       status, source) VALUES (?,?,'tag','both','proposed','existing_data')""",
                    (slugify(raw), raw))
                conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                             " VALUES (?,?,'new_proposed',?)", (raw, slugify(raw), r["score"]))
            stats["reject->proposed"] += 1
            continue

        if target not in active:
            # A remap target you specified that doesn't exist yet is an explicit
            # vocabulary addition — create it as active, don't silently drop it.
            if decision.startswith("remap:"):
                display = target.replace("-", " ")
                kind = ("subgenre" if any(g in target for g in
                        ("romance", "thriller", "fantasy", "mystery", "horror",
                         "fiction", "sci-fi", "scifi")) else "tag")
                if not dry_run:
                    conn.execute(
                        """INSERT OR IGNORE INTO taxonomy (slug, display, kind,
                           applies_to, status, source)
                           VALUES (?,?,?,'fiction','active','user_review')""",
                        (target, display, kind))
                active.add(target)
                created_targets.append((target, kind))
            else:
                bad_targets.append((raw, decision, target))
                stats["INVALID_TARGET"] += 1
                continue
        if not dry_run:
            conn.execute("INSERT OR REPLACE INTO taxonomy_alias VALUES (?,?)", (norm, target))
            conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                         " VALUES (?,?,?,?)",
                         (raw, target, "remap_approved" if decision.startswith("remap")
                          else "alias_approved", r["score"]))
        stats["remap" if decision.startswith("remap") else "accept"] += 1

    if not dry_run:
        conn.commit()

    print(f"{'DRY RUN — ' if dry_run else ''}applied {len(rows)} decisions:")
    for k, v in stats.most_common():
        print(f"  {k:<18} {v:>5}")
    if created_targets:
        print("\nNEW taxonomy terms created from your remap targets:")
        for tgt, kind in created_targets:
            print(f"  {tgt:<28} kind={kind}  (status=active, source=user_review)")
    if bad_targets:
        print("\nINVALID remap targets (slug not active in taxonomy):")
        for raw, dec, tgt in bad_targets:
            print(f"  {raw!r} -> {tgt!r} ({dec})")
    n_alias = conn.execute("SELECT COUNT(*) FROM taxonomy_alias").fetchone()[0]
    print(f"\ntaxonomy_alias now: {n_alias:,} entries")
    conn.close()
    return len(bad_targets) == 0
