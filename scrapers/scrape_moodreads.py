#!/usr/bin/env python3
"""
MoodReads (moodreads.app) scraper -> merges into bookCatalog.json and adds
unmatched books as new entries (same behaviour as the other scrapers).

MoodReads is a fantasy-romance / romantasy site with per-book tropes, moods,
creatures, spice level and content warnings — a strong match for this catalog.

Its /browse feed is infinite-scroll backed by /api/ (which robots.txt disallows),
but individual books live at /book/<numeric-id> (allowed), so this crawls by ID.

Usage:
  python scrape_moodreads.py --book 101            # dry-run a single book
  python scrape_moodreads.py 1 500                 # ids 1..500 inclusive
  python scrape_moodreads.py 1 500 --limit 20      # first 20 found in that range
  python scrape_moodreads.py 501 1000              # resume a later slice

Mapping to catalog fields:
  - genre   : schema.org JSON-LD genre (e.g. Romance).
  - tropes  : the book's Tropes list (clean display names).
  - tags    : Moods + Creatures.
  - spiceLevel   : from "Spice Level N/5" / contentRating, canonicalised.
  - contentWarnings : the listed content warnings.
  - verifiedSource amended to include "MoodReads".

robots.txt: /book/ is allowed (general User-agent: *); /api/, /search, /login,
etc. are not and are never touched. Note the site signals Content-Signal
ai-train=no — this tool builds a personal reference catalog (use=reference), not
training data. A 1s delay is used between requests.
Run `python sync_db.py --refresh` afterwards to update the app DB.
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
import urllib.error
from pathlib import Path

from bs4 import BeautifulSoup

from scrape_tropetrove import find_catalog_match
from app import normalize_title, normalize_author, canonical_spice

CATALOG_PATH = Path(__file__).parent.parent / "bookCatalog.json"
UNMATCHED_PATH = Path(__file__).parent.parent / "moodreads_unmatched.json"
BASE = "https://moodreads.app"


def atomic_write_json(path, data, indent=2):
    """Write JSON atomically: dump to a temp file on the same filesystem, fsync,
    then os.replace() into place. A crash mid-write leaves the previous complete
    file intact instead of a truncated, unparseable one (which is how an
    overnight crash corrupted the 49 MB catalog on 2026-07-25)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.flush()
        _os.fsync(f.fileno())
    _os.replace(tmp, path)          # atomic on the same filesystem
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# MoodReads spice (numeric /5 or word) -> catalog canonical spice level
SPICE_NUM = {0: "No Spice", 1: "Tame", 2: "Tame", 3: "Medium Spice",
             4: "Explicit", 5: "Explicit"}
SPICE_WORD = {"none": "No Spice", "low": "Tame", "mild": "Tame",
              "medium": "Medium Spice", "high": "Explicit", "extreme": "Explicit"}


def fetch(url, _tries=4):
    """Fetch politely. On 403 (MoodReads throttling sustained crawls) back off
    hard and retry rather than skipping the book — the previous fast run lost
    ~13k books to un-retried 403s."""
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    for attempt in range(_tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 403 and attempt < _tries - 1:
                cool = 60 * (attempt + 1)      # 60s, 120s, 180s
                print(f"    403 — cooling off {cool}s (attempt {attempt+1})", flush=True)
                time.sleep(cool)
                continue
            raise
    raise RuntimeError("unreachable")


def _clean_links(soup, category):
    """Anchor display text under /<category>/ links, minus 'more … →' nav."""
    out = []
    for a in soup.find_all("a", href=re.compile(rf"^/{category}/[^?#]+$")):
        t = a.get_text(strip=True)
        if not t or "→" in t or t.lower().startswith("more ") or len(t) > 45:
            continue
        if t not in out:
            out.append(t)
    return out


def _spice(title_text, content_rating):
    m = re.search(r"Spice(?:\s*Level)?\s*(\d)\s*/\s*5", title_text or "")
    if m:
        return SPICE_NUM.get(int(m.group(1)))
    if content_rating:
        w = re.sub(r"(?i)spice[:\s]*", "", content_rating).strip().lower()
        if w in SPICE_WORD:
            return SPICE_WORD[w]
    return canonical_spice(content_rating)


def scrape_book(book_id):
    html = fetch(f"{BASE}/book/{book_id}")
    soup = BeautifulSoup(html, "html.parser")

    title = author = genre = content_rating = None
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.get_text())
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in (data.get("@graph", [data]) if isinstance(data, dict) else data):
            if isinstance(obj, dict) and obj.get("@type") == "Book":
                title = obj.get("name")
                a = obj.get("author")
                if isinstance(a, list):
                    author = ", ".join(x.get("name", "") for x in a if isinstance(x, dict))
                elif isinstance(a, dict):
                    author = a.get("name")
                genre = obj.get("genre")
                content_rating = obj.get("contentRating")
    if not title:
        return None

    title_tag = soup.find("title")
    spice = _spice(title_tag.get_text() if title_tag else "", content_rating)

    tropes = _clean_links(soup, "tropes")
    tags = _clean_links(soup, "mood") + _clean_links(soup, "creature")

    cw = []
    m = re.search(r"Content warnings for [^:]+ include:\s*([^.\"]+)", html)
    if m:
        cw = [w.strip() for w in m.group(1).split(",") if w.strip()]

    genres = [genre] if isinstance(genre, str) and genre else (genre or [])
    return {"id": f"moodreads_{book_id}", "title": title, "author": author,
            "genres": genres, "tropes": tropes, "tags": tags, "spice": spice,
            "cw": cw, "url": f"{BASE}/book/{book_id}"}


def entry_from_scrape(s):
    return {
        "id": s["id"], "title": s["title"], "author": s["author"],
        "genre": s["genres"], "tropes": s["tropes"], "tags": s["tags"],
        "pacing": None, "focus": None, "spiceLevel": s["spice"] or "N/A",
        "contentWarnings": s["cw"],
        "verifiedSource": "MoodReads", "sourceUrl": s["url"],
    }


def _add_unique(entry, key, values):
    cur = entry.get(key) or []
    if isinstance(cur, str):                 # legacy scalar field -> coerce to list
        cur = [cur] if cur else []
    norm = {re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in cur}
    changed = False
    for v in values:
        if re.sub(r"[^a-z0-9]", "", str(v).lower()) not in norm:
            cur.append(v)
            norm.add(re.sub(r"[^a-z0-9]", "", str(v).lower()))
            changed = True
    entry[key] = cur
    return changed


def merge_into(entry, s):
    changed = False
    changed |= _add_unique(entry, "genre", s["genres"])
    changed |= _add_unique(entry, "tropes", s["tropes"])
    changed |= _add_unique(entry, "tags", s["tags"])
    changed |= _add_unique(entry, "contentWarnings", s["cw"])
    # fill spice only if the catalog entry lacks it
    if s["spice"] and (entry.get("spiceLevel") in (None, "", "N/A")):
        entry["spiceLevel"] = s["spice"]
        changed = True
    if changed:
        src = entry.get("verifiedSource") or ""
        if "MoodReads" not in src:
            entry["verifiedSource"] = (src + " + " if src else "") + "MoodReads"
    return changed


def main():
    args = sys.argv[1:]

    if "--book" in args:
        s = scrape_book(args[args.index("--book") + 1])
        print(json.dumps(entry_from_scrape(s) if s else None, indent=2, ensure_ascii=False))
        return

    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]
    delay = 1.1
    if "--delay" in args:
        i = args.index("--delay")
        delay = float(args[i + 1])
        del args[i:i + 2]              # consume the value too, or it reads as positional
    nums = [int(a) for a in args if not a.startswith("--") and a.isdigit()]
    if len(nums) != 2:
        print(__doc__)
        sys.exit(1)
    start, end = nums

    # resumable: never re-fetch an id we've already processed
    prog_path = Path(__file__).parent.parent / "moodreads_progress.json"
    done_ids = set(json.loads(prog_path.read_text())) if prog_path.exists() else set()
    if done_ids:
        print(f"resuming: {len(done_ids):,} ids already processed")

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_index = [(b, normalize_title(b.get("title") or ""),
                      normalize_author(b.get("author") or "")) for b in catalog]

    updated, added, unchanged, missing = 0, 0, 0, 0
    unmatched = []
    processed_now = 0
    for book_id in range(start, end + 1):
        if book_id in done_ids:
            continue
        try:
            s = scrape_book(book_id)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                missing += 1
                done_ids.add(book_id)          # 404 is terminal, don't retry later
            else:
                print(f"[{book_id}] HTTP {e.code} (will retry on a later run)")
            time.sleep(delay)
            continue
        except Exception as e:
            print(f"[{book_id}] FAILED: {e}")
            time.sleep(delay)
            continue
        done_ids.add(book_id)
        processed_now += 1
        if processed_now % 25 == 0:            # checkpoint + save catalog
            # back up the last-good catalog, then write the new one atomically
            if CATALOG_PATH.exists():
                shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
            atomic_write_json(CATALOG_PATH, catalog)
            prog_path.write_text(json.dumps(sorted(done_ids)))
        time.sleep(delay)
        if not s or not s["title"] or not s["author"]:
            missing += 1
            continue
        match = find_catalog_match(s["title"], s["author"], catalog_index)
        if match is None:
            new = entry_from_scrape(s)
            catalog.append(new)
            catalog_index.append((new, normalize_title(new["title"]),
                                  normalize_author(new["author"])))
            added += 1
            print(f"[{book_id}] NEW: {s['title']} by {s['author']} "
                  f"({len(s['tropes'])} tropes, spice {s['spice']})")
        elif merge_into(match, s):
            updated += 1
            print(f"[{book_id}] merged -> {match['title']}")
        else:
            unchanged += 1
        if limit and (added + updated) >= limit:
            break

    if CATALOG_PATH.exists():
        shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
    atomic_write_json(CATALOG_PATH, catalog)
    UNMATCHED_PATH.write_text(json.dumps(unmatched, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    prog_path.write_text(json.dumps(sorted(done_ids)))

    print(f"\nDone. Added {added}, updated {updated}, already-complete {unchanged}, "
          f"missing/empty ids {missing}. Processed this run: {processed_now}.")
    print("Now run: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
