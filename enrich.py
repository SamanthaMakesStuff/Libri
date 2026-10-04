#!/usr/bin/env python3
"""Catalog enrichment pipeline — one entrypoint, one subcommand per phase.

  python enrich.py taxonomy-build [--dry-run]     # Phase 0
  python enrich.py status                          # pipeline census (any time)

Later phases (clean, triage, ol-ingest, subjects, run, ground, escalate,
canonicalise, promote, pilot, report) are added as each phase is built and gated.
"""
import argparse
import sqlite3
import sys

import config as C


def cmd_taxonomy_build(args):
    import enrich_taxonomy
    enrich_taxonomy.build(dry_run=args.dry_run)


def cmd_taxonomy_apply(args):
    import enrich_apply
    enrich_apply.apply_decisions(dry_run=args.dry_run)


def cmd_clean(args):
    import enrich_clean
    enrich_clean.clean(dry_run=args.dry_run)


def cmd_triage(args):
    import enrich_triage
    enrich_triage.triage(dry_run=args.dry_run)


def cmd_ol_ingest(args):
    import enrich_ol
    if args.editions_only:
        enrich_ol.editions_only(dry_run=args.dry_run)
    else:
        enrich_ol.ingest(dry_run=args.dry_run, skip_editions=args.skip_editions)


def cmd_subjects(args):
    import enrich_subjects
    enrich_subjects.run(dry_run=args.dry_run, limit=args.limit,
                        offline_only=args.offline_only)


def cmd_priority(args):
    import enrich_priority
    enrich_priority.build(limit=args.limit, dry_run=args.dry_run)


def cmd_promote(args):
    import enrich_promote
    if args.list_runs:
        enrich_promote.list_runs()
    elif args.rollback:
        enrich_promote.rollback(args.rollback, dry_run=args.dry_run)
    else:
        enrich_promote.promote(auto_approve=args.auto_approve,
                               include_medium=args.include_medium,
                               decisions_csv=args.decisions,
                               dry_run=args.dry_run)


def cmd_canonicalise(args):
    import enrich_canonicalise
    if args.apply:
        enrich_canonicalise.apply(args.apply, dry_run=args.dry_run)
    else:
        enrich_canonicalise.review(min_freq=args.min_freq, out=args.out)


def cmd_vocab_apply(args):
    import enrich_vocab
    enrich_vocab.apply_vocab(dry_run=args.dry_run,
                             hold=set(args.hold.split(",")) if args.hold else ())


def cmd_status(args):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    print(f"books: {conn.execute('SELECT COUNT(*) FROM books').fetchone()[0]:,}")
    if "taxonomy" in have:
        print("\ntaxonomy by kind/status:")
        for r in conn.execute("SELECT kind, status, COUNT(*) n FROM taxonomy "
                              "GROUP BY kind, status ORDER BY n DESC"):
            print(f"  {r['kind']:<10} {r['status']:<9} {r['n']:>6}")
        print(f"aliases: {conn.execute('SELECT COUNT(*) FROM taxonomy_alias').fetchone()[0]:,}")
    if "enrichment_state" in have:
        print("\nenrichment_state by stage:")
        for r in conn.execute("SELECT stage, COUNT(*) n FROM enrichment_state "
                              "GROUP BY stage ORDER BY n DESC"):
            print(f"  {r['stage']:<18} {r['n']:>6}")
    conn.close()


def main():
    p = argparse.ArgumentParser(prog="enrich", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    tb = sub.add_parser("taxonomy-build", help="Phase 0: compile the taxonomy")
    tb.add_argument("--dry-run", action="store_true")
    tb.set_defaults(func=cmd_taxonomy_build)

    ta = sub.add_parser("taxonomy-apply", help="Phase 0 gate: apply taxonomy_decisions.csv")
    ta.add_argument("--dry-run", action="store_true")
    ta.set_defaults(func=cmd_taxonomy_apply)

    cl = sub.add_parser("clean", help="Phase 1: normalise existing book vocabulary")
    cl.add_argument("--dry-run", action="store_true")
    cl.set_defaults(func=cmd_clean)

    tr = sub.add_parser("triage", help="Phase 2: classify books, populate enrichment_state")
    tr.add_argument("--dry-run", action="store_true")
    tr.set_defaults(func=cmd_triage)

    oi = sub.add_parser("ol-ingest", help="Phase 3a: ingest Open Library dumps (free)")
    oi.add_argument("--dry-run", action="store_true")
    oi.add_argument("--skip-editions", action="store_true",
                    help="skip the slow 17GB combined-dump editions pass")
    oi.add_argument("--editions-only", action="store_true",
                    help="run ONLY the editions pass, reusing the stored work->book map")
    oi.set_defaults(func=cmd_ol_ingest)

    sj = sub.add_parser("subjects", help="Phase 3b: deterministic non-fiction subjects (free)")
    sj.add_argument("--dry-run", action="store_true")
    sj.add_argument("--limit", type=int)
    sj.add_argument("--offline-only", action="store_true",
                    help="use only local/dump signal, no LoC/BNB network calls")
    sj.set_defaults(func=cmd_subjects)

    pr = sub.add_parser("priority", help="Step 3: rank the books worth enriching first")
    pr.add_argument("--limit", type=int, default=1000)
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_priority)

    pm = sub.add_parser("promote", help="Phase 7: apply approved enrichment to books")
    pm.add_argument("--auto-approve", action="store_true")
    pm.add_argument("--include-medium", action="store_true")
    pm.add_argument("--decisions", help="CSV with a human-edited decision column")
    pm.add_argument("--rollback", metavar="RUN_ID")
    pm.add_argument("--list-runs", action="store_true")
    pm.add_argument("--dry-run", action="store_true")
    pm.set_defaults(func=cmd_promote)

    cn = sub.add_parser("canonicalise", help="Phase 6: rule on proposed vocabulary")
    cn.add_argument("--apply", help="apply an edited proposed_terms_review.csv")
    cn.add_argument("--min-freq", type=int, default=3, dest="min_freq")
    cn.add_argument("--out", default="proposed_terms_review.csv")
    cn.add_argument("--dry-run", action="store_true")
    cn.set_defaults(func=cmd_canonicalise)

    va = sub.add_parser("vocab-apply", help="activate reviewed community vocabulary")
    va.add_argument("--dry-run", action="store_true")
    va.add_argument("--hold", help="comma-separated slugs to leave untouched")
    va.set_defaults(func=cmd_vocab_apply)

    st = sub.add_parser("status", help="pipeline census")
    st.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
