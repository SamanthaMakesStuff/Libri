"""Read-only project status review: recommendable pool, coverage, gaps."""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

conn = sqlite3.connect(C.DB_PATH, timeout=600)
conn.row_factory = sqlite3.Row

kind = {r["slug"]: r["kind"] for r in conn.execute("SELECT slug, kind FROM taxonomy")}
def mood_only(tags_json):
    tags = json.loads(tags_json or "[]")
    if not tags:
        return False
    return all(kind.get(t) == "mood" for t in tags)

total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
archived = conn.execute("SELECT COUNT(*) FROM books WHERE status LIKE 'archived%'").fetchone()[0]
active = total - archived

# The recommender's own candidate pre-filter (app.py)
recommendable = conn.execute(
    "SELECT COUNT(*) FROM books WHERE ((tropes NOT IN ('[]','')) OR (tags NOT IN ('[]',''))) "
    "AND (status IS NULL OR status NOT LIKE 'archived%')").fetchone()[0]

with_trope = conn.execute("SELECT COUNT(*) FROM books WHERE tropes NOT IN ('[]','') "
                          "AND (status IS NULL OR status NOT LIKE 'archived%')").fetchone()[0]
with_tag = conn.execute("SELECT COUNT(*) FROM books WHERE tags NOT IN ('[]','') "
                        "AND (status IS NULL OR status NOT LIKE 'archived%')").fetchone()[0]
both = conn.execute("SELECT COUNT(*) FROM books WHERE tropes NOT IN ('[]','') AND tags NOT IN ('[]','') "
                    "AND (status IS NULL OR status NOT LIKE 'archived%')").fetchone()[0]

# meaningfully recommendable = has a trope OR a non-mood tag (real discriminative signal)
rows = conn.execute("SELECT tropes, tags FROM books WHERE (status IS NULL OR status NOT LIKE 'archived%')").fetchall()
meaningful = mood_only_ct = 0
for r in rows:
    has_trope = r["tropes"] not in (None, "", "[]")
    tags = json.loads(r["tags"] or "[]")
    has_real_tag = any(kind.get(t) not in (None, "mood") for t in tags)
    if has_trope or has_real_tag:
        meaningful += 1
    elif tags and not has_trope and all(kind.get(t) == "mood" for t in tags):
        mood_only_ct += 1

print(f"TOTAL books............ {total:,}")
print(f"  archived (non-Eng)... {archived:,}")
print(f"  active............... {active:,}")
print(f"\nRECOMMENDABLE (app pre-filter: has trope|tag, not archived): {recommendable:,} "
      f"({recommendable/active*100:.0f}% of active)")
print(f"  with >=1 trope....... {with_trope:,}")
print(f"  with >=1 tag......... {with_tag:,}")
print(f"  with BOTH............ {both:,}")
print(f"\nMEANINGFULLY recommendable (trope OR non-mood tag): {meaningful:,}")
print(f"  weak (mood-tags only, no trope/real-tag): {mood_only_ct:,}")

# fiction/nonfiction of active
cls = Counter(r[0] for r in conn.execute(
    "SELECT es.book_class FROM books b JOIN enrichment_state es ON es.book_id=b.id "
    "WHERE (b.status IS NULL OR b.status NOT LIKE 'archived%')"))
print(f"\nactive book_class: {dict(cls.most_common())}")

# the enrichment GAP: active fiction with a description but NO trope
gap = conn.execute("""SELECT COUNT(*) FROM books b JOIN enrichment_state s ON s.book_id=b.id
    LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
    LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
    LEFT JOIN book_metadata g ON g.book_id=b.id AND g.source='googlebooks'
    WHERE s.book_class='fiction' AND (b.tropes IS NULL OR b.tropes='[]')
      AND (b.status IS NULL OR b.status NOT LIKE 'archived%')
      AND COALESCE(w.description,o.description,g.description) IS NOT NULL
      AND TRIM(COALESCE(w.description,o.description,g.description))!=''""").fetchone()[0]
nodesc = conn.execute("""SELECT COUNT(*) FROM books b JOIN enrichment_state s ON s.book_id=b.id
    LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
    LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
    WHERE s.book_class='fiction' AND (b.tropes IS NULL OR b.tropes='[]')
      AND (b.status IS NULL OR b.status NOT LIKE 'archived%')
      AND (COALESCE(w.description,o.description) IS NULL
           OR TRIM(COALESCE(w.description,o.description))='')""").fetchone()[0]
print(f"\nENRICHMENT GAP (active fiction, no trope yet):")
print(f"  WITH a description (reachable by matcher).. {gap:,}")
print(f"  WITHOUT a description (needs a fetch)...... {nodesc:,}")

# genre breakdown of active fiction lacking tropes but with descriptions
print(f"\ntop genres of the reachable-but-untropetd fiction:")
gc = Counter()
for (genres,) in conn.execute("""SELECT b.genres FROM books b JOIN enrichment_state s ON s.book_id=b.id
    LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
    LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
    WHERE s.book_class='fiction' AND (b.tropes IS NULL OR b.tropes='[]')
      AND (b.status IS NULL OR b.status NOT LIKE 'archived%')
      AND COALESCE(w.description,o.description) IS NOT NULL
      AND TRIM(COALESCE(w.description,o.description))!=''"""):
    for g in json.loads(genres or "[]"):
        gc[g] += 1
for g, n in gc.most_common(14):
    print(f"    {g:32.32} {n:,}")

# taxonomy
tax = Counter((r["kind"], r["status"]) for r in conn.execute("SELECT kind,status FROM taxonomy"))
print(f"\ntaxonomy active: " + ", ".join(f"{k}={v}" for (k, st), v in sorted(tax.items()) if st == "active"))
conn.close()
