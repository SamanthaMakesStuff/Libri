"""Re-triage the `ambiguous` backlog.

Phase 2's classify() reads ONLY the genres array, and matches Title-Case labels
exactly. Two consequences left 8,996 books stranded as ambiguous:

  * ~3,400 carry perfectly good FICTION labels that simply aren't in the
    configured set - 'Young Adult' (2,711), 'crime', 'Thriller & Mystery',
    'romance', 'contemporary', 'fantasy romance', 'historical'
  * 5,489 have an EMPTY genres array, so there was no signal at all

This pass adds two things Phase 2 didn't have:
  1. case-insensitive matching plus the missing fiction/nonfiction label variants
  2. Open Library subject headings as a fallback signal. OL headings very often
     literally contain "Fiction" / "Juvenile fiction", which is the single
     strongest classifier available, and discipline headings (Biography,
     History, Study and teaching...) mark non-fiction.

Conservative by design: a book is only reclassified on a CLEAR margin,
otherwise it stays ambiguous. Nothing else about the book is touched.

  python _retriage_ambiguous.py --dry-run
  python _retriage_ambiguous.py
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

DRY = "--dry-run" in sys.argv
MARGIN = 2          # subject-signal lead required to reclassify

FICTION_LABELS = {g.lower() for g in C.FICTION_GENRES} | {
    "young adult", "ya", "crime", "thriller & mystery", "thriller and mystery",
    "contemporary", "contemporary romance", "fantasy romance", "sci-fi romance",
    "historical", "small town", "dark romance", "paranormal romance",
    "urban fantasy", "dystopian", "romantasy", "romance", "chick lit",
    "new adult", "cozy mystery", "speculative fiction", "magical realism",
    "science fiction", "fiction",
}
NONFICTION_LABELS = {g.lower() for g in C.NONFICTION_GENRES} | {
    "biography", "memoir", "nonfiction", "non-fiction", "science & nature",
    "social science", "computers", "technology", "medical", "law", "sports",
    "true crime", "essays", "journalism", "finance", "parenting", "crafts",
    "gardening", "language", "mathematics",
}
CHILDRENS_LABELS = {"children's", "childrens", "children", "juvenile",
                    "picture book", "middle grade"}
POETRY_LABELS = {"poetry", "drama", "plays"}

# Decisive markers: one hit is enough. Library headings are formulaic, so these
# are reliable on their own. NB 'comic books' is deliberately NOT a fiction
# marker - scholarly works ABOUT comics carry it (it misfiled a manga history).
STRONG_FIC = ("fiction", "juvenile fiction", "love stories", "science fiction",
              "fantasy fiction", "detective and mystery stories", "romans",
              "short stories", "novela", "roman")
STRONG_NONFIC = ("nonfiction", "non-fiction", "handbooks", "manuals",
                 "textbooks", "study and teaching", "biography", "autobiography",
                 "guidebooks", "encyclopedias", "dictionaries",
                 "criticism and interpretation", "case studies", "cookbooks",
                 "programming", "computer", "algorithms", "medicine", "diets",
                 "management", "statistics", "research",
                 # scholarly markers: a book ABOUT a genre carries that genre's
                 # name in its subjects, so it needs counter-evidence
                 "history and criticism", "historiography", "themes, motives",
                 "criticism", "bibliography")

# Weaker discipline signal, needs corroboration
WEAK_NONFIC = ("history", "social conditions", "economic conditions",
               "politics and government", "psychology", "religion", "cooking",
               "travel", "science", "philosophy", "essays", "education",
               "health", "business", "art and society")


def _has(keys, text):
    """Whole-word match. \\b stops 'fiction' matching inside 'nonfiction'."""
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in keys)


def label_class(genres):
    g = {str(x).strip().lower() for x in genres}
    if g & CHILDRENS_LABELS:
        return "childrens"
    if (g & POETRY_LABELS) and not (g & FICTION_LABELS):
        return "poetry_drama"
    fic, non = g & FICTION_LABELS, g & NONFICTION_LABELS
    if fic and not non:
        return "fiction"
    if non and not fic:
        return "nonfiction"
    return None


def subject_class(subjects, nonfic_slugs=(), alias=None, active=None):
    """Classify from OL subject headings.

    Three signals, strongest first:
      1. decisive keyword markers (one hit settles it)
      2. the TAXONOMY itself - a subject that resolves to an active term scoped
         applies_to='nonfiction' is non-fiction evidence. This reuses the Phase 6
         vocabulary work instead of hand-maintaining a keyword list.
      3. weak discipline words, which only count in aggregate
    """
    # Word-boundary matching, NOT naive substring. Substring matching produced
    # three separate false results: 'fiction' fired inside 'nonfiction' (they
    # cancelled and lost the book), and 'roman' fired inside 'romance'.
    blob = [str(s).strip().lower() for s in subjects]
    fic = sum(_has(STRONG_FIC, s) for s in blob)
    non = sum(_has(STRONG_NONFIC, s) for s in blob)
    if fic and not non:
        return "fiction"
    if non and not fic:
        return "nonfiction"

    if alias is not None:
        for s in blob:
            slug = alias.get(s) or (s.replace(" ", "-") if s.replace(" ", "-") in active else None)
            if slug and slug in nonfic_slugs:
                non += 1
    weak = sum(any(k in s for k in WEAK_NONFIC) for s in blob)
    non += weak

    if fic - non >= MARGIN:
        return "fiction"
    if non - fic >= MARGIN:
        return "nonfiction"
    return None


conn = sqlite3.connect(C.DB_PATH, timeout=180)
conn.row_factory = sqlite3.Row

# Phase 6 scoped 64 active terms as applies_to='nonfiction' - reuse them
NONFIC_SLUGS = {r[0] for r in conn.execute(
    "SELECT slug FROM taxonomy WHERE status='active' AND applies_to='nonfiction'")}
ACTIVE = {r[0] for r in conn.execute("SELECT slug FROM taxonomy WHERE status='active'")}
ALIAS = {r[0]: r[1] for r in conn.execute("SELECT alias, slug FROM taxonomy_alias")}
print(f"taxonomy signal: {len(NONFIC_SLUGS)} nonfiction-scoped slugs, {len(ALIAS)} aliases")

rows = conn.execute("""SELECT b.id, b.title, b.genres, m.subjects
                       FROM books b JOIN enrichment_state s ON s.book_id=b.id
                       LEFT JOIN book_metadata m ON m.book_id=b.id AND m.source='ol_dump'
                       WHERE s.book_class='ambiguous' AND s.stage='pending'""").fetchall()

stats, by_source, changes, examples = Counter(), Counter(), [], {}
for r in rows:
    try:
        genres = json.loads(r["genres"] or "[]")
    except Exception:
        genres = []
    try:
        subjects = json.loads(r["subjects"] or "[]")
    except Exception:
        subjects = []

    cls = label_class(genres)
    src = "genre-label"
    if cls is None and subjects:
        cls = subject_class(subjects, NONFIC_SLUGS, ALIAS, ACTIVE)
        src = "ol-subjects"
    if cls is None:
        stats["still_ambiguous"] += 1
        continue
    stats[cls] += 1
    by_source[src] += 1
    changes.append((r["id"], cls))
    examples.setdefault((cls, src), []).append(f"{r['title'][:44]}  {genres or subjects[:3]}")

if not DRY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (C.ROOT / f"retriage_backup_{ts}.json").write_text(
        json.dumps([{"id": i, "was": "ambiguous"} for i, _ in changes],
                   ensure_ascii=False), encoding="utf-8")
    for bid, cls in changes:
        conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?", (cls, bid))
    conn.commit()
    print(f"backup -> retriage_backup_{ts}.json")

print(f"\n{'DRY RUN - ' if DRY else ''}re-triage of {len(rows):,} ambiguous books")
for k, v in stats.most_common():
    print(f"  {k:<20} {v:>7,}")
print("\n  classified by:", dict(by_source))
for key, ex in list(examples.items())[:6]:
    print(f"\n  {key[0]} via {key[1]}:")
    for e in ex[:3]:
        print(f"     {e}")
conn.close()
