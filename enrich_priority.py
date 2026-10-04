"""Step 3 — priority slice selector (`enrich priority`).

The brief's --priority ordering, adapted for inline (no-API-key) enrichment:
demand order, not catalog order. Produces a ranked worklist of the books where
adding tropes actually changes THIS user's recommendations.

Tiers:
  1  books the user has read/shelved (user_books) that lack tropes
  2  books ever served as a recommendation (recommendations table)
  3  nearest neighbours of the user's loved books, by genre+tag overlap
     against the taste profile, restricted to fiction/childrens/ambiguous
  4  remaining fiction with tags but no tropes (best trope-inference odds)

Emits priority_slice.json (ranked, with the context an enricher needs) and
prints a census. Read-only: selects, never writes book data.
"""
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as C

OUT = C.ROOT / "priority_slice.json"


def _resolve_user(conn):
    """user_books.user_id is a string ('test_user'), not an int — read it."""
    r = conn.execute("""SELECT user_id, COUNT(*) n FROM user_books
                        GROUP BY user_id ORDER BY n DESC LIMIT 1""").fetchone()
    return r["user_id"] if r else None


def build(limit=1000, dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    user_id = _resolve_user(conn)
    print(f"user: {user_id!r}")

    trope_slugs = {r["slug"] for r in conn.execute(
        "SELECT slug FROM taxonomy WHERE kind='trope' AND status='active'")}

    books = {}
    for r in conn.execute(
            """SELECT b.id, b.title, b.author, b.genres, b.tropes, b.tags,
                      b.pacing, b.spice_level, b.focus, s.book_class
               FROM books b LEFT JOIN enrichment_state s ON s.book_id=b.id"""):
        books[r["id"]] = {
            "id": r["id"], "title": r["title"], "author": r["author"],
            "genres": json.loads(r["genres"] or "[]"),
            "tropes": json.loads(r["tropes"] or "[]"),
            "tags": json.loads(r["tags"] or "[]"),
            "pacing": r["pacing"], "spice": r["spice_level"], "focus": r["focus"],
            "book_class": r["book_class"] or "ambiguous",
        }

    def needs_tropes(b):
        canon = [t for t in b["tropes"] if t in trope_slugs]
        return len(canon) < 3 and b["book_class"] in ("fiction", "childrens", "ambiguous")

    # ---- tier 1: the user's own books -----------------------------------
    tier = {}
    rated = {}
    for r in conn.execute(
            """SELECT book_id, user_rating FROM user_books
               WHERE user_id=? AND book_id IS NOT NULL""", (user_id,)):
        if r["book_id"] in books:
            rated[r["book_id"]] = r["user_rating"]
            if needs_tropes(books[r["book_id"]]):
                tier.setdefault(r["book_id"], 1)

    # ---- tier 2: previously served recommendations ----------------------
    for r in conn.execute("SELECT DISTINCT book_id FROM recommendations"):
        b = books.get(r["book_id"])
        if b and needs_tropes(b) and r["book_id"] not in tier:
            tier[r["book_id"]] = 2

    # ---- taste profile from loved books (for neighbour scoring) ---------
    gw, tw = Counter(), Counter()
    for bid, rating in rated.items():
        b = books.get(bid)
        if not b:
            continue
        w = {5: 2.0, 4: 1.0, 3: 0.0, 2: -1.0, 1: -2.0}.get(int(rating or 0), 0.5)
        if w <= 0:
            continue
        for g in b["genres"]:
            gw[g] += w
        for t in b["tags"]:
            tw[t] += w

    # rarity weighting so ubiquitous mood tags don't dominate neighbour choice
    df = Counter()
    for b in books.values():
        for t in set(b["tags"]):
            df[t] += 1
    n = len(books) or 1
    idf = {t: math.log(n / c) for t, c in df.items() if c}

    # ---- tier 3: nearest neighbours of the taste profile ----------------
    scored = []
    for b in books.values():
        if b["id"] in tier or not needs_tropes(b):
            continue
        s = (sum(gw.get(g, 0) for g in b["genres"]) * 0.3
             + sum(tw.get(t, 0) * idf.get(t, 1.0) for t in b["tags"]) * 0.7)
        if s > 0:
            scored.append((s, b["id"]))
    scored.sort(reverse=True)
    for s, bid in scored:
        tier.setdefault(bid, 3)

    # ---- tier 4: remaining fiction that at least has tags ---------------
    for b in books.values():
        if b["id"] not in tier and needs_tropes(b) and b["tags"]:
            tier[b["id"]] = 4

    rank = {bid: i for i, (_, bid) in enumerate(scored)}
    worklist = sorted(tier.items(), key=lambda kv: (kv[1], rank.get(kv[0], 10**9)))

    census = Counter(t for _, t in tier.items())
    print("=== priority slice census ===")
    names = {1: "your read/shelved books", 2: "previously recommended",
             3: "nearest neighbours of your taste", 4: "other fiction with tags"}
    for t in sorted(census):
        print(f"  tier {t} — {names[t]:<32} {census[t]:>7,}")
    print(f"  TOTAL needing tropes:                        {len(tier):>7,}")
    print(f"\nselecting top {limit:,} for inline enrichment")

    out = []
    for bid, t in worklist[:limit]:
        b = books[bid]
        out.append({
            "id": bid, "tier": t, "title": b["title"], "author": b["author"],
            "genres": b["genres"], "book_class": b["book_class"],
            "existing_tags": b["tags"][:12], "existing_tropes": b["tropes"],
            "user_rating": rated.get(bid),
        })
    if not dry_run:
        OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {OUT.name} ({len(out):,} books)")

    print("\n=== first 15 of the worklist ===")
    for e in out[:15]:
        star = f" [{e['user_rating']}*]" if e["user_rating"] else ""
        print(f"  t{e['tier']} {e['title'][:40]:<40} {(e['author'] or '')[:22]:<22}"
              f" {'/'.join(e['genres'][:2])[:22]:<22}{star}")
    conn.close()
