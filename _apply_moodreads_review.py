"""Apply the reviewed MoodReads vocabulary.

The decisions need THREE different execution paths, because the terms live in
three different places:

  1. tags/tropes (69)  -> taxonomy status changes, written to a CSV for
                          `enrich canonicalise --apply`. These terms are NOT on
                          any book yet (the scoped merge dropped them as
                          unmapped), so the merge must be re-run afterwards to
                          actually pull them onto books.
  2. contentWarnings   -> books.content_warnings is FREE TEXT, not taxonomy-
     (150)                gated, so canonicalise would silently do nothing.
                          Consolidated here directly, case-insensitively.
  3. SPICE (8)         -> not a vocabulary decision at all: these encode the
                          spice scale, so they set books.spice_level and the
                          term is discarded. Read from bookCatalog.json because
                          they never made it into the DB.

Fixes two malformed rows:
  death-of-a-child -> 'merge:' with no target  -> treated as accept (it is a
                      real warning, distinct from death-of-a-parent)
  substance-abuse  -> 'merge:drug-us'          -> typo for drug-use
"""
import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

DRY = "--dry-run" in sys.argv
SRC = "moodreads_terms_review.csv"

# MoodReads uses a 1-5 spice scale; the catalog's canonical scale is
# No Spice / Tame / Medium Spice / Explicit. Highest signal on a book wins.
SPICE_MAP = {
    "spice-2": "Tame",
    "spice-3": "Medium Spice",
    "spice-4": "Explicit",
    "spice-level-4": "Explicit",
    "high-heat": "Explicit",
    "very-explicit": "Explicit",
    "open-door-spice": "Medium Spice",       # on-page, but intensity unstated
    "explicit-sexual-content": "Explicit",
}
RANK = {"No Spice": 0, "Tame": 1, "Medium Spice": 2, "Explicit": 3}
FILLABLE = (None, "", "N/A")

RETARGET = {"drug-us": "drug-use"}           # typo
FORCE_ACCEPT = {"death-of-a-child"}          # 'merge:' with an empty target

rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
conn = sqlite3.connect(C.DB_PATH, timeout=180)
conn.row_factory = sqlite3.Row

# ---------------------------------------------------------------- classify
canon_rows, cw_merge, cw_drop, spice_terms = [], {}, set(), {}
for r in rows:
    d = (r.get("decision") or "").strip()
    term, raw, field = r["term"], r["raw_term"], r["from_field"]
    low = d.lower()
    if low == "spice":
        spice_terms[raw.strip().lower()] = SPICE_MAP.get(term)
        continue
    if term in FORCE_ACCEPT:
        low, d = "accept", "accept"
    if field == "contentWarnings":
        if low.startswith("merge"):
            t = d.split(":", 1)[1].strip() if ":" in d else ""
            t = RETARGET.get(t, t)
            if t:
                cw_merge[raw.strip().lower()] = t.replace("-", " ")
        elif low == "reject":
            cw_drop.add(raw.strip().lower())
        # accept -> leave the warning exactly as it is
    else:
        if low == "accept":
            canon_rows.append({"decision": "activate", "term": term,
                               "kind": "tag", "genre_bucket": "", "applies_to": ""})
        elif low == "reject":
            canon_rows.append({"decision": "drop", "term": term, "kind": "tag",
                               "genre_bucket": "", "applies_to": ""})
        elif low.startswith("merge"):
            t = d.split(":", 1)[1].strip() if ":" in d else ""
            t = RETARGET.get(t, t)
            if t:
                canon_rows.append({"decision": f"merge:{t}", "term": term,
                                   "kind": "tag", "genre_bucket": "", "applies_to": ""})

with open("moodreads_canon_apply.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket", "applies_to"])
    w.writeheader()
    w.writerows(canon_rows)

# ---------------------------------------------------------------- 3. SPICE
catalog = {b["id"]: b for b in json.load(open("bookCatalog.json", encoding="utf-8"))
           if b.get("id")}
want = {}
for bid, b in catalog.items():
    best = None
    for f in ("tags", "tropes", "contentWarnings"):
        for t in (b.get(f) or []):
            lvl = spice_terms.get(str(t).strip().lower())
            if lvl and (best is None or RANK[lvl] > RANK[best]):
                best = lvl
    if best:
        want[bid] = best

stats = Counter()
backup = []
for bid, lvl in want.items():
    cur = conn.execute("SELECT spice_level FROM books WHERE id=?", (bid,)).fetchone()
    if cur is None:
        stats["book_not_in_db"] += 1
        continue
    if cur["spice_level"] in FILLABLE:
        stats["spice_filled"] += 1
        backup.append({"id": bid, "spice_level": cur["spice_level"]})
        if not DRY:
            conn.execute("UPDATE books SET spice_level=? WHERE id=?", (lvl, bid))
    else:
        stats["spice_kept_existing"] += 1     # never overwrite community spice

# ---------------------------------------------------------------- 2. warnings
cw_backup = []
for r in conn.execute("SELECT id, content_warnings FROM books "
                      "WHERE content_warnings IS NOT NULL AND content_warnings NOT IN ('','[]')"):
    try:
        cw = json.loads(r["content_warnings"])
    except Exception:
        continue
    out, seen, changed = [], set(), False
    for wv in cw:
        k = str(wv).strip().lower()
        if k in cw_drop:
            changed = True
            stats["cw_dropped"] += 1
            continue
        if k in cw_merge:
            wv = cw_merge[k]
            changed = True
            stats["cw_merged"] += 1
        kk = str(wv).strip().lower()
        if kk in seen:
            changed = True
            stats["cw_dedup"] += 1
            continue
        seen.add(kk)
        out.append(wv)
    if changed:
        stats["cw_books_changed"] += 1
        cw_backup.append({"id": r["id"], "content_warnings": r["content_warnings"]})
        if not DRY:
            conn.execute("UPDATE books SET content_warnings=? WHERE id=?",
                         (json.dumps(out, ensure_ascii=False), r["id"]))

if not DRY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (C.ROOT / f"moodreads_review_backup_{ts}.json").write_text(
        json.dumps({"spice": backup, "content_warnings": cw_backup},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    conn.commit()
    print(f"backup -> moodreads_review_backup_{ts}.json")

print(f"\n{'DRY RUN - ' if DRY else ''}moodreads review applied")
print(f"  taxonomy rows written to moodreads_canon_apply.csv: {len(canon_rows)}")
print(f"  spice terms recognised: {len(spice_terms)}  -> books wanting spice: {len(want)}")
for k, v in stats.most_common():
    print(f"  {k:<22} {v:>6,}")
print(f"  cw merge rules: {len(cw_merge)} | cw drop rules: {len(cw_drop)}")
conn.close()
