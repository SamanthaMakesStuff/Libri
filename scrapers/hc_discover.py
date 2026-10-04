#!/usr/bin/env python3
"""
Hardcover discovery: ADD popular books that aren't in the catalog yet, with full
genre/tags/content-warnings. Browses the books table by popularity (users_count),
100 per query, so it's far faster than per-book search.

Usage:
  python hc_discover.py --survey                 # count new books, write nothing
  python hc_discover.py --floor 30               # add new books with users_count >= 30
  python hc_discover.py --floor 30 --limit 5000  # stop after adding 5000
Then: python sync_db.py --refresh

Resumable via hardcover_discover_progress.json (stores the last page offset).
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

from app import normalize_title, normalize_author
from hc_enrich import gql, HC_GENRE, GENRE_DROP, TAG_JUNK_SUBSTR

HERE = Path(__file__).parent.parent   # data files live at the repo root
CATALOG_PATH = HERE / "bookCatalog.json"
PROGRESS = HERE / "hardcover_discover_progress.json"
PAGE = 100
DELAY = 1.1

BROWSE_Q = """
query Browse($lim: Int!, $off: Int!) {
  books(order_by: {users_count: desc_nulls_last}, limit: $lim, offset: $off) {
    id title users_count
    cached_tags
    contributions { author { name } }
  }
}
"""


def extract_cached(ct):
    """Map a book's cached_tags jsonb to (genres, tags, content_warnings)."""
    if not isinstance(ct, dict):
        return [], [], []
    genres, tags, cw = [], [], []
    for e in ct.get("Genre", []):
        g = (e.get("tag") or "").strip()
        gl = g.lower()
        if not gl or gl in GENRE_DROP:
            continue
        if gl in HC_GENRE:
            if HC_GENRE[gl] not in genres:
                genres.append(HC_GENRE[gl])
        elif gl not in tags:
            tags.append(gl)
    for e in ct.get("Mood", []):
        m = (e.get("tag") or "").strip().lower()
        if m and m not in tags:
            tags.append(m)
    for e in ct.get("Tag", []):
        t = (e.get("tag") or "").strip().lower()
        if not t or t in GENRE_DROP or any(j in t for j in TAG_JUNK_SUBSTR):
            continue
        if t not in tags:
            tags.append(t)
    for e in ct.get("Content Warning", []):
        w = (e.get("tag") or "").strip()
        if w and w not in cw:
            cw.append(w)
    return genres, tags, cw


def main():
    args = sys.argv[1:]
    survey = "--survey" in args
    floor = int(args[args.index("--floor") + 1]) if "--floor" in args else 30
    add_limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    max_books = int(args[args.index("--max-books") + 1]) if "--max-books" in args else 200000

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    have = {(normalize_title(b.get("title") or ""), normalize_author(b.get("author") or ""))
            for b in catalog}

    offset = 0
    if not survey and PROGRESS.exists():
        offset = json.loads(PROGRESS.read_text()).get("offset", 0)

    scanned = added = skip_have = skip_notags = skip_noauthor = 0
    print(f"{'SURVEY' if survey else 'ADD'} mode | floor users_count>={floor} | "
          f"starting offset {offset}")

    while scanned < max_books:
        r = gql(BROWSE_Q, {"lim": PAGE, "off": offset})
        if "errors" in r:
            print("API errors:", json.dumps(r["errors"])[:300]); break
        books = r["data"]["books"]
        if not books:
            print("reached end of catalog."); break

        stop = False
        for b in books:
            scanned += 1
            if (b.get("users_count") or 0) < floor:
                stop = True                       # sorted desc -> we're past the floor
                break
            author = ", ".join(c["author"]["name"] for c in (b.get("contributions") or [])
                               if c.get("author"))
            if not author or not b.get("title"):
                skip_noauthor += 1
                continue
            key = (normalize_title(b["title"]), normalize_author(author))
            if key in have:
                skip_have += 1
                continue
            genres, tags, cw = extract_cached(b.get("cached_tags"))
            if not tags:                          # must be recommendable
                skip_notags += 1
                continue
            have.add(key)
            added += 1
            if not survey:
                catalog.append({
                    "id": f"hardcover_{b['id']}", "title": b["title"], "author": author,
                    "genre": genres, "tropes": [], "tags": tags,
                    "pacing": None, "focus": None, "spiceLevel": "N/A",
                    "contentWarnings": cw,
                    "verifiedSource": "Hardcover",
                    "sourceUrl": f"https://hardcover.app/books/{b['id']}",
                })
            if add_limit and added >= add_limit:
                stop = True
                break

        offset += len(books)
        if not survey and added and added % 1000 < PAGE:
            shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
            CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
            PROGRESS.write_text(json.dumps({"offset": offset}))
        if scanned % 2000 < PAGE:
            print(f"  scanned {scanned:,} | new added {added:,} | "
                  f"already-have {skip_have:,} | no-tags {skip_notags:,}")
        if stop:
            break
        time.sleep(DELAY)

    if not survey:
        shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
        CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        PROGRESS.write_text(json.dumps({"offset": offset}))

    print(f"\n{'SURVEY' if survey else 'DONE'}: scanned {scanned:,}, "
          f"{'would add' if survey else 'added'} {added:,} new books "
          f"(skipped {skip_have:,} already-have, {skip_notags:,} no-tags).")
    if not survey:
        print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
