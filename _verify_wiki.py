"""External validation via Wikipedia (the only reachable source — Google Books
is 429-blocked, Open Library times out). For each uncertain book that carries
tropes/tags (i.e. can actually surface in recommendations), find its Wikipedia
article and use it to resolve, with high confidence:

  * fiction vs non-fiction  — from the article's CATEGORIES ("American novels"
    -> fiction; "Non-fiction books"/"Memoirs" -> non-fiction). Far more reliable
    than the overnight blurb heuristic, so here it is safe to also strip tropes
    from a Wikipedia-confirmed non-fiction book (backed up).
  * language                — only when the intro explicitly states a non-English
    original language ("is a Spanish-language novel"); then archive as non-English.
    Never archives on a guess (Google Books, the real language source, is down).
  * description             — backfilled into book_metadata (wikipedia) if missing.

Resumable: every lookup (hit or miss) is cached to verify_wiki_cache.json, so a
re-run never repeats a query. Polite (reuses _wiki_fetch's rate limiter/backoff).

  python _verify_wiki.py --cap 4000        # process up to N candidates
  python _verify_wiki.py --rollback verify_wiki_backup_<ts>.json
"""
import csv
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C
import _wiki_fetch as W

CACHE = "verify_wiki_cache.json"

FIC_CAT = re.compile(
    r"\bnovels?\b|short story collections|\bnovellas?\b|fantasy|science fiction|"
    r"children's (books|novels|literature)|young adult|picture books|"
    r"(?<!non-)(?<!non )\bfiction\b|"      # 'fiction' but NOT 'non-fiction'
    r"\bplays\b|poetry|comics|graphic novels|fairy tales|mystery fiction|"
    r"thriller|romance novels|horror fiction", re.I)
NF_CAT = re.compile(
    r"non-?fiction|biograph|\bmemoirs?\b|autobiograph|history books|\bessays?\b|"
    r"self-help|textbooks|reference works|cookbooks|travel books|popular science|"
    r"academic|guidebooks|\btreatises?\b|journalism", re.I)
LANG_INTRO = re.compile(
    r"is a[n]? (?:\d{4} )?(spanish|french|german|italian|portuguese|russian|"
    r"japanese|chinese|dutch|swedish|norwegian|danish|polish|czech|greek|arabic|"
    r"turkish|hebrew|hindi|korean|finnish|hungarian|romanian|catalan)[- ]"
    r"(?:language )?(?:novel|book|work|memoir|play|poem)", re.I)
EN_NOVEL = re.compile(r"is a[n]? (?:\d{4} |bestselling |debut )*"
                      r"(novel|thriller|mystery|fantasy|science fiction novel|"
                      r"children's|young adult|picture book|short story)", re.I)


def neutral_search(title):
    """Search without _wiki_fetch's '<title> novel' bias, which hides non-fiction
    books (memoirs, histories) and would leave them stuck uncertain."""
    d = W._get({"action": "query", "list": "search",
                "srsearch": title, "srlimit": 8})
    return [h["title"] for h in d.get("query", {}).get("search", [])]


def extract_and_categories(page):
    """One API call for BOTH the plain-text extract and the categories, instead
    of two. Halving the per-book request burst is what keeps Wikipedia from
    429-throttling us (the slow ~20s/book seen before was mostly backoff)."""
    d = W._get({"action": "query", "prop": "extracts|categories",
                "explaintext": 1, "cllimit": 60, "clshow": "!hidden",
                "redirects": 1, "titles": page})
    for _, p in d.get("query", {}).get("pages", {}).items():
        text = p.get("extract", "") or ""
        cats = [c["title"].replace("Category:", "") for c in p.get("categories", [])]
        return text, cats
    return "", []


def probe(title, author):
    """Return dict(page, cats, intro, class, lang_nonenglish) or None."""
    for page in neutral_search(title):
        if not W.title_ok(title, page):
            continue
        text, cats = extract_and_categories(page)
        if len(text) < 150 or W.is_disambig(page, text) or not W.author_ok(text, author):
            continue
        intro = " ".join(text.split())[:600]
        catblob = " || ".join(cats)
        fic = len(FIC_CAT.findall(catblob))
        nf = len(NF_CAT.findall(catblob))
        cls = None
        if fic and not nf:
            cls = "fiction"
        elif nf and not fic:
            cls = "nonfiction"
        elif EN_NOVEL.search(intro) and not nf:
            cls = "fiction"
        m = LANG_INTRO.search(intro)
        plot = W.plot_section(text)
        desc = plot[:1500] if len(plot) >= 200 else (intro[:1200] if len(intro) >= 200 else "")
        return {"page": page, "class": cls,
                "lang_nonenglish": m.group(1).lower() if m else None,
                "desc": desc}
    return None


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def candidates(conn):
    def ids(f):
        return [r["book_id"] for r in csv.DictReader(open(f, encoding="utf-8-sig"))] \
            if os.path.exists(f) else []
    cu, lu = ids("class_uncertain.csv"), ids("lang_uncertain.csv")
    order, seen = [], set()
    for group in (cu, lu):                       # class-uncertain first (higher value)
        for bid in group:
            if bid not in seen:
                seen.add(bid); order.append(bid)
    if not order:
        return []
    ph = ",".join("?" * len(order))
    keep = {r[0] for r in conn.execute(
        f"SELECT id FROM books WHERE id IN ({ph}) AND "
        f"((tropes NOT IN ('[]','')) OR (tags NOT IN ('[]',''))) AND "
        f"(status IS NULL OR status NOT LIKE 'archived%')", order)}
    return [b for b in order if b in keep]


def rollback(path):
    data = json.load(open(path, encoding="utf-8"))
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    for r in data:
        if "old_class" in r:
            conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?",
                         (r["old_class"], r["id"]))
        if "old_tropes" in r:
            conn.execute("UPDATE books SET tropes=? WHERE id=?", (r["old_tropes"], r["id"]))
        if "old_status" in r:
            conn.execute("UPDATE books SET status=? WHERE id=?", (r["old_status"], r["id"]))
    conn.commit(); conn.close()
    print(f"rolled back {len(data)} books from {path}")


def run(cap=4000):
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    cache = load_cache()
    order = candidates(conn)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[wiki] {len(order):,} candidates (uncertain + has tropes/tags); cap={cap}", flush=True)

    tally = Counter()
    backup = []
    backup_path = f"verify_wiki_backup_{ts}.json"
    done = 0
    for bid in order:
        if done >= cap:
            break
        b = conn.execute("SELECT id,title,author,tropes,status,"
                         "(SELECT book_class FROM enrichment_state WHERE book_id=books.id) bc "
                         "FROM books WHERE id=?", (bid,)).fetchone()
        if not b or not (b["author"] or "").strip():
            continue
        key = str(bid)
        if key in cache:
            res = cache[key]
        else:
            try:
                res = probe(b["title"] or "", b["author"] or "")
            except Exception:
                res = None
            cache[key] = res
            done += 1
            if done % 25 == 0:
                json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
                if backup:      # flush backup too, so rollback works if interrupted
                    json.dump(backup, open(backup_path, "w", encoding="utf-8"), ensure_ascii=False)
                conn.commit()
                print(f"  ...{done}/{cap} hits={tally['hit']} reclass={tally['reclass']} "
                      f"archived={tally['archived']} backfilled={tally['backfilled']}", flush=True)
        if not res:
            tally["miss"] += 1
            continue
        tally["hit"] += 1
        rec = {"id": bid}
        # language: archive only on an explicit non-English statement
        if res.get("lang_nonenglish") and not (b["status"] or "").startswith("archived"):
            rec["old_status"] = b["status"]
            conn.execute("UPDATE books SET status='archived_nonenglish' WHERE id=?", (bid,))
            tally["archived"] += 1
        # class from categories
        newcls = res.get("class")
        if newcls and newcls != b["bc"]:
            rec["old_class"] = b["bc"]
            conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?", (newcls, bid))
            tally["reclass"] += 1
            if newcls == "nonfiction" and b["tropes"] not in (None, "", "[]"):
                rec["old_tropes"] = b["tropes"]
                conn.execute("UPDATE books SET tropes='[]' WHERE id=?", (bid,))
                tally["stripped"] += 1
        # description backfill
        desc = (res.get("desc") or "").strip()
        if len(desc) > 40:
            has = conn.execute("SELECT 1 FROM book_metadata WHERE book_id=? AND "
                               "source IN ('ol_dump','wikipedia') AND description IS NOT NULL "
                               "AND TRIM(description)!=''", (bid,)).fetchone()
            if not has:
                conn.execute("INSERT OR REPLACE INTO book_metadata(book_id,source,description) "
                             "VALUES(?,?,?)", (bid, "wikipedia", desc))
                tally["backfilled"] += 1
        if len(rec) > 1:
            backup.append(rec)

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    if backup:
        json.dump(backup, open(backup_path, "w", encoding="utf-8"), ensure_ascii=False)
    conn.commit(); conn.close()
    print(f"[wiki] DONE looked_up={done} {dict(tally)} -> {backup_path}", flush=True)


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback(sys.argv[sys.argv.index("--rollback") + 1])
    else:
        cap = int(sys.argv[sys.argv.index("--cap") + 1]) if "--cap" in sys.argv else 4000
        run(cap=cap)
