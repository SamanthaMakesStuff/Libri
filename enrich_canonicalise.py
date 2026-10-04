"""Phase 6 — canonicalise proposed terms (`enrich canonicalise`).

Gathers every non-active vocabulary term actually in use on books, with a
frequency count, and decides what each should become:

  * frequency < MIN_FREQ            -> dropped as idiosyncratic noise (logged)
  * rapidfuzz >= AUTO_MERGE         -> suggest merge into the existing slug
  * BORDERLINE..AUTO_MERGE          -> suggest review, with top-3 candidates
  * below BORDERLINE                -> suggest activating as a genuinely new term

No embeddings/LLM tier: there is no API key, so the brief's 0.70-0.87 Sonnet
band becomes a human/inline review band instead. rapidfuzz is the only scorer,
which the project already depends on.

Prior rulings are respected, never re-asked blindly:
  * taxonomy rows already status='rejected'
  * vocab_decisions_final.csv (e.g. 'war' -> drop, 'author-of-colour' -> drop)
are carried into the CSV as `prior_decision` so a past call is visible.

GATE: `review` only writes a CSV. Nothing touches the DB until you edit the
`decision` column and run `--apply`.

decision column accepts:
    merge:<slug>   alias this term to an existing active slug, rewrite books
    activate       make this term active taxonomy (kind from `kind` column)
    drop           remove the term from every book, mark rejected
    (blank)        leave untouched, ask again next time
"""
import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from rapidfuzz import fuzz, process

import config as C
from enrich_taxonomy import normalize_raw, slugify

MIN_FREQ = 3          # brief: frequency < 3 across the run -> drop as noise
AUTO_MERGE = 92       # brief: rapidfuzz >= 92 -> auto-merge candidate
BORDERLINE = 70       # below this, treat as a genuinely new concept
OUT = "proposed_terms_review.csv"


def _conn():
    c = sqlite3.connect(C.DB_PATH, timeout=120)
    c.row_factory = sqlite3.Row
    return c


def _prior_decisions():
    """slug -> prior ruling from the reviewed community-vocab CSV."""
    out = {}
    try:
        for r in csv.DictReader(open("vocab_decisions_final.csv", encoding="utf-8-sig")):
            if r.get("slug"):
                out[r["slug"]] = r.get("kind", "")
    except FileNotFoundError:
        pass
    return out


def _norm_genre(g):
    """Catalog genre labels are messy ('romance' vs 'Romance')."""
    g = str(g).strip().lower()
    return {"sci-fi": "sci-fi", "science fiction": "sci-fi",
            "general fiction": "general-fiction",
            "children's": "childrens", "young adult": "young-adult",
            "literary fiction": "literary-fiction",
            "biography & memoir": "biography-memoir"}.get(g, g.replace(" ", "-"))


def _term_frequencies(conn, active):
    """Non-active terms on books.tags -> counts, examples, and genre spread.

    The genre spread is what lets a term be judged in the context it actually
    occurs in: `aliens` is meaningful for sci-fi and meaningless for romance.
    """
    freq, examples = Counter(), {}
    genres = {}
    for r in conn.execute("SELECT id, title, tags, genres FROM books "
                          "WHERE tags IS NOT NULL AND tags != '[]'"):
        try:
            terms = json.loads(r["tags"])
            bgen = [_norm_genre(g) for g in json.loads(r["genres"] or "[]")]
        except Exception:
            continue
        for t in terms:
            if t in active:
                continue
            freq[t] += 1
            genres.setdefault(t, Counter()).update(bgen or ["(none)"])
            if len(examples.setdefault(t, [])) < 3:
                examples[t].append(r["title"])
    return freq, examples, genres


def review(min_freq=MIN_FREQ, out=OUT):
    conn = _conn()
    active = {r["slug"]: r["kind"] for r in conn.execute(
        "SELECT slug, kind FROM taxonomy WHERE status='active'")}
    rejected = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE status='rejected'")}
    display = {r["display"]: r["slug"] for r in conn.execute(
        "SELECT slug, display FROM taxonomy WHERE status='active'") if r["display"]}
    prior = _prior_decisions()

    freq, examples, genres = _term_frequencies(conn, active)
    choices = list(display.keys()) + list(active.keys())

    stats = Counter()
    rows = []
    DOMINANT = 0.50   # >=50% of a term's books in one genre -> file it there
    for term, n in freq.most_common():
        if n < min_freq:
            stats["dropped_noise"] += 1
            continue
        if term in rejected:
            stats["already_rejected"] += 1
            continue

        cands = process.extract(normalize_raw(term), choices,
                                scorer=fuzz.token_sort_ratio, limit=3)
        top = cands[0][1] if cands else 0
        if top >= AUTO_MERGE:
            slug = display.get(cands[0][0], cands[0][0])
            tier, suggestion = "auto-merge", f"merge:{slug}"
        elif top >= BORDERLINE:
            tier, suggestion = "review", ""
        else:
            tier, suggestion = "new", "activate"
        # a prior human ruling always wins over the suggestion
        if term in prior:
            tier = "prior-ruling"
            suggestion = "drop" if prior[term] == "drop" else suggestion
        stats[tier] += 1

        nearest = []
        for cand, score, _ in cands:
            nearest += [display.get(cand, cand), int(score)]
        nearest += [""] * (6 - len(nearest))

        gc = genres.get(term, Counter())
        gtot = sum(gc.values()) or 1
        top_g, top_n = gc.most_common(1)[0] if gc else ("(none)", 0)
        bucket = top_g if top_n / gtot >= DOMINANT else "cross-genre"
        mix = ", ".join(f"{g} {v*100//gtot}%" for g, v in gc.most_common(3))

        rows.append({
            "decision": "", "tier": tier, "suggestion": suggestion,
            "term": term, "books": n, "kind": "tag",
            "genre_bucket": bucket, "genre_mix": mix,
            "prior_decision": prior.get(term, ""),
            "nearest_1": nearest[0], "score_1": nearest[1],
            "nearest_2": nearest[2], "score_2": nearest[3],
            "nearest_3": nearest[4], "score_3": nearest[5],
            "example_books": " | ".join(examples.get(term, [])[:3]),
        })

    fields = list(rows[0].keys())
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # split by genre bucket so each term is judged in the context it occurs in
    buckets = {}
    for r in rows:
        buckets.setdefault(r["genre_bucket"], []).append(r)
    written = []
    for bucket, brows in sorted(buckets.items(), key=lambda kv: -sum(int(r["books"]) for r in kv[1])):
        if len(brows) < 5:                      # tiny buckets stay in the master file only
            continue
        path = f"canon_{bucket}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(brows)
        written.append((path, len(brows), sum(int(r["books"]) for r in brows)))

    print(f"wrote {out} ({len(rows):,} terms needing a decision)")
    for k, v in stats.most_common():
        print(f"  {k:<18} {v:>6,}")
    print(f"\n  terms below min_freq={min_freq} dropped as noise: {stats['dropped_noise']:,}")
    print(f"\n  split into {len(written)} per-genre files (judge each term in context):")
    for p, nterms, nbooks in written:
        print(f"    {p:<34} {nterms:>5} terms  {nbooks:>7,} book-tags")
    print("\n  edit the `decision` column: merge:<slug> | activate | drop | (blank)")
    conn.close()


def apply(path, dry_run=False):
    conn = _conn()
    active = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE status='active'")}
    decisions = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        d = (r.get("decision") or "").strip()
        if d:
            decisions.append((r["term"], d, r.get("kind") or "tag",
                              (r.get("genre_bucket") or "").strip(),
                              (r.get("applies_to") or "").strip()))
    print(f"loaded {len(decisions):,} decisions from {path}")

    merge_map, activate, drop = {}, [], set()
    # activations first: a term activated in THIS run is a legal merge target,
    # so it must be in `active` before any merge: line is validated.
    for term, d, kind, bucket, app in decisions:
        if d == "activate":
            activate.append((term, kind, bucket, app))
            active.add(term)
    for term, d, kind, bucket, app in decisions:
        if d.startswith("merge:"):
            slug = d.split(":", 1)[1].strip()
            if slug in active:
                merge_map[term] = slug
            else:
                print(f"  !! skipped merge {term} -> {slug} (target not active)")
        elif d == "drop":
            drop.add(term)

    now = datetime.now().isoformat(timespec="seconds")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats = Counter()

    NONFIC = {"history", "biography-memoir", "business-&-economics", "psychology",
              "self-help", "science-&-nature", "politics", "travel", "cooking"}
    if not dry_run:
        for term, kind, bucket, app in activate:
            # scope the term to the genre it actually occurs in (user's request):
            # a genre-specific term is only meaningful inside that genre.
            genres = json.dumps([bucket] if bucket and bucket not in
                                ("cross-genre", "(none)") else [], ensure_ascii=False)
            # an explicit applies_to column wins; else infer from the bucket
            applies = app if app in ("fiction", "nonfiction", "both") else (
                "nonfiction" if bucket in NONFIC else "both")
            conn.execute("""INSERT INTO taxonomy
                              (slug, display, kind, applies_to, genres, status, source, created_at)
                            VALUES (?,?,?,?,?,'active','canonicalise',?)
                            ON CONFLICT(slug) DO UPDATE SET status='active',
                              kind=excluded.kind, genres=excluded.genres,
                              applies_to=excluded.applies_to""",
                         (term, term.replace("-", " "), kind, applies, genres, now))
            active.add(term)
        for term, slug in merge_map.items():
            conn.execute("INSERT OR IGNORE INTO taxonomy_alias (alias, slug) VALUES (?,?)",
                         (normalize_raw(term), slug))
            conn.execute("""INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score, created_at)
                            VALUES (?,?,'canonicalise',100,?)""", (term, slug, now))
        for term in drop:
            conn.execute("""INSERT INTO taxonomy
                              (slug, display, kind, applies_to, status, source, created_at)
                            VALUES (?,?, 'tag','both','rejected','canonicalise',?)
                            ON CONFLICT(slug) DO UPDATE SET status='rejected'""",
                         (term, term.replace("-", " "), now))

    # rewrite books: merge -> canonical slug, drop -> remove, activate -> keep as-is
    backup = []
    for r in conn.execute("SELECT id, tags FROM books WHERE tags IS NOT NULL AND tags != '[]'"):
        try:
            tags = json.loads(r["tags"])
        except Exception:
            continue
        new = []
        changed = False
        for t in tags:
            if t in drop:
                changed = True
                stats["tag_occurrences_dropped"] += 1
                continue
            if t in merge_map:
                t2 = merge_map[t]
                changed = True
                stats["tag_occurrences_merged"] += 1
                t = t2
            if t not in new:
                new.append(t)
            else:
                changed = True
                stats["dedup_collapsed"] += 1
        if changed:
            stats["books_changed"] += 1
            backup.append({"id": r["id"], "tags": r["tags"]})
            if not dry_run:
                conn.execute("UPDATE books SET tags=? WHERE id=?",
                             (json.dumps(new, ensure_ascii=False), r["id"]))

    stats["terms_activated"] = len(activate)
    stats["terms_merged"] = len(merge_map)
    stats["terms_dropped"] = len(drop)

    if not dry_run:
        (C.ROOT / f"canonicalise_backup_{ts}.json").write_text(
            json.dumps({"run": ts, "books": backup}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        conn.commit()

    print(f"\n{'DRY RUN - ' if dry_run else ''}canonicalise")
    for k, v in stats.most_common():
        print(f"  {k:<26} {v:>7,}")
    if not dry_run:
        print(f"\n  backup -> canonicalise_backup_{ts}.json")
    conn.close()
