#!/usr/bin/env python3
"""
tropetrove.com scraper -> merges tropes/genres into EXISTING bookCatalog.json entries.

Usage:
  python scrape_tropetrove.py science-fiction            # one genre, all pages
  python scrape_tropetrove.py science-fiction fantasy    # several genres
  python scrape_tropetrove.py science-fiction --limit 5  # test on 5 books

Behaviour (per spec):
  - Walks https://www.tropetrove.com/book-genres/<slug>?page=N until pages run out.
  - Per book page: tropes from class "flex flex-wrap gap-4", genres from
    class "mb-5 flex flex-wrap items-center gap-2".
  - Fuzzy-matches title+author against bookCatalog.json and MERGES (adds, never
    replaces) tropes + genres into every matching book, sparse or not.
  - verifiedSource is amended to include tropetrove.com on updated books.
  - Books with no catalog match are written to tropetrove_unmatched.json.
  - Run `python sync_db.py --refresh` afterwards to push merges into the app DB.
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
from rapidfuzz import fuzz

from scrape_sfbook import fetch, slug_from_url  # shared helpers
from app import normalize_title, normalize_author

GENRE_MAP = {"Science Fiction": "Sci-Fi"}


def entry_from_scrape(s):
    """Build a new catalog entry from a scraped Trope Trove book."""
    return {
        "id": slug_from_url(s["url"]),
        "title": s["title"],
        "author": s["author"],
        "genre": [GENRE_MAP.get(g, g) for g in s["genres"]],
        "tropes": s["tropes"],
        "tags": [],
        "pacing": None,
        "focus": None,
        "spiceLevel": "N/A",
        "contentWarnings": [],
        "verifiedSource": "tropetrove.com",
        "sourceUrl": s["url"],
    }

CATALOG_PATH = Path(__file__).parent.parent / "bookCatalog.json"
UNMATCHED_PATH = Path(__file__).parent.parent / "tropetrove_unmatched.json"
BASE = "https://www.tropetrove.com"


def collect_genre_urls(slug):
    """All /books/... URLs for a genre, following ?page=N until empty."""
    urls, page = [], 1
    while True:
        html = fetch(f"{BASE}/book-genres/{slug}?page={page}")
        links = sorted(set(re.findall(
            r'href="https://www\.tropetrove\.com(/books/[a-z0-9-]+)"', html)))
        if not links:
            break
        new = [l for l in links if l not in urls]
        if not new:  # site repeats last page for out-of-range page numbers
            break
        urls.extend(new)
        print(f"  {slug} page {page}: {len(new)} books")
        page += 1
        time.sleep(1)
    return urls


def scrape_book(path):
    soup = BeautifulSoup(fetch(BASE + path), "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else None

    # <title> is "Title: Author | ..." or "Title by Author | ..." — anchor on h1
    author = None
    t = soup.find("title")
    if t and title:
        tt = t.get_text(strip=True)
        rest = tt[len(title):] if tt.lower().startswith(title.lower()) else tt
        m = re.match(r"^\s*(?::|by)\s*(.+?)\s*\|", rest)
        if m:
            author = m.group(1)

    genre_block = soup.find(class_="mb-5 flex flex-wrap items-center gap-2")
    genres = ([a.get_text(strip=True) for a in genre_block.find_all("a")]
              if genre_block else [])

    tropes = []
    for block in soup.find_all(class_="flex flex-wrap gap-4"):
        for a in block.find_all("a"):
            v = a.get_text(strip=True)
            if v and v not in tropes:
                tropes.append(v)

    return {"title": title, "author": author, "genres": genres,
            "tropes": tropes, "url": BASE + path}


def find_catalog_match(title, author, catalog_index):
    nt, na = normalize_title(title), normalize_author(author or "")
    best, bt, ba = None, 0, 0
    for entry, ent, ena in catalog_index:
        ts = fuzz.token_sort_ratio(nt, ent)
        if ts < 60:
            continue
        au = fuzz.token_sort_ratio(na, ena)
        if ts * 0.7 + au * 0.3 > bt * 0.7 + ba * 0.3:
            best, bt, ba = entry, ts, au
    if best is not None and bt >= 88 and ba >= 75:
        return best
    return None


def merge_into(entry, scraped):
    """Add tropes/genres to a catalog entry; returns True if anything changed."""
    changed = False

    existing_tropes = entry.get("tropes") or []
    norm = {re.sub(r"[^a-z0-9]", "", t.lower()) for t in existing_tropes}
    for t in scraped["tropes"]:
        if re.sub(r"[^a-z0-9]", "", t.lower()) not in norm:
            existing_tropes.append(t)
            changed = True
    entry["tropes"] = existing_tropes

    genre = entry.get("genre")
    genres = genre if isinstance(genre, list) else ([genre] if genre else [])
    gnorm = {re.sub(r"[^a-z0-9]", "", g.lower()) for g in genres}
    # keep catalog vocabulary: Science Fiction -> Sci-Fi
    for g in scraped["genres"]:
        g = {"Science Fiction": "Sci-Fi"}.get(g, g)
        if re.sub(r"[^a-z0-9]", "", g.lower()) not in gnorm:
            genres.append(g)
            changed = True
    entry["genre"] = genres

    if changed:
        src = entry.get("verifiedSource") or ""
        if "tropetrove" not in src:
            entry["verifiedSource"] = (src + " + " if src else "") + "tropetrove.com"
    return changed


def main():
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    slugs = [a for a in args if not a.startswith("--")]
    if not slugs:
        print(__doc__)
        sys.exit(1)

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_index = [(b, normalize_title(b.get("title") or ""),
                      normalize_author(b.get("author") or "")) for b in catalog]

    all_urls = []
    for slug in slugs:
        print(f"Collecting {slug}...")
        all_urls.extend(collect_genre_urls(slug))
    if limit:
        all_urls = all_urls[:limit]
    print(f"Book pages to scrape: {len(all_urls)}\n")

    updated, unchanged, added, unmatched = 0, 0, 0, []
    for i, path in enumerate(all_urls, 1):
        try:
            s = scrape_book(path)
        except Exception as e:
            print(f"[{i}/{len(all_urls)}] FAILED {path}: {e}")
            continue
        entry = find_catalog_match(s["title"], s["author"], catalog_index)
        if entry is None:
            if s["title"] and s["author"]:
                new = entry_from_scrape(s)
                catalog.append(new)
                catalog_index.append((new, normalize_title(new["title"]),
                                      normalize_author(new["author"])))
                added += 1
                print(f"[{i}/{len(all_urls)}] NEW: {s['title']} by {s['author']} "
                      f"({len(s['tropes'])} tropes)")
            else:
                unmatched.append(s)  # can't add without title+author
        elif merge_into(entry, s):
            updated += 1
            print(f"[{i}/{len(all_urls)}] merged {len(s['tropes'])} tropes -> "
                  f"{entry['title']}")
        else:
            unchanged += 1
        time.sleep(1)

    shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    UNMATCHED_PATH.write_text(json.dumps(unmatched, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    print(f"\nDone. Updated {updated}, added-new {added}, already-complete {unchanged}, "
          f"skipped-incomplete {len(unmatched)} (see tropetrove_unmatched.json)")
    print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
