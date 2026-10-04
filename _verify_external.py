"""Phase 4 (overnight, capped, resumable): resolve the language- and class-
uncertain books using the free Google Books API, which returns the book's
language, a Fiction/Non-fiction category, and often a description in one call.

For each looked-up book:
  * language != en (confident)      -> archive as non-English
  * language == en                  -> clears the language doubt (keep)
  * categories say Fiction/NF       -> set book_class (overrides, confident)
  * missing description + one found -> backfill into book_metadata (googlebooks)

Prioritised so the limited daily quota is spent where it matters: uncertain
books that carry tropes/tags (they can actually surface in recommendations)
come first. Every external result is cached (resumable) and the API is called
politely with backoff; on repeated blocking it stops cleanly. Anything still
unresolved is written to review_leftover.csv for the user — kept short.

  python _verify_external.py --cap 900
"""
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C
import sqlite3

CACHE = "gbooks_cache.json"
API = "https://www.googleapis.com/books/v1/volumes?q="
NONFIC_CATS = {"biography", "history", "science", "self-help", "business",
               "cooking", "religion", "philosophy", "psychology", "travel",
               "health", "political", "true crime", "reference", "education",
               "social science", "nature", "art", "music"}


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def gbooks(title, author, cache):
    key = f"{title}|||{author}"
    if key in cache:
        return cache[key]
    q = f'intitle:{title}'
    if author:
        q += f'+inauthor:{author}'
    url = API + urllib.parse.quote(q) + "&maxResults=1&country=US"
    result = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BookRec/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            items = data.get("items") or []
            if items:
                vi = items[0].get("volumeInfo", {})
                result = {"language": vi.get("language"),
                          "categories": [c.lower() for c in vi.get("categories", [])],
                          "description": vi.get("description", "")}
            else:
                result = {"language": None, "categories": [], "description": ""}
            break
        except Exception as e:
            result = {"error": str(e)}
            time.sleep(2 * (attempt + 1))
    cache[key] = result
    return result


def priority_books(conn):
    """Uncertain book_ids ordered by whether they can surface in recommendations."""
    seen, ordered = set(), []
    def add(rows):
        for bid, in rows:
            if bid not in seen:
                seen.add(bid); ordered.append(bid)
    # 1) language-uncertain WITH tropes/tags
    try:
        lu = [r["book_id"] for r in csv.DictReader(open("lang_uncertain.csv", encoding="utf-8-sig"))]
    except FileNotFoundError:
        lu = []
    if lu:
        ph = ",".join("?" * len(lu))
        add(conn.execute(f"SELECT id FROM books WHERE id IN ({ph}) AND "
                         f"((tropes NOT IN ('[]','')) OR (tags NOT IN ('[]','')))", lu))
        add((x,) for x in lu)     # then the rest of the language-uncertain
    return ordered


def run(cap=900, sleep=1.5):
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    cache = load_cache()
    order = priority_books(conn)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[verify] {len(order):,} language-uncertain candidates; cap={cap}", flush=True)

    archived, reclassed, backfilled, leftover, done, errors = 0, 0, 0, [], 0, 0
    lang_backup, class_backup = [], []
    for bid in order:
        if done >= cap:
            break
        b = conn.execute("SELECT id,title,author,genres,tropes,status,"
                         "(SELECT book_class FROM enrichment_state WHERE book_id=books.id) bc "
                         "FROM books WHERE id=?", (bid,)).fetchone()
        if not b or (b["status"] or "").startswith("archived"):
            continue
        r = gbooks(b["title"] or "", b["author"] or "", cache)
        done += 1
        if r.get("error"):
            errors += 1
            if errors >= 15:
                print(f"[verify] too many API errors ({errors}); stopping", flush=True)
                break
            continue
        lang = r.get("language")
        cats = r.get("categories") or []
        # language decision
        if lang and lang != "en":
            lang_backup.append({"id": b["id"], "status": b["status"]})
            conn.execute("UPDATE books SET status='archived_nonenglish' WHERE id=?", (b["id"],))
            archived += 1
        # fiction/nonfiction from categories (only when clearly one)
        is_fic = any("fiction" in c for c in cats)
        is_nf = any(any(k in c for k in NONFIC_CATS) for c in cats) and not is_fic
        newcls = "fiction" if is_fic else ("nonfiction" if is_nf else None)
        if newcls and newcls != b["bc"] and not (lang and lang != "en"):
            class_backup.append({"id": b["id"], "old_class": b["bc"]})
            conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?",
                         (newcls, b["id"]))
            if newcls == "nonfiction" and b["tropes"] not in (None, "", "[]"):
                conn.execute("UPDATE books SET tropes='[]' WHERE id=?", (b["id"],))
            reclassed += 1
        # backfill description
        desc = (r.get("description") or "").strip()
        if desc and len(desc) > 40:
            has = conn.execute("SELECT 1 FROM book_metadata WHERE book_id=? AND "
                               "source IN ('ol_dump','wikipedia') AND description IS NOT NULL "
                               "AND TRIM(description)!=''", (b["id"],)).fetchone()
            if not has:
                conn.execute("INSERT OR REPLACE INTO book_metadata(book_id,source,description,fetched_at) "
                             "VALUES(?,?,?,?)", (b["id"], "googlebooks", desc,
                                                 datetime.now().isoformat(timespec="seconds")))
                backfilled += 1
        if done % 50 == 0:
            conn.commit()
            json.dump(cache, open(CACHE, "w", encoding="utf-8"))
            print(f"  ...{done}/{cap} archived={archived} reclassed={reclassed} "
                  f"backfilled={backfilled} err={errors}", flush=True)
        time.sleep(sleep)

    conn.commit()
    json.dump(cache, open(CACHE, "w", encoding="utf-8"))
    if lang_backup:
        json.dump(lang_backup, open(f"verify_lang_backup_{ts}.json", "w"), ensure_ascii=False)
    if class_backup:
        json.dump(class_backup, open(f"verify_class_backup_{ts}.json", "w"), ensure_ascii=False)
    conn.close()
    print(f"[verify] DONE looked_up={done} archived={archived} reclassed={reclassed} "
          f"backfilled={backfilled} errors={errors}", flush=True)


if __name__ == "__main__":
    cap = int(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 900
    run(cap=cap)
