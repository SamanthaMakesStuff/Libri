#!/usr/bin/env python3
"""
Conservative catalog reclassification (taxonomy.md-aligned).

- Genre: corrected ONLY when the book's own source tags clearly contradict the
  assigned genre. Evidence comes from the tags that shipped with the data.
- Subgenre: added to the genres array (per spec, subgenres live alongside genre).
- Tropes: NEVER modified in this pass.
- Tags: junk shelf/list names removed (favourites, reviews, to-buy, etc.).
- Everything lands in enrichment_review + enrichedCatalog.json; books table is
  updated in place (bookCatalog.json is never touched).
"""

import json
import sqlite3
from collections import Counter

from app import derive_tags, canonical_spice

DB_PATH = "book_rec.db"
CATALOG_PATH = "bookCatalog.json"

JUNK_SUBSTRINGS = ("favourite", "favorite", "best of", "recommended", "review",
                   "to buy", "tbr", "wish list", "wishlist", "all reviews",
                   "books fiction", "kindle", "audiobook", "ebook")

# tag evidence -> (primary genre, subgenre) . Checked in order; first hit wins.
GENRE_EVIDENCE = [
    (("erotica",), ("Romance", "erotica")),
    (("historical", "regency", "victorian", "1920s", "1950s", "wwii", "world war"),
     ("Romance", "historical romance")),
    (("paranormal", "vampire", "witch", "shifter", "werewolf", "ghost", "demon"),
     ("Romance", "paranormal romance")),
    (("fantasy", "magic", "fae", "dragon", "royalty fantasy"),
     ("Fantasy", "fantasy romance")),
    (("sci-fi", "science fiction", "space", "futuristic", "dystopian", "alien"),
     ("Sci-Fi", "sci-fi romance")),
    (("crime", "detective", "police", "murder", "thriller", "espionage", "assassin",
      "mystery", "fbi / cia", "law enforcement"),
     ("Mystery", "romantic suspense")),
    (("sports",), ("Romance", "sports romance")),
    (("christmas", "holiday"), ("Romance", "holiday romance")),
    (("small town", "small-town"), ("Romance", "small-town romance")),
    (("contemporary",), ("Romance", "contemporary romance")),
]

# When a book is a romance but its primary genre is something else, the romance
# element must stay visible next to the genre (user requirement)
ROMANCE_BLEND = {
    "Fantasy": "Romantasy",
    "Sci-Fi": "sci-fi romance",
    "Mystery": "romantic suspense",
    "Thriller": "romantic suspense",
    "Horror": "paranormal romance",
    "Historical": "historical romance",
    "Contemporary": "contemporary romance",
}


# Tropes that clearly signal a romance arc (used to detect the romance element
# when the source data has tropes but no "Romance" genre or romance tags).
ROMANCE_TROPES = {
    "romantasy", "fated mates", "forbidden romance", "second chance romance",
    "second chance", "slow-burn romance", "slow burn romance", "dark romance",
    "friends to lovers", "enemies to lovers", "rivals to lovers",
    "grumpy-sunshine dynamic", "grumpy sunshine", "fake dating",
    "marriage of convenience", "forced marriage", "fake relationship",
}


def is_junk(tag):
    t = tag.lower()
    return any(s in t for s in JUNK_SUBSTRINGS)


def evidence_genres(tags_lower):
    """All (genre, subgenre) pairs supported by this book's own tags.
    Whole-word matching — 'fae' must not match inside 'cafe'."""
    import re as _re
    hits = []
    for keywords, result in GENRE_EVIDENCE:
        if any(_re.search(r"\b" + _re.escape(k) + r"\b", t)
               for t in tags_lower for k in keywords):
            hits.append(result)
    return hits


def reclassify(book):
    raw_genre = book.get("genre", "")
    original_genres = ([g for g in raw_genre if g] if isinstance(raw_genre, list)
                       else ([raw_genre] if raw_genre else []))
    original_genre = original_genres[0] if original_genres else ""

    tags = book.get("tags", [])
    tags_lower = [t.lower() for t in tags]

    # Spice is its own dimension: pull spice-ish tags out of tags, use them to
    # fill spice_level when the field is missing, then canonicalize to
    # Explicit / Medium Spice / Tame / No Spice / N-A
    spice_tags = [t for t in tags if any(k in t.lower() for k in
                  ("spice", "heat", "euphemistic", "explicit", "closed door"))]
    spice_raw = book.get("spiceLevel") or (spice_tags[0] if spice_tags else None)
    spice = canonical_spice(spice_raw)

    clean_tags = derive_tags(book.get("tropes", []),
                             [t for t in tags if not is_junk(t) and t not in spice_tags],
                             None, book.get("pacing"))

    hits = evidence_genres(tags_lower)
    # Romance-flavored subgenres only when the book is actually a romance.
    # Signals: a Romance genre (anywhere in the list), romance tags, sapphic/mlm,
    # or clearly romance-arc tropes (Fated Mates, Slow-burn Romance, ...).
    tropes_norm = {t.strip().lower() for t in book.get("tropes", [])}
    is_romance = (any(g.strip().lower() == "romance" for g in original_genres)
                  or any("romance" in t for t in tags_lower)
                  or any(t in ("sapphic", "mlm") for t in book.get("tropes", []))
                  or bool(tropes_norm & ROMANCE_TROPES))
    if not is_romance:
        plain = {"sci-fi romance": None, "historical romance": "historical",
                 "paranormal romance": "paranormal", "romantic suspense": "crime",
                 "contemporary romance": "contemporary", "romantasy": None,
                 "erotica": None, "sports romance": None, "holiday romance": None,
                 "small-town romance": "small town"}
        hits = [(g, plain.get(s, s)) for g, s in hits]
    supported_primaries = {g for g, _ in hits}

    changed = False
    # Check the evidence against EVERY source genre, not just the first. Testing
    # only original_genres[0] meant ['Sci-Fi','Space Opera','Thriller'] was judged
    # on 'Sci-Fi' alone and "corrected" to Mystery, even though Thriller was
    # sitting right there in the list.
    supported = [g for g in original_genres if g in supported_primaries]
    if hits and original_genres and not supported:
        # Evidence contradicts every source genre. Surface the evidence genre as
        # primary, but do NOT treat that as licence to delete the source genres
        # below - shelf tags are noisy, catalogue genres are not.
        primary, subgenre = hits[0]
        changed = True
        confidence = "tag-evidence"
    elif hits:
        # Consistent with at least one source genre -> keep that one as primary
        primary = supported[0] if supported else original_genre
        subgenre = next((s for g, s in hits if g == primary), hits[0][1])
        confidence = "consistent"
    else:
        primary, subgenre = original_genre, None
        confidence = "no-evidence"

    # A romance in another genre keeps that genre but must SHOW the romance
    # element (e.g. Fantasy · fantasy romance) — never hide it, never override
    if is_romance and primary != "Romance":
        subgenre = ROMANCE_BLEND.get(primary, "romance")
        confidence += "+romance"

    # Catalogue genres come first and are never dropped or demoted; tag evidence
    # is APPENDED as an extra signal. Emitting only [primary, subgenre] destroyed
    # the rest - 1,653 books lost their real genre that way (793 fantasy, 534
    # young adult, 494 adventure), e.g. Bloodstone ['Fantasy','Post Apocalyptic']
    # became ['Mystery','crime']. Shelf tags are noisy; they must not overrule
    # catalogue data, only add to it.
    genres = [g for g in original_genres if g]
    for g in ([primary] if primary else []) + ([subgenre] if subgenre else []):
        if g and g not in genres:
            genres.append(g)

    # A book that is both fantasy and romance is "romantasy" — surface it as a
    # (sub-)genre (e.g. Fantasy · Romantasy) so it shows in the genre breakdown.
    has_fantasy = (any("fantasy" in g.lower() for g in original_genres)
                   or "fantasy" in primary.lower()
                   or (subgenre and "fantasy" in subgenre.lower()))
    if has_fantasy and is_romance and not any(g.lower() == "romantasy" for g in genres):
        genres.append("Romantasy")
    return {
        "book_id": book.get("id"),
        "title": book.get("title"),
        "original_genre": original_genre,
        "genres": genres,
        "genre_changed": changed,
        "confidence": confidence,
        "tropes": book.get("tropes", []),      # untouched
        "tags": clean_tags,
        "junk_removed": len(tags) - len(clean_tags),
        "pacing": book.get("pacing"),
        "spiceLevel": spice,
        "focus": book.get("focus"),
        "contentWarnings": book.get("contentWarnings", []),
    }


def main():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)

    results = [reclassify(b) for b in catalog]

    changed = [r for r in results if r["genre_changed"]]
    junk_total = sum(r["junk_removed"] for r in results)

    print(f"Books processed: {len(results)}")
    print(f"Genres corrected (tags contradicted label): {len(changed)}")
    print(f"Genres kept (consistent with tags): {sum(1 for r in results if r['confidence'] == 'consistent')}")
    print(f"No tag evidence (left untouched): {sum(1 for r in results if r['confidence'] == 'no-evidence')}")
    print(f"Junk tags removed: {junk_total}")

    print("\nGenre corrections by direction:")
    for (frm, to), n in Counter((r["original_genre"], r["genres"][0]) for r in changed).most_common(12):
        print(f"  {frm} -> {to}: {n}")

    print("\nSample corrections:")
    for r in changed[:12]:
        print(f"  {r['title']}: {r['original_genre']} -> {' / '.join(r['genres'])}")

    # Trope corroboration report (informational only — tropes not modified)
    suspect = 0
    for r in results:
        tl = [t.lower() for t in r["tags"]]
        if "royalty" in r["tropes"] and not any("royal" in t or "princess" in t or "queen" in t for t in tl):
            suspect += 1
    print(f"\nInfo: 'royalty' trope with no corroborating tag: {suspect} books (not changed)")

    # Persist: review queue + enriched export + live books table
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id TEXT NOT NULL UNIQUE,
            enriched_data TEXT,
            status TEXT DEFAULT 'approved',
            approved BOOLEAN DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for r in results:
        conn.execute(
            "INSERT OR REPLACE INTO enrichment_review (book_id, enriched_data) VALUES (?, ?)",
            (r["book_id"], json.dumps(r)))
        conn.execute("""
            UPDATE books SET genres = ?, tags = ?, spice_level = ?,
                             source = 'reclassified' WHERE id = ?
        """, (json.dumps(r["genres"]), json.dumps(r["tags"]), r["spiceLevel"],
              r["book_id"]))
    conn.commit()
    conn.close()

    with open("enrichedCatalog.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\nApplied to books table (tropes untouched). Full diff in enrichedCatalog.json")
    print("bookCatalog.json was NOT modified.")


if __name__ == "__main__":
    main()
