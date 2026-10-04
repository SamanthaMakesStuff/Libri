"""Inline enrichment support (no API key).

  build_vocab()  -> vocab_prompt.txt : the active taxonomy, grouped by kind
  ingest(path)   -> validate a JSON array of enrichment results and write them
                    to enrichment_review, applying the brief's Phase 4 rules:
                      * every slug must exist in the ACTIVE taxonomy; unknown
                        slugs are moved to proposed_new, never silently kept
                      * known=false / confidence=low -> stage='needs_escalation'
                      * nonfiction & poetry_drama  -> tropes forced empty
                      * childrens                  -> spice_level forced 'N/A'
                      * union-only merge; existing data is never deleted
                    A before-image is stored so promotion is reversible.
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C

VALID_PACING = {"Slow", "Medium", "Fast"}
VALID_FOCUS = {"Plot", "Character", "World"}
# The catalog's canonical spice scale (app.canonical_spice). The brief's prompt
# schema uses None/Low/Medium/High, so map those in rather than fragmenting the
# dimension — community-sourced spice (e.g. The Lesbian Review) uses these five.
SPICE_MAP = {"none": "No Spice", "no spice": "No Spice",
             "low": "Tame", "tame": "Tame",
             "medium": "Medium Spice", "medium spice": "Medium Spice",
             "high": "Explicit", "explicit": "Explicit",
             "n/a": "N/A", "na": "N/A"}
VALID_SPICE = {"No Spice", "Tame", "Medium Spice", "Explicit", "N/A"}
# Which taxonomy kind each result field must draw from. Note content_warnings ->
# 'warning' (naive de-pluralising would have produced 'content_warning').
FIELD_KIND = {"tropes": "trope", "tags": "tag", "subjects": "subject",
              "content_warnings": "warning"}


def norm_spice(v):
    if not v:
        return None
    return SPICE_MAP.get(str(v).strip().lower())


def build_vocab():
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    lines, counts = [], Counter()
    for kind in ("genre", "subgenre", "trope", "tag", "mood", "subject", "warning"):
        rows = conn.execute(
            "SELECT slug, display FROM taxonomy WHERE kind=? AND status='active' "
            "ORDER BY slug", (kind,)).fetchall()
        if not rows:
            continue
        counts[kind] = len(rows)
        lines.append(f"\n## {kind.upper()} ({len(rows)})")
        lines.append(", ".join(r["slug"] for r in rows))
    C.VOCAB_PROMPT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {C.VOCAB_PROMPT.name}: " +
          " ".join(f"{k}={v}" for k, v in counts.items()))
    conn.close()


def ingest(path, dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    active = {r["slug"]: r["kind"] for r in conn.execute(
        "SELECT slug, kind FROM taxonomy WHERE status='active'")}
    classes = {r["book_id"]: r["book_class"] for r in conn.execute(
        "SELECT book_id, book_class FROM enrichment_state")}

    results = json.loads(open(path, encoding="utf-8").read())
    stats, unknown_slugs = Counter(), Counter()
    now = datetime.now().isoformat(timespec="seconds")

    for res in results:
        bid = res.get("id")
        if not bid:
            stats["no_id"] += 1
            continue
        row = conn.execute("SELECT tropes, tags, pacing, spice_level, focus, "
                           "content_warnings FROM books WHERE id=?", (bid,)).fetchone()
        if row is None:
            stats["unknown_book_id"] += 1
            continue

        # Guard: a book that already carries original catalog vocab (tropes/tags)
        # is KNOWN. Don't let a model 'known=false' — which usually just means it
        # had no OL description to ground on (e.g. The Lesbian Review titles,
        # absent from Open Library) — wipe that data or flag it 'unknown_book'.
        # Leave the book and its stage untouched.
        if not res.get("known", True) and (json.loads(row["tropes"] or "[]")
                                           or json.loads(row["tags"] or "[]")):
            stats["kept_original_data"] += 1
            continue

        klass = res.get("book_class") or classes.get(bid) or "ambiguous"
        proposed = list(res.get("proposed_new") or [])

        def clean(field):
            # A slug must be active AND of the right KIND for this field.
            # Checking only membership let `spy-espionage-thriller` — an active
            # *subgenre* — through as a trope on 3 books, because every kind
            # shares one namespace here.
            want = FIELD_KIND[field]
            out = []
            for s in (res.get(field) or []):
                if active.get(s) == want:
                    out.append(s)
                else:
                    unknown_slugs[f"{s} (wanted {want}, got {active.get(s) or 'nothing'})"] += 1
                    proposed.append({"term": s, "kind": want,
                                     "why": "model-emitted-unlisted"})
            return out

        tropes, tags = clean("tropes"), clean("tags")
        subjects, warnings = clean("subjects"), clean("content_warnings")
        tags = list(dict.fromkeys(tags + subjects))       # subjects live in tags

        # --- enforce the brief's bounds -------------------------------
        if klass in ("nonfiction", "poetry_drama"):
            if tropes:
                stats["tropes_stripped_nonfiction"] += 1
            tropes = []
        spice = norm_spice(res.get("spice_level"))
        if klass == "childrens":
            spice = "N/A"
        if spice not in VALID_SPICE:
            spice = None
        pacing = res.get("pacing") if res.get("pacing") in VALID_PACING else None
        focus = res.get("focus") if res.get("focus") in VALID_FOCUS else None
        if len(tropes) > 8:
            tropes = tropes[:8]
            stats["tropes_truncated"] += 1

        known = res.get("known", True)
        conf = res.get("confidence", "medium")
        stage = ("needs_escalation" if (not known or conf == "low" or
                                        (not tropes and not tags)) else "enriched")
        if not known:
            tropes, tags = [], []          # never keep output for an unknown book
            stats["known_false"] += 1

        payload = {"book_id": bid, "book_class": klass, "known": known,
                   "confidence": conf, "tropes": tropes, "tags": tags,
                   "pacing": pacing, "focus": focus, "spice_level": spice,
                   "content_warnings": warnings, "proposed_new": proposed}
        if not dry_run:
            # enrichment_review has UNIQUE(book_id) from the earlier pilot:
            # keep one current review per book (before_image preserves rollback).
            conn.execute(
                """INSERT INTO enrichment_review (book_id, enriched_data, status,
                     approved, model, confidence, before_image)
                   VALUES (?,?,'pending',0,'inline-claude',?,?)
                   ON CONFLICT(book_id) DO UPDATE SET
                     enriched_data=excluded.enriched_data,
                     status='pending', approved=0,
                     model=excluded.model, confidence=excluded.confidence,
                     before_image=COALESCE(enrichment_review.before_image,
                                           excluded.before_image)""",
                (bid, json.dumps(payload, ensure_ascii=False), conf,
                 json.dumps(dict(row), ensure_ascii=False)))
            conn.execute(
                """UPDATE enrichment_state SET stage=?, confidence=?,
                   model='inline-claude', updated_at=? WHERE book_id=?""",
                (stage, conf, now, bid))
        stats[stage] += 1
        stats[f"confidence_{conf}"] += 1

    if not dry_run:
        conn.commit()
    print(f"{'DRY RUN — ' if dry_run else ''}ingested {len(results)} results")
    for k, v in stats.most_common():
        print(f"  {k:<30} {v:>5}")
    if unknown_slugs:
        print(f"\n  slugs not in active taxonomy -> moved to proposed_new "
              f"({len(unknown_slugs)} distinct):")
        for s, n in unknown_slugs.most_common(15):
            print(f"    {s} x{n}")
    conn.close()
