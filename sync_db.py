#!/usr/bin/env python3
"""
Sync bookCatalog.json -> book_rec.db WITHOUT touching user data.

- Inserts catalog books missing from the DB (runs them through the same
  cleanup pipeline as reclassify.py: genre evidence, junk-tag removal,
  spice canonicalization, derived tags).
- Existing books, user_books, feedback, recommendations are left alone.
- Then re-matches previously unmatched user_books rows against the expanded
  catalog, so imports that failed to match before can link up now.

Usage:
  python sync_db.py            # insert new catalog books + re-match imports
  python sync_db.py --refresh  # also UPDATE existing books whose catalog entry
                               # changed (e.g. after a tropetrove merge)
"""

import json
import sys

from app import get_db, init_db, normalize_title, normalize_author, fuzzy_match
from reclassify import reclassify

CATALOG_PATH = "bookCatalog.json"


def main():
    init_db()
    conn = get_db()

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)

    existing = {r["id"] for r in conn.execute("SELECT id FROM books")}

    inserted = 0
    skipped = []
    for book in catalog:
        if book.get("id") in existing:
            continue
        if not book.get("title") or not book.get("author"):
            skipped.append(book.get("id"))
            continue
        r = reclassify(book)  # same cleanup rules as the live catalog
        conn.execute("""
            INSERT INTO books (id, title, author, norm_title, norm_author, genres,
                               tropes, tags, pacing, spice_level, focus,
                               content_warnings, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'catalog_sync')
        """, (
            book.get("id"), book.get("title"), book.get("author"),
            normalize_title(book.get("title")), normalize_author(book.get("author")),
            json.dumps(r["genres"]), json.dumps(r["tropes"]), json.dumps(r["tags"]),
            r["pacing"], r["spiceLevel"], r["focus"],
            json.dumps(r["contentWarnings"]),
        ))
        existing.add(book.get("id"))
        inserted += 1
    conn.commit()
    print(f"Inserted {inserted} new books "
          f"(catalog {len(catalog)}, DB now {len(existing)})")

    if "--refresh" in sys.argv:
        refreshed = 0
        for book in catalog:
            if not book.get("title") or not book.get("author"):
                continue
            r = reclassify(book)
            cur = conn.execute("""
                UPDATE books SET genres = ?, tropes = ?, tags = ?, pacing = ?,
                                 spice_level = ?, focus = ?, content_warnings = ?
                WHERE id = ? AND (tropes != ? OR genres != ? OR tags != ?)
            """, (
                json.dumps(r["genres"]), json.dumps(r["tropes"]), json.dumps(r["tags"]),
                r["pacing"], r["spiceLevel"], r["focus"], json.dumps(r["contentWarnings"]),
                book.get("id"),
                json.dumps(r["tropes"]), json.dumps(r["genres"]), json.dumps(r["tags"]),
            ))
            refreshed += cur.rowcount
        conn.commit()
        print(f"Refreshed {refreshed} existing books from catalog changes")
    if skipped:
        print(f"Skipped {len(skipped)} entries missing title/author: {skipped[:5]}")

    # Re-match previously unmatched imports against the expanded catalog
    unmatched = conn.execute("""
        SELECT id, raw_title, raw_author FROM user_books
        WHERE match_status = 'unmatched'
    """).fetchall()
    if unmatched:
        books = conn.execute("SELECT id, norm_title, norm_author FROM books").fetchall()
        rematched = 0
        for row in unmatched:
            status, book_id = fuzzy_match(row["raw_title"], row["raw_author"], books)
            if status != "unmatched":
                conn.execute(
                    "UPDATE user_books SET book_id = ?, match_status = ? WHERE id = ?",
                    (book_id, status, row["id"]))
                rematched += 1
        conn.commit()
        print(f"Re-matched {rematched} of {len(unmatched)} previously unmatched "
              f"imported books (profile updates automatically)")

    conn.close()


if __name__ == "__main__":
    main()
