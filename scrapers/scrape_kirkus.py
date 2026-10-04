#!/usr/bin/env python3
"""
Kirkus Reviews scraper -> merges genre/categories into bookCatalog.json and adds
unmatched books as new entries (same behaviour as scrape_tropetrove.py).

Kirkus is browsed genre by genre. Each genre's archive is paginated 6 books per
page and goes all the way back (not just recent books), so no search is needed:
    https://www.kirkusreviews.com/discover-books/<genre-slug>?page=N

Usage:
  python scrape_kirkus.py fiction                 # one genre, all pages (SLOW)
  python scrape_kirkus.py fiction --limit 10      # test on first 10 books
  python scrape_kirkus.py fiction --start 250     # begin at page 250 (resume/skip)
  python scrape_kirkus.py fiction --start 250 --limit 60   # 60 books from page 250 on
  python scrape_kirkus.py romance mystery-detective
  python scrape_kirkus.py --book https://www.kirkusreviews.com/book-reviews/a/b/

Genre slugs (from the site nav): fiction, romance, mystery-detective,
thriller-suspense, science-fiction-fantasy, teen, childrens, nonfiction,
biography-memoir, history, graphic-novels-comics.

Data available (Kirkus is an editorial review site):
  - genre : the book's "Categories" (e.g. LITERARY FICTION, HISTORICAL FICTION),
            mapped to catalog genre vocabulary; unrecognised ones become tags.
  - title/author : from the page's schema.org JSON-LD.
  - tropes/reader-tags : NONE — Kirkus has no reader-trope or folksonomy data.
  - verifiedSource amended to include "Kirkus Reviews" on updated books.

robots.txt: /discover-books/ and /book-reviews/<author>/<title>/ are allowed;
/search/ and the old /book-reviews/<category>/ indexes are not (unused here).
Crawl-delay is 10s and is respected between every request, so full-genre crawls
take hours. Run `python sync_db.py --refresh` afterwards to update the app DB.
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
from pathlib import Path

from bs4 import BeautifulSoup

from scrape_tropetrove import find_catalog_match
from app import normalize_title, normalize_author

CATALOG_PATH = Path(__file__).parent.parent / "bookCatalog.json"
UNMATCHED_PATH = Path(__file__).parent.parent / "kirkus_unmatched.json"
BASE = "https://www.kirkusreviews.com"
CRAWL_DELAY = 10  # robots.txt Crawl-delay for User-agent: *
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Kirkus category (UPPERCASE) -> catalog GENRE. Unlisted categories become tags.
KIRKUS_GENRE = {
    "SCIENCE FICTION": "Sci-Fi", "SCIENCE FICTION & FANTASY": "Sci-Fi",
    "FANTASY": "Fantasy", "ROMANCE": "Romance",
    "MYSTERY": "Mystery", "MYSTERY & DETECTIVE": "Mystery", "DETECTIVE": "Mystery",
    "THRILLER": "Thriller", "THRILLER & SUSPENSE": "Thriller", "SUSPENSE": "Thriller",
    "HORROR": "Horror", "LITERARY FICTION": "Literary Fiction",
    "HISTORICAL FICTION": "Historical Fiction", "GENERAL FICTION": "Fiction",
    "GRAPHIC NOVELS & COMICS": "Graphic Novel", "GRAPHIC NOVELS": "Graphic Novel",
}

# Category labels that are section headers / noise, not genres or tags.
CATEGORY_DROP = {"FICTION", "NONFICTION", "BOOK REVIEWS"}


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    time.sleep(CRAWL_DELAY)  # be polite: honour robots Crawl-delay
    return html


def smart_title(s):
    """Kirkus JSON-LD titles are ALL CAPS -> readable title case (keeps 'Don't')."""
    if not s or not s.isupper():
        return s
    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?",
                  lambda m: m.group(0)[0] + m.group(0)[1:].lower(), s)


def classify_categories(cats):
    """Split Kirkus categories into (genres, tags) using catalog vocabulary."""
    genres, tags = [], []
    for c in cats:
        cu = c.strip().upper()
        if cu in CATEGORY_DROP:
            continue
        if cu in KIRKUS_GENRE:
            g = KIRKUS_GENRE[cu]
            if g not in genres:
                genres.append(g)
        else:
            t = c.strip().lower()
            if t not in tags:
                tags.append(t)
    return genres, tags


def scrape_book(url):
    soup = BeautifulSoup(_fetch(url), "html.parser")

    title = author = None
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.get_text())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            data = next((d for d in data if d.get("@type") == "Book"), None)
        if data and data.get("@type") == "Book":
            title = smart_title(data.get("name"))
            a = data.get("author")
            if isinstance(a, list):
                author = ", ".join(x.get("name", "") for x in a).strip(", ")
            elif isinstance(a, dict):
                author = a.get("name")
            break

    # The main book's Categories block shares an ancestor with the <h1>.
    cats = []
    label = soup.find(string=re.compile(r"Categories?:"))
    if label:
        c = label.parent
        links = []
        for _ in range(4):
            links = c.find_all("a", href=re.compile(r"/discover-books/[^/]+/"))
            if links:
                break
            c = c.parent
        for a in links:
            t = a.get_text(strip=True)
            if t and t not in cats:
                cats.append(t)

    genres, tags = classify_categories(cats)
    return {"title": title, "author": author, "genres": genres, "tags": tags,
            "url": url}


def entry_from_scrape(s):
    return {
        "id": "kirkus_" + re.sub(r"[^a-z0-9]+", "_",
                                 s["url"].rstrip("/").split("/book-reviews/")[-1]).strip("_"),
        "title": s["title"], "author": s["author"],
        "genre": s["genres"], "tropes": [], "tags": s["tags"],
        "pacing": None, "focus": None, "spiceLevel": "N/A", "contentWarnings": [],
        "verifiedSource": "Kirkus Reviews", "sourceUrl": s["url"],
    }


def merge_into(entry, s):
    changed = False
    cur = entry.get("genre")
    genres = cur if isinstance(cur, list) else ([cur] if cur else [])
    gnorm = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in genres}
    for g in s["genres"]:
        if re.sub(r"[^a-z0-9]", "", g.lower()) not in gnorm:
            genres.append(g)
            gnorm.add(re.sub(r"[^a-z0-9]", "", g.lower()))
            changed = True
    entry["genre"] = genres

    tags = entry.get("tags") or []
    tnorm = {re.sub(r"[^a-z0-9]", "", t.lower()) for t in tags}
    for t in s["tags"]:
        if re.sub(r"[^a-z0-9]", "", t.lower()) not in tnorm:
            tags.append(t)
            tnorm.add(re.sub(r"[^a-z0-9]", "", t.lower()))
            changed = True
    entry["tags"] = tags

    if changed:
        src = entry.get("verifiedSource") or ""
        if "Kirkus" not in src:
            entry["verifiedSource"] = (src + " + " if src else "") + "Kirkus Reviews"
    return changed


def collect_listing(slug, cap=None, start_page=1):
    """Walk /discover-books/<slug>?page=N from start_page; return book-review URLs."""
    urls, page = [], start_page
    while True:
        html = _fetch(f"{BASE}/discover-books/{slug}?page={page}")
        soup = BeautifulSoup(html, "html.parser")
        page_urls = []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if h.startswith("/book-reviews/") and h.count("/") >= 3:
                full = BASE + h
                if full not in urls and full not in page_urls:
                    page_urls.append(full)
        if not page_urls:
            break
        urls.extend(page_urls)
        print(f"  {slug} page {page}: {len(page_urls)} books (total {len(urls)})")
        if cap and len(urls) >= cap:
            break
        page += 1
    return urls


def main():
    args = sys.argv[1:]

    if "--book" in args:
        s = scrape_book(args[args.index("--book") + 1])
        print(json.dumps(entry_from_scrape(s), indent=2, ensure_ascii=False))
        return

    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    start_page = 1
    if "--start" in args:
        i = args.index("--start")
        start_page = int(args[i + 1])
        del args[i:i + 2]
    slugs = [a for a in args if not a.startswith("--")]
    if not slugs:
        print(__doc__)
        sys.exit(1)

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_index = [(b, normalize_title(b.get("title") or ""),
                      normalize_author(b.get("author") or "")) for b in catalog]

    urls = []
    for slug in slugs:
        print(f"Collecting {slug} (from page {start_page})...")
        urls.extend(collect_listing(slug, cap=limit, start_page=start_page))
    if limit:
        urls = urls[:limit]
    print(f"Book pages to scrape: {len(urls)}\n")

    updated, added, unchanged, unmatched = 0, 0, 0, []
    for i, url in enumerate(urls, 1):
        try:
            s = scrape_book(url)
        except Exception as e:
            print(f"[{i}/{len(urls)}] FAILED {url}: {e}")
            continue
        if not s["title"] or not s["author"]:
            unmatched.append({"url": url, "reason": "missing title/author"})
            continue
        entry = find_catalog_match(s["title"], s["author"], catalog_index)
        if entry is None:
            new = entry_from_scrape(s)
            catalog.append(new)
            catalog_index.append((new, normalize_title(new["title"]),
                                  normalize_author(new["author"])))
            added += 1
            print(f"[{i}/{len(urls)}] NEW: {s['title']} by {s['author']} "
                  f"({'/'.join(s['genres']) or 'no genre'})")
        elif merge_into(entry, s):
            updated += 1
            print(f"[{i}/{len(urls)}] merged -> {entry['title']}")
        else:
            unchanged += 1

    shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    UNMATCHED_PATH.write_text(json.dumps(unmatched, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    print(f"\nDone. Updated {updated}, added-new {added}, already-complete {unchanged}, "
          f"skipped-incomplete {len(unmatched)} (see kirkus_unmatched.json)")
    print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
