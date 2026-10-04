#!/usr/bin/env python3
"""
Hardcover.app enricher: fills tropes/tags/genre/content-warnings on catalog books
using the official GraphQL API (token in hardcover_token.txt, never printed).

One search call per book returns genres, moods, tags and content_warnings. We
match by title + author (fuzzy), then MERGE — never overwrite. Respects the
60 req/min limit (1 call/sec) and is resumable via hardcover_progress.json.

Usage:
  python hc_enrich.py --book "From Blood and Ash" ["Author"]   # dry run, no write
  python hc_enrich.py --limit 500      # enrich up to 500 books lacking tags, then stop
  python hc_enrich.py                   # enrich all books lacking tropes AND tags
Then: python sync_db.py --refresh
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

from rapidfuzz import fuzz

from app import normalize_title, normalize_author

HERE = Path(__file__).parent.parent   # data files live at the repo root
CATALOG_PATH = HERE / "bookCatalog.json"
TOKEN_FILE = HERE / "hardcover_token.txt"
PROGRESS_FILE = HERE / "hardcover_progress.json"
ENDPOINT = "https://api.hardcover.app/v1/graphql"
DELAY = 1.1  # 60 req/min

# Hardcover genre (lowercased) -> catalog genre. Others in the genres array that
# aren't here become tags (community tropes/themes), minus the junk below.
HC_GENRE = {
    "romance": "Romance", "fantasy": "Fantasy", "science fiction": "Sci-Fi",
    "sci-fi": "Sci-Fi", "horror": "Horror", "mystery": "Mystery",
    "thriller": "Thriller", "suspense": "Thriller", "historical fiction": "Historical Fiction",
    "young adult": "Young Adult", "literary fiction": "Literary Fiction",
    "paranormal": "Paranormal", "graphic novel": "Graphic Novel", "comics": "Graphic Novel",
    "poetry": "Poetry", "horror fiction": "Horror", "crime": "Mystery",
    "contemporary romance": "Romance", "fantasy romance": "Romance",
    "biography": "Biography & Memoir", "memoir": "Biography & Memoir",
    "history": "History", "self-help": "Self-Help", "adventure": "Adventure",
    "western": "Western", "erotica": "Erotica", "short stories": "Short Stories",
}

# Broad noise labels never worth keeping as a genre OR tag.
GENRE_DROP = {"fiction", "nonfiction", "non-fiction", "arts & entertainment",
              "science fiction & fantasy", "adult", "audiobook", "ebook",
              "books", "general"}

# Hardcover "tags" array carries reading-experience votes, not content — drop these.
TAG_JUNK_SUBSTR = ("driven", "character development", "loveable characters",
                   "diverse characters", "a mix", "characters")


def token():
    t = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return t if t.lower().startswith("bearer ") else f"Bearer {t}"


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json", "Authorization": token(),
        "User-Agent": "BookRec personal catalog enricher (local use)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:                     # rate limited -> back off
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise RuntimeError("giving up after repeated 429s")


SEARCH_Q = """
query S($q: String!) {
  search(query: $q, query_type: "Book", per_page: 5, page: 1) { results }
}
"""


def lookup(title, author):
    """Return the best-matching Hardcover doc for title+author, or None."""
    res = gql(SEARCH_Q, {"q": title})
    if "errors" in res:
        return None
    results = res["data"]["search"]["results"]
    hits = results.get("hits", []) if isinstance(results, dict) else []
    nt, na = normalize_title(title), normalize_author(author or "")
    best, best_score = None, 0
    for h in hits:
        doc = h.get("document", {})
        dt = normalize_title(doc.get("title") or "")
        da = normalize_author(", ".join(doc.get("author_names") or []))
        ts = fuzz.token_sort_ratio(nt, dt)
        aus = fuzz.token_sort_ratio(na, da) if na and da else 0
        if ts >= 80 and (aus >= 80 or not na):
            rank = ts + aus + (doc.get("users_count") or 0) / 1e6
            if rank > best_score:
                best, best_score = doc, rank
    return best


def extract(doc):
    """Map a Hardcover doc to (genres, tags, content_warnings) for the catalog."""
    genres, tags = [], []
    for g in doc.get("genres") or []:
        gl = g.strip().lower()
        if gl in GENRE_DROP:
            continue
        if gl in HC_GENRE:
            if HC_GENRE[gl] not in genres:
                genres.append(HC_GENRE[gl])
        else:                                     # trope-ish genre entry -> tag
            if g.strip().lower() not in tags:
                tags.append(g.strip().lower())
    for m in doc.get("moods") or []:              # moods -> tags
        if m.strip().lower() not in tags:
            tags.append(m.strip().lower())
    for t in doc.get("tags") or []:               # community tags, minus vote-junk
        tl = t.strip().lower()
        if tl in GENRE_DROP or any(j in tl for j in TAG_JUNK_SUBSTR):
            continue
        if tl not in tags:
            tags.append(tl)
    cw = [w.strip() for w in (doc.get("content_warnings") or []) if w.strip()]
    return genres, tags, cw


def add_unique(entry, key, values):
    cur = entry.get(key) or []
    norm = {re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in cur}
    changed = False
    for v in values:
        if re.sub(r"[^a-z0-9]", "", str(v).lower()) not in norm:
            cur.append(v)
            norm.add(re.sub(r"[^a-z0-9]", "", str(v).lower()))
            changed = True
    entry[key] = cur
    return changed


def merge(entry, genres, tags, cw):
    changed = False
    changed |= add_unique(entry, "genre", genres)
    changed |= add_unique(entry, "tags", tags)
    changed |= add_unique(entry, "contentWarnings", cw)
    if changed:
        src = entry.get("verifiedSource") or ""
        if "Hardcover" not in src:
            entry["verifiedSource"] = (src + " + " if src else "") + "Hardcover"
    return changed


def main():
    args = sys.argv[1:]

    if "--book" in args:
        i = args.index("--book")
        title = args[i + 1]
        author = args[i + 2] if len(args) > i + 2 and not args[i + 2].startswith("--") else ""
        doc = lookup(title, author)
        if not doc:
            print(f"No confident Hardcover match for {title!r} by {author!r}")
            return
        g, t, cw = extract(doc)
        print(f"Matched: {doc['title']} by {', '.join(doc.get('author_names') or [])} "
              f"(users_count={doc.get('users_count')})")
        print(json.dumps({"genre_add": g, "tags_add": t, "contentWarnings_add": cw},
                         indent=2, ensure_ascii=False))
        return

    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    done = set(json.loads(PROGRESS_FILE.read_text()) if PROGRESS_FILE.exists() else [])

    targets = [b for b in catalog
               if b.get("id") not in done and b.get("title") and b.get("author")
               and not b.get("tropes") and not b.get("tags")]

    # Enrich the most relevant / most-likely-on-Hardcover books first: fiction in
    # popular genres before broad non-fiction and obscure academic titles.
    priority = {"Romance", "Fantasy", "Romantasy", "Sci-Fi", "Mystery", "Thriller",
                "Horror", "Young Adult", "Paranormal", "Historical Fiction",
                "Literary Fiction", "Adventure"}
    def rank(b):
        g = b.get("genre") or []
        g = g if isinstance(g, list) else [g]
        return 0 if any(x in priority for x in g) else 1
    targets.sort(key=rank)
    print(f"{len(targets)} books lacking tropes/tags "
          f"({sum(1 for b in targets if rank(b) == 0):,} priority-fiction first); "
          f"enriching {limit if limit else 'all'} (resumable)...")

    enriched = processed = 0
    for b in targets:
        if limit and processed >= limit:
            break
        processed += 1
        try:
            doc = lookup(b["title"], b["author"])
        except Exception as e:
            print(f"  [{b['id']}] error: {e}")
            time.sleep(DELAY)
            continue
        if doc:
            g, t, cw = extract(doc)
            if merge(b, g, t, cw):
                enriched += 1
        done.add(b["id"])
        if processed % 50 == 0:
            shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
            CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
            PROGRESS_FILE.write_text(json.dumps(sorted(done)))
            print(f"  ...{processed} processed, {enriched} enriched (checkpoint saved)")
        time.sleep(DELAY)

    shutil.copy2(CATALOG_PATH, CATALOG_PATH.with_name("bookCatalog.backup.json"))
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    PROGRESS_FILE.write_text(json.dumps(sorted(done)))
    print(f"\nDone. Processed {processed}, enriched {enriched}. "
          f"Run again to continue, then: python sync_db.py --refresh")


if __name__ == "__main__":
    main()
