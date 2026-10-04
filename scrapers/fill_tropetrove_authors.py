#!/usr/bin/env python3
"""
Fill missing authors in tropetrove_unmatched.json by reading each book page.

Trope Trove pages with series info put the series (not the author) in the
<title>, so the scraper left author=null. The author is reliably in the page's
schema.org JSON-LD (and the "by <author>" byline as a fallback).

Usage: python fill_tropetrove_authors.py
Writes tropetrove_unmatched.json in place (backup: tropetrove_unmatched.backup.json).
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import json
import re
import shutil
import time
from pathlib import Path

from bs4 import BeautifulSoup

from scrape_sfbook import fetch

FILE = Path(__file__).parent.parent / "tropetrove_unmatched.json"


def get_author(url):
    soup = BeautifulSoup(fetch(url), "html.parser")

    # 1) schema.org JSON-LD Book.author
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.get_text())
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") == "Book" and obj.get("author"):
                a = obj["author"]
                names = [x.get("name") for x in (a if isinstance(a, list) else [a])
                         if isinstance(x, dict) and x.get("name")]
                if names:
                    return ", ".join(names)

    # 2) byline: "by <a href='/authors/...'>Name</a>"
    for a in soup.find_all("a", href=re.compile(r"/authors/[a-z0-9-]+$")):
        name = a.get_text(strip=True)
        if name and name.lower() != "authors":
            return name
    return None


def main():
    data = json.loads(FILE.read_text(encoding="utf-8"))
    shutil.copy2(FILE, FILE.with_name("tropetrove_unmatched.backup.json"))

    cache = {}
    filled = failed = 0
    for entry in data:
        if entry.get("author"):
            continue
        url = entry["url"]
        if url not in cache:
            try:
                cache[url] = get_author(url)
            except Exception as e:
                print(f"FAILED {url}: {e}")
                cache[url] = None
            time.sleep(1)
        author = cache[url]
        if author:
            entry["author"] = author
            filled += 1
            print(f"{entry['title']!r:50} -> {author}")
        else:
            failed += 1
            print(f"{entry['title']!r:50} -> (no author found)")

    FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Filled {filled}, still missing {failed}, "
          f"unique pages fetched {len(cache)}.")


if __name__ == "__main__":
    main()
