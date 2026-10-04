#!/usr/bin/env python3
"""
Load the (now author-filled) tropetrove_unmatched.json into bookCatalog.json.

Dedupes by URL, then runs each book through the SAME match-or-add logic the
Trope Trove scraper uses: books that now fuzzy-match an existing catalog entry
are merged into it (tropes/genres added); the rest are added as new entries.

Usage: python load_tropetrove_unmatched.py
Then run `python sync_db.py --refresh` for enrichment + DB sync.
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import json
import shutil
from pathlib import Path

from scrape_tropetrove import entry_from_scrape, merge_into, find_catalog_match
from app import normalize_title, normalize_author

CATALOG = Path("bookCatalog.json")
UNMATCHED = Path("tropetrove_unmatched.json")


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog_index = [(b, normalize_title(b.get("title") or ""),
                      normalize_author(b.get("author") or "")) for b in catalog]

    entries = json.loads(UNMATCHED.read_text(encoding="utf-8"))
    seen, unique = set(), []
    for e in entries:
        if e["url"] in seen:
            continue
        seen.add(e["url"])
        unique.append(e)
    print(f"{len(entries)} entries -> {len(unique)} unique books")

    added, merged, skipped = 0, 0, 0
    for s in unique:
        if not s.get("author"):
            skipped += 1
            continue
        match = find_catalog_match(s["title"], s["author"], catalog_index)
        if match is not None:
            if merge_into(match, s):
                merged += 1
                print(f"  merged -> {match['title']}")
            else:
                skipped += 1
        else:
            new = entry_from_scrape(s)
            catalog.append(new)
            catalog_index.append((new, normalize_title(new["title"]),
                                  normalize_author(new["author"])))
            added += 1

    shutil.copy2(CATALOG, CATALOG.with_name("bookCatalog.backup.json"))
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    print(f"\nAdded {added} new, merged {merged} into existing, "
          f"skipped {skipped}. Catalog now {len(catalog)} books.")
    print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
