"""Read-only survey: active trope slugs + per-genre reachable book counts.

Used to size the next pattern packs (romance / fantasy / sci-fi) the same way
the mystery pack was built. Writes nothing.
"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

conn = sqlite3.connect(C.DB_PATH, timeout=600)
conn.row_factory = sqlite3.Row

tropes = [r[0] for r in conn.execute(
    "SELECT slug FROM taxonomy WHERE kind='trope' AND status='active' ORDER BY slug")]
print(f"active tropes: {len(tropes)}\n")
print(", ".join(tropes))

GENRES = {
    "romance":  "(b.genres LIKE '%Romance%' OR b.genres LIKE '%romance%')",
    "fantasy":  "(b.genres LIKE '%Fantasy%' OR b.genres LIKE '%fantasy%')",
    "sci-fi":   "(b.genres LIKE '%Sci-Fi%' OR b.genres LIKE '%Science Fiction%' "
                "OR b.genres LIKE '%sci-fi%' OR b.genres LIKE '%science fiction%')",
    "horror":   "(b.genres LIKE '%Horror%' OR b.genres LIKE '%horror%')",
    "mystery":  "(b.genres LIKE '%Mystery%' OR b.genres LIKE '%crime%' "
                "OR b.genres LIKE '%Thriller%' OR b.genres LIKE '%mystery%')",
}

print("\n\nreachable pool (trope-less fiction WITH a description):")
for name, gen in GENRES.items():
    row = conn.execute(f"""SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN COALESCE(w.description,o.description) IS NOT NULL
                    AND TRIM(COALESCE(w.description,o.description))!='' THEN 1 ELSE 0 END) AS with_desc
        FROM books b JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
        WHERE {gen} AND s.book_class='fiction'
          AND (b.tropes IS NULL OR b.tropes='[]')""").fetchone()
    print(f"  {name:<9} trope-less fiction {row['total']:>7,}   with description {row['with_desc'] or 0:>7,}")

conn.close()
