"""Phase 5a (partial): fetch stronger descriptions from Wikipedia for books that
have no usable OL description.

Wikipedia plot/synopsis sections are, per the brief, "the best possible
grounding text for trope extraction" - far better than a marketing blurb.

Per book:
  1. search the MediaWiki API for the title (biased toward novels)
  2. for each candidate page, pull the plain-text extract
  3. VERIFY it's the right book: the author surname must appear in the article
     (guards against same-title collisions - the wrong-book trap again)
  4. slice out the Plot / Synopsis / Plot summary section; fall back to the
     intro if there's no plot section
  5. cache to book_metadata as source='wikipedia', fully resumable

Polite: descriptive User-Agent, ~0.5s between calls, single-threaded.

  python _wiki_fetch.py --test          # 12-book yield probe, writes nothing
  python _wiki_fetch.py --limit 200     # real run, caches to book_metadata
"""
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from rapidfuzz import fuzz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

UA = "BookRecEnrichment/1.0 (personal recommendation catalogue; contact: local)"
API = "https://en.wikipedia.org/w/api.php"
DELAY = 0.5


_last_call = [0.0]
MIN_INTERVAL = 1.0     # min seconds between ANY two API calls (be a good citizen)


def _get(params, tries=5):
    """Rate-limited, with escalating backoff on the 429s Wikipedia throws under
    bursty load. Bursts (search + several extracts per book) were the cause."""
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(tries):
        gap = time.time() - _last_call[0]
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                _last_call[0] = time.time()
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            _last_call[0] = time.time()
            if e.code == 429 and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))      # 5,10,15,20s
                continue
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
        except Exception:
            _last_call[0] = time.time()
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def search(title):
    d = _get({"action": "query", "list": "search",
              "srsearch": f'{title} novel', "srlimit": 6})
    return [h["title"] for h in d.get("query", {}).get("search", [])]


def extract(page):
    d = _get({"action": "query", "prop": "extracts", "explaintext": 1,
              "redirects": 1, "titles": page})
    for _, p in d.get("query", {}).get("pages", {}).items():
        return p.get("extract", "") or ""
    return ""


def author_ok(text, author):
    """Require the SURNAME as a whole word. Matching first names ('Barbara',
    'David') is what let 'Under Pressure' match Stephen King's 'Under the Dome'
    and 'ShadowBreed' match a disambiguation page."""
    if not author:
        return False                       # no author = can't verify = reject
    # surname = last alphabetic token; also try the first if it's long/distinctive
    parts = [p for p in re.split(r"[\s,]+", author) if re.search(r"[A-Za-z]", p)]
    surnames = [p for p in ([parts[-1]] if parts else []) if len(p) >= 3]
    for s in surnames:
        if re.search(r"\b" + re.escape(s) + r"\b", text, re.I):
            return True
    return False


def is_disambig(page, text):
    return ("(disambiguation)" in page.lower()
            or bool(re.search(r"\bmay (also )?refer to\b", text[:400], re.I)))


PLOT_RE = re.compile(r"\n==+\s*(Plot|Synopsis|Plot summary|Story|Premise)\s*==+\n",
                     re.I)


def plot_section(text):
    m = PLOT_RE.search(text)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"\n==+\s*[^=]+\s*==+\n", text[start:])
    body = text[start: start + nxt.start()] if nxt else text[start:]
    return " ".join(body.split())


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\([^)]*\)", "", s.lower())).strip()


def title_ok(book_title, page):
    """Guard author-collision: the page must actually be about THIS title, not a
    different novel by the same author. Page title fuzzy-matches, or the book
    title is a clean substring."""
    bt, pt = _norm(book_title), _norm(page)
    if not bt:
        return False
    if bt in pt or pt in bt:
        return True
    return fuzz.token_sort_ratio(bt, pt) >= 72


def best_description(title, author):
    for page in search(title):
        if not title_ok(title, page):
            continue
        text = extract(page)
        if len(text) < 200 or is_disambig(page, text) or not author_ok(text, author):
            continue
        plot = plot_section(text)
        if len(plot) >= 200:
            return page, "plot", plot[:1500]
        intro = " ".join(text.split())[:1200]
        if len(intro) >= 200:
            return page, "intro", intro
    return None, None, None


def candidates(limit):
    conn = sqlite3.connect(C.DB_PATH, timeout=180)
    conn.row_factory = sqlite3.Row
    GEN = ("(b.genres LIKE '%Mystery%' OR b.genres LIKE '%crime%' "
           "OR b.genres LIKE '%Thriller%')")
    # exclude anything already ATTEMPTED - a hit ('wikipedia') OR a recorded
    # miss ('wikipedia_miss'). Without the miss marker, un-findable books never
    # leave the pool and a chunked loop spins on them forever.
    rows = conn.execute(f"""SELECT b.id, b.title, b.author
        FROM books b JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata m ON m.book_id=b.id AND m.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source IN ('wikipedia','wikipedia_miss')
        WHERE {GEN} AND s.book_class='fiction' AND (b.tropes IS NULL OR b.tropes='[]')
          AND (m.description IS NULL OR TRIM(m.description)='')
          AND w.book_id IS NULL AND b.author IS NOT NULL AND b.author!=''
        ORDER BY b.id LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return rows


def fetch_all(log=print):
    """Single pass over every remaining candidate. Hits -> 'wikipedia'; misses
    -> a 'wikipedia_miss' sentinel so they are never retried. Resumable."""
    rows = candidates(10 ** 9)
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    hits = 0
    for i, r in enumerate(rows, 1):
        try:
            page, kind, desc = best_description(r["title"], r["author"])
        except Exception:
            desc = None
        time.sleep(DELAY)
        if desc:
            hits += 1
            conn.execute("INSERT OR REPLACE INTO book_metadata "
                         "(book_id, source, description, subjects) VALUES (?, 'wikipedia', ?, ?)",
                         (r["id"], desc, json.dumps({"page": page, "kind": kind})))
        else:
            conn.execute("INSERT OR REPLACE INTO book_metadata "
                         "(book_id, source, description, subjects) VALUES (?, 'wikipedia_miss', '', '')",
                         (r["id"],))
        if i % 50 == 0:
            conn.commit()
            log(f"  ...{i}/{len(rows)} | {hits} found")
    conn.commit()
    conn.close()
    log(f"fetch_all done: {hits}/{len(rows)} descriptions from this pass")
    return hits, len(rows)


def main():
    if "--test" in sys.argv:
        tests = [("The Girl with the Dragon Tattoo", "Stieg Larsson"),
                 ("Gerald's Game", "Stephen King"), ("Dead Lines", "Greg Bear"),
                 ("Loyalty", "E. J. Noyes"), ("Archer Securities", "Jove Belle"),
                 ("Under Pressure", "Barbara Winkes"), ("Antarctica", "Katherine Rupley"),
                 ("In the Woods", "Tana French"), ("Big Little Lies", "Liane Moriarty"),
                 ("The Cuckoo's Calling", "Robert Galbraith"),
                 ("Trailhead", "C. Jean Downer"), ("ShadowBreed", "David Ferring")]
        hits = 0
        for title, author in tests:
            try:
                page, kind, desc = best_description(title, author)
            except Exception as e:
                print(f"ERR          {title[:34]:<36} {type(e).__name__}"); continue
            time.sleep(DELAY)
            if desc:
                hits += 1
                print(f"HIT  [{kind:<5}] {title[:34]:<36} -> {page[:34]}")
                print(f"        {desc[:140]}...")
            else:
                print(f"miss         {title[:34]:<36} ({author})")
        print(f"\n{hits}/{len(tests)} found")
        return

    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 100
    rows = candidates(limit)
    conn = sqlite3.connect(C.DB_PATH, timeout=180)
    hits = 0
    for i, r in enumerate(rows, 1):
        try:
            page, kind, desc = best_description(r["title"], r["author"])
        except Exception:
            desc = None
        time.sleep(DELAY)
        if desc:
            hits += 1
            conn.execute("INSERT OR REPLACE INTO book_metadata (book_id, source, description, subjects) VALUES (?, 'wikipedia', ?, ?)",
                         (r["id"], desc, json.dumps({"page": page, "kind": kind})))
        if i % 25 == 0:
            conn.commit(); print(f"  ...{i}/{len(rows)} | {hits} found", flush=True)
    conn.commit(); conn.close()
    print(f"done: {hits}/{len(rows)} Wikipedia descriptions cached")


if __name__ == "__main__":
    main()
