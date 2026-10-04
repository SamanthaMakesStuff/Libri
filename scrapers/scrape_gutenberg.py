#!/usr/bin/env python3
"""
Project Gutenberg scraper -> merges subjects/genre into bookCatalog.json, and
adds unmatched books as new entries (same behaviour as scrape_tropetrove.py).

Gutenberg has ~70k books, so it's crawled one bookshelf (genre) at a time.

Usage:
  python scrape_gutenberg.py 644                 # bookshelf id 644 (Adventure), all pages
  python scrape_gutenberg.py 644 --limit 5       # test on first 5 books
  python scrape_gutenberg.py 644 668 638         # several bookshelves
  python scrape_gutenberg.py --book 2701         # dry-run a single book page (prints entry)

Find a bookshelf id from its URL, e.g. https://www.gutenberg.org/ebooks/bookshelf/644
Some common ones: 644 Adventure, 668 Science-Fiction, 638 Mystery, 646 Gothic Fiction,
486 Horror, 645 Novels, 649 Classics of Literature.

Mapping to catalog fields:
  - genre : the crawled bookshelf's name + any genre-like labels from the book's
            "Readers also downloaded" box (similar-books-tags), mapped to catalog vocab.
  - tags  : Gutenberg "Subject" headings (cleaned of "-- Fiction") + descriptive
            shelf labels (e.g. "Classics of Literature" -> "classic literature").
  - tropes: left empty — Gutenberg has no reader-trope data.
  - verifiedSource amended to include "Project Gutenberg" on updated books.

Curatorial reading-lists ("Readers also downloaded" header, "Best Books Ever
Listings", the Banned-Books lists, etc.) are dropped — they aren't genres/tags.
Run `python sync_db.py --refresh` afterwards to push changes into the app DB.
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import json
import re
import shutil
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from scrape_sfbook import fetch
from scrape_tropetrove import find_catalog_match, UNMATCHED_PATH
from app import normalize_title, normalize_author

CATALOG_PATH = Path(__file__).parent.parent / "bookCatalog.json"
BASE = "https://www.gutenberg.org"
PER_PAGE = 25

# Gutenberg bookshelf/subject names -> catalog genre vocabulary
GENRE_MAP = {
    "Science-Fiction": "Sci-Fi", "Science Fiction": "Sci-Fi",
    "Mystery": "Mystery", "Detective Fiction": "Mystery",
    "Horror": "Horror", "Gothic Fiction": "Horror",
    "Fantasy": "Fantasy", "Adventure": "Adventure",
}


def map_genre(name):
    return GENRE_MAP.get(name, name)


# --- "Readers also downloaded" (similar-books-tags) classification -----------
# Curatorial reading-lists: not genres or tags -> dropped entirely.
SHELF_DROP = {
    "Readers also downloaded", "Best Books Ever Listings", "Harvard Classics",
    "Contemporary Reviews", "Movie Books", "Novels",
    "Banned Books from Anne Haight's list",
    "Banned Books List from the American Library Association",
}

# Shelf label -> catalog GENRE (routed to the genre field, Title Case).
SHELF_GENRE = {
    "Science-Fiction & Fantasy": "Sci-Fi", "Precursors of Science Fiction": "Sci-Fi",
    "Science Fiction by Women": "Sci-Fi", "Fantasy": "Fantasy",
    "Gothic Fiction": "Horror", "Horror": "Horror",
    "Mystery Fiction": "Mystery", "Detective Fiction": "Mystery",
    "Crime, Thrillers and Mystery": "Mystery", "Romance": "Romance",
    "Adventure": "Adventure",
}

# Shelf label -> cleaned TAG (lowercase, to match catalog tag style). Labels not
# listed here and not a genre keep their own text, lowercased.
SHELF_TAG_ALIAS = {
    "Classics of Literature": "classic literature",
    "Plays/Films/Dramas": "plays and dramas",
}


def classify_shelves(labels):
    """Split 'Readers also downloaded' labels into (genres, tags), dropping
    curatorial reading-lists and cleaning tag names."""
    genres, tags = [], []
    for lab in labels:
        if lab in SHELF_DROP:
            continue
        if lab in SHELF_GENRE:
            g = SHELF_GENRE[lab]
            if g not in genres:
                genres.append(g)
        else:
            t = SHELF_TAG_ALIAS.get(lab, lab.lower())
            if t not in tags:
                tags.append(t)
    return genres, tags


def clean_subject(subj):
    """'Ship captains -- Fiction' -> 'ship captains'; 'Sea stories' -> 'sea stories'."""
    subj = re.sub(r"\s*--\s*Fiction\s*$", "", subj, flags=re.I)
    return subj.strip().lower()


def format_author(cell):
    """'Melville, Herman, 1819-1891' -> 'Herman Melville' (drops life dates)."""
    parts = [p.strip() for p in cell.split(",")]
    parts = [p for p in parts if not re.match(r"^\d{3,4}\??-?", p)]  # drop dates
    if len(parts) >= 2:
        return f"{parts[1]} {parts[0]}".strip()
    return parts[0] if parts else None


def scrape_book(ebook_id):
    soup = BeautifulSoup(fetch(f"{BASE}/ebooks/{ebook_id}"), "html.parser")
    tbl = soup.find("table", class_="bibrec")
    if not tbl:
        return None

    title = author = None
    authors, subjects = [], []
    for tr in tbl.find_all("tr"):
        th, td = tr.find("th"), tr.find("td")
        if not th or not td:
            continue
        label = th.get_text(strip=True)
        val = td.get_text(" ", strip=True)
        if label == "Title" and not title:
            title = val
        elif label == "Author":
            a = format_author(val)
            if a:
                authors.append(a)
        elif label == "Subject":
            subjects.append(val)
    author = ", ".join(authors) if authors else None

    tags, seen = [], set()
    for s in subjects:
        c = clean_subject(s)
        if c and c not in seen:
            seen.add(c)
            tags.append(c)

    # "Readers also downloaded" box -> extra genres + descriptive tags
    labels = []
    block = soup.find(class_="similar-books-tags")
    if block:
        labels = [a.get_text(strip=True) for a in block.find_all("a")]
    shelf_genres, shelf_tags = classify_shelves(labels)
    for t in shelf_tags:
        if t not in seen:
            seen.add(t)
            tags.append(t)

    return {"id": f"gutenberg_{ebook_id}", "title": title, "author": author,
            "tags": tags, "genres": shelf_genres,
            "url": f"{BASE}/ebooks/{ebook_id}"}


def collect_shelf(shelf_id, cap=None):
    """Return (shelf_name, [ebook_ids]) walking ?start_index pagination.
    Stops early once `cap` ids have been gathered (used by --limit)."""
    ids, start, name = [], 1, None
    while True:
        url = f"{BASE}/ebooks/bookshelf/{shelf_id}"
        if start > 1:
            url += f"?start_index={start}"
        soup = BeautifulSoup(fetch(url), "html.parser")
        if name is None:
            t = soup.find("title")
            m = re.search(r"Category:\s*(.+?)\s*-\s*Project Gutenberg",
                          t.get_text(strip=True)) if t else None
            name = m.group(1) if m else f"shelf-{shelf_id}"
        page_ids = []
        for a in soup.select("li.booklink a.link"):
            m = re.match(r"/ebooks/(\d+)$", a.get("href", ""))
            if m and m.group(1) not in ids:
                page_ids.append(m.group(1))
        if not page_ids:
            break
        ids.extend(page_ids)
        has_next = any("start_index" in a.get("href", "")
                       and a.get_text(strip=True) == "Next"
                       for a in soup.find_all("a", href=True))
        print(f"  {name} @start={start}: {len(page_ids)} books")
        if not has_next or (cap and len(ids) >= cap):
            break
        start += PER_PAGE
        time.sleep(1)
    return name, ids


def combined_genres(s, genre):
    """Crawl-shelf genre first, then the book's own shelf-derived genres."""
    out = []
    if genre:
        out.append(map_genre(genre))
    for g in s.get("genres", []):
        if g not in out:
            out.append(g)
    return out


def entry_from_scrape(s, genre):
    return {
        "id": s["id"], "title": s["title"], "author": s["author"],
        "genre": combined_genres(s, genre),
        "tropes": [], "tags": s["tags"],
        "pacing": None, "focus": None, "spiceLevel": "N/A",
        "contentWarnings": [],
        "verifiedSource": "Project Gutenberg", "sourceUrl": s["url"],
    }


def merge_into(entry, s, genre):
    """Add Gutenberg tags + genre to an existing catalog entry."""
    changed = False

    tags = entry.get("tags") or []
    norm = {re.sub(r"[^a-z0-9]", "", t.lower()) for t in tags}
    for t in s["tags"]:
        if re.sub(r"[^a-z0-9]", "", t.lower()) not in norm:
            tags.append(t)
            changed = True
    entry["tags"] = tags

    cur = entry.get("genre")
    genres = cur if isinstance(cur, list) else ([cur] if cur else [])
    gnorm = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in genres}
    for g in combined_genres(s, genre):
        if re.sub(r"[^a-z0-9]", "", g.lower()) not in gnorm:
            genres.append(g)
            gnorm.add(re.sub(r"[^a-z0-9]", "", g.lower()))
            changed = True
    entry["genre"] = genres

    if changed:
        src = entry.get("verifiedSource") or ""
        if "Gutenberg" not in src:
            entry["verifiedSource"] = (src + " + " if src else "") + "Project Gutenberg"
    return changed


def main():
    args = sys.argv[1:]

    # single-book dry run
    if "--book" in args:
        s = scrape_book(args[args.index("--book") + 1])
        print(json.dumps(entry_from_scrape(s, None) if s else None,
                         indent=2, ensure_ascii=False))
        return

    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    shelf_ids = [a for a in args if not a.startswith("--")]
    if not shelf_ids:
        print(__doc__)
        sys.exit(1)

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_index = [(b, normalize_title(b.get("title") or ""),
                      normalize_author(b.get("author") or "")) for b in catalog]

    jobs = []  # (genre_name, ebook_id)
    for sid in shelf_ids:
        print(f"Collecting bookshelf {sid}...")
        name, ids = collect_shelf(sid, cap=limit)
        jobs.extend((name, i) for i in ids)
    if limit:
        jobs = jobs[:limit]
    print(f"Book pages to scrape: {len(jobs)}\n")

    updated, added, unchanged, unmatched = 0, 0, 0, []
    for i, (genre, eid) in enumerate(jobs, 1):
        try:
            s = scrape_book(eid)
        except Exception as e:
            print(f"[{i}/{len(jobs)}] FAILED ebook {eid}: {e}")
            continue
        if not s or not s["title"] or not s["author"]:
            unmatched.append({"ebook": eid, "reason": "missing title/author"})
            continue
        entry = find_catalog_match(s["title"], s["author"], catalog_index)
        if entry is None:
            new = entry_from_scrape(s, genre)
            catalog.append(new)
            catalog_index.append((new, normalize_title(new["title"]),
                                  normalize_author(new["author"])))
            added += 1
            print(f"[{i}/{len(jobs)}] NEW: {s['title']} by {s['author']} "
                  f"({len(s['tags'])} tags)")
        elif merge_into(entry, s, genre):
            updated += 1
            print(f"[{i}/{len(jobs)}] merged {len(s['tags'])} tags -> {entry['title']}")
        else:
            unchanged += 1
        time.sleep(1)

    shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    UNMATCHED_PATH.with_name("gutenberg_unmatched.json").write_text(
        json.dumps(unmatched, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone. Updated {updated}, added-new {added}, already-complete {unchanged}, "
          f"skipped-incomplete {len(unmatched)} (see gutenberg_unmatched.json)")
    print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
