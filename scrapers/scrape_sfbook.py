#!/usr/bin/env python3
"""
sfbook.com review scraper -> bookCatalog.json entries.

Usage:
  python scrape_sfbook.py <review-url>           # dry run: print the parsed entry
  python scrape_sfbook.py <review-url> --save    # append to bookCatalog.json
                                                 # (backs up to bookCatalog.backup.json first,
                                                 #  skips books already in the catalog)
  python scrape_sfbook.py --crawl                # crawl ALL Science Fiction reviews via the
                                                 # yearly archive pages (no scrolling needed)
                                                 # and append to bookCatalog.json as it goes
  python scrape_sfbook.py --crawl --limit 5      # test crawl on the first 5 new books
  python scrape_sfbook.py --crawl --genre all    # crawl every genre, not just sci-fi

The site's endless-scroll listing is fed by /api/random (random reviews), so it
can't be paged. Instead the crawl walks archives-1999.htm .. archives-<now>.htm,
which together enumerate every review. Progress is saved to scrape_state.json,
so an interrupted crawl resumes where it left off.

Extraction rules (per spec):
  - Genres: .tag-container -> div.tag.tag--link anchors; tag--series-chip ignored.
  - Tropes: book-tag-group "Key Tropes".
  - Tags:   all other book-tag-group sections (Tone & Pace, Themes, Setting, General)
            plus secondary genre links.
  - Pacing derived from Tone & Pace when possible; spiceLevel N/A (not a romance source).
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import json
import re
import shutil
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

CATALOG_PATH = Path(__file__).parent.parent / "bookCatalog.json"
STATE_PATH = Path(__file__).parent.parent / "scrape_state.json"
ARCHIVE_FIRST_YEAR = 1999
HEADERS = {"User-Agent": "Mozilla/5.0 (personal book-catalog builder)"}

# sfbook genre names -> catalog genre vocabulary
GENRE_MAP = {"Science Fiction": "Sci-Fi", "Fantasy": "Fantasy", "Horror": "Horror",
             "Mystery": "Mystery", "Thriller": "Thriller"}

PACING_MAP = {"fast-paced": "Fast", "action-packed": "Fast",
              "slow-paced": "Slow", "slow burn": "Slow",
              "medium-paced": "Medium", "moderately paced": "Medium"}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def slug_from_url(url):
    return re.sub(r"[^a-z0-9]+", "_", url.rstrip("/").split("/")[-1]
                  .removesuffix(".htm").lower()).strip("_")


def scrape_review(url):
    soup = BeautifulSoup(fetch(url), "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else None

    author = None
    author_span = soup.find("span", string=re.compile(r"Author:"))
    if author_span:
        link = author_span.find_next("a", class_="book-details-link")
        if link:
            author = link.get_text(strip=True)
    if not author:
        # collections/anthologies have no Author: field; fall back to
        # <title> "Book review of X by Author"
        t = soup.find("title")
        m = re.search(r"\bby\s+(.+?)\s*$", t.get_text(strip=True)) if t else None
        if m:
            author = m.group(1)

    # Genres from .tag-container, ignoring the series chip
    genres = []
    container = soup.find(class_="tag-container")
    if container:
        for div in container.find_all("div", class_="tag"):
            classes = div.get("class", [])
            if "tag--series-chip" in classes or "tag--link" not in classes:
                continue
            a = div.find("a")
            if a:
                genres.append(a.get_text(strip=True))

    # book-tag-group sections
    tropes, tags, pacing = [], [], None
    for group in soup.find_all(class_="book-tag-group"):
        label_el = group.find(class_="book-tag-group__label")
        label = label_el.get_text(strip=True) if label_el else ""
        values = [a.get_text(strip=True) for a in group.find_all("a", class_="book-tag")]

        if label == "Key Tropes":
            tropes.extend(values)
        else:
            for v in values:
                if pacing is None and v.lower() in PACING_MAP:
                    pacing = PACING_MAP[v.lower()]
                tags.append(v)

    return {
        "id": slug_from_url(url),
        "title": title,
        "author": author,
        "genre": [GENRE_MAP.get(g, g) for g in genres],
        "tropes": tropes,
        "tags": list(dict.fromkeys(tags)),
        "pacing": pacing,
        "focus": None,
        "spiceLevel": "N/A",
        "contentWarnings": [],
        "verifiedSource": "sfbook.com",
        "sourceUrl": url,
    }


def save_to_catalog(entries):
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)

    existing_ids = {b.get("id") for b in catalog}
    existing_keys = {(str(b.get("title", "")).lower(), str(b.get("author", "")).lower())
                     for b in catalog}

    shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))

    added, skipped = 0, 0
    for e in entries:
        key = (str(e["title"]).lower(), str(e["author"]).lower())
        if e["id"] in existing_ids or key in existing_keys:
            skipped += 1
            continue
        catalog.append(e)
        existing_ids.add(e["id"])
        existing_keys.add(key)
        added += 1

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    return added, skipped


def collect_archive_urls(genre_filter="Science Fiction"):
    """Walk archives-<year>.htm pages and return {url: genre} for every review."""
    found = {}
    for year in range(ARCHIVE_FIRST_YEAR, date.today().year + 1):
        url = f"https://sfbook.com/archives-{year}.htm"
        try:
            soup = BeautifulSoup(fetch(url), "html.parser")
        except Exception as e:
            print(f"  {year}: skipped ({e})")
            continue
        count = 0
        for snippet in soup.find_all(class_="review-snippet"):
            header = snippet.find("h2", class_="item-header")
            link = header.find("a") if header else None
            if not link or not link.get("href"):
                continue
            genre = ""
            for d in snippet.find_all("div", class_="tag"):
                cl = d.get("class", [])
                if any(x in cl for x in ("tag--review", "tag--latest", "tag--series-chip")):
                    continue
                genre = d.get_text(strip=True)
                break
            if genre_filter != "all" and genre != genre_filter:
                continue
            found[link["href"]] = genre
            count += 1
        print(f"  {year}: {count} matching reviews")
        time.sleep(1)
    return found


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"done": [], "failed": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def crawl(genre_filter="Science Fiction", limit=None):
    print(f"Collecting review URLs from archive pages ({genre_filter})...")
    urls = collect_archive_urls(genre_filter)
    print(f"Total reviews found: {len(urls)}")

    state = load_state()
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog_keys = {(str(b.get('title', '')).lower(), str(b.get('author', '')).lower())
                        for b in json.load(f)}

    todo = [u for u in urls if u not in state["done"]]
    if limit:
        todo = todo[:limit]
    print(f"To scrape (new): {len(todo)}\n")

    batch = []
    for i, url in enumerate(todo, 1):
        try:
            entry = scrape_review(url)
            print(f"[{i}/{len(todo)}] {entry['title']} by {entry['author']}")
            key = (str(entry["title"]).lower(), str(entry["author"]).lower())
            if key not in catalog_keys:
                batch.append(entry)
                catalog_keys.add(key)
        except Exception as e:
            print(f"[{i}/{len(todo)}] FAILED {url}: {e}")
            state["failed"].append(url)
        else:
            state["done"].append(url)

        if len(batch) >= 10 or i == len(todo):
            if batch:
                added, skipped = save_to_catalog(batch)
                batch = []
            save_state(state)
        time.sleep(1)  # be polite

    save_state(state)
    print(f"\nCrawl complete. done={len(state['done'])} failed={len(state['failed'])}")
    print("Re-run the same command to resume/retry; state in scrape_state.json")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv

    if "--crawl" in sys.argv:
        genre = "Science Fiction"
        limit = None
        if "--genre" in sys.argv:
            genre = sys.argv[sys.argv.index("--genre") + 1]
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        crawl(genre, limit)
        return

    if not args:
        print(__doc__)
        sys.exit(1)

    entries = []
    for url in args:
        entry = scrape_review(url)
        entries.append(entry)
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        time.sleep(1)  # be polite when scraping multiple pages

    if save:
        added, skipped = save_to_catalog(entries)
        print(f"\nSaved: {added} added, {skipped} already in catalog "
              f"(backup: bookCatalog.backup.json)")
    else:
        print("\nDry run - nothing written. Add --save to append to bookCatalog.json")


if __name__ == "__main__":
    main()
