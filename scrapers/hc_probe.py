#!/usr/bin/env python3
"""
One-off probe: confirm the Hardcover API token works and dump the real
cached_tags structure for a known book, so the enricher's parser can be written
against the actual shape. Reads the token from hardcover_token.txt (never printed).

Usage: python hc_probe.py ["Book Title"]
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import json
import sys
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.hardcover.app/v1/graphql"
TOKEN_FILE = Path(__file__).parent.parent / "hardcover_token.txt"


def token():
    t = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return t if t.lower().startswith("bearer ") else f"Bearer {t}"


def gql(query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": token(),
        "User-Agent": "BookRec personal catalog enricher (contact: local use)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} {e.reason}")
        print("response body (first 500 chars):")
        print(body[:500])
        sys.exit(1)


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "From Blood and Ash"

    # Step 1: search (Typesense) to find the book id.
    sq = """
    query Search($q: String!) {
      search(query: $q, query_type: "Book", per_page: 3, page: 1) { results }
    }
    """
    sr = gql(sq, {"q": title})
    if "errors" in sr:
        print("SEARCH ERRORS:", json.dumps(sr["errors"], indent=2)); return
    results = sr["data"]["search"]["results"]
    hits = results.get("hits", []) if isinstance(results, dict) else []
    print(f"search returned {len(hits)} hit(s). First hit document keys:")
    if hits:
        doc = hits[0].get("document", {})
        print(sorted(doc.keys()))
        print("first hit sample:", json.dumps(doc, indent=2)[:800])
        book_id = doc.get("id")
    else:
        print("no hits"); return

    # Step 2: exact id lookup for cached_tags (ilike is blocked; _eq is fine).
    q = """
    query Probe($id: Int!) {
      books(where: {id: {_eq: $id}}) {
        id title rating users_count
        cached_tags
        contributions { author { name } }
      }
    }
    """
    resp = gql(q, {"id": int(book_id)})
    if "errors" in resp:
        print("BOOK QUERY ERRORS:", json.dumps(resp["errors"], indent=2)); return
    for b in resp["data"]["books"]:
        authors = ", ".join(c["author"]["name"] for c in b.get("contributions", [])
                            if c.get("author"))
        print(f"\nid={b['id']} | {b['title']} by {authors} "
              f"(users_count={b.get('users_count')}, rating={b.get('rating')})")
        print("cached_tags structure:")
        print(json.dumps(b.get("cached_tags"), indent=2)[:3000])


if __name__ == "__main__":
    main()
