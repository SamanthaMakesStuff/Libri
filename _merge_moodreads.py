"""Scoped, additive merge of MoodReads catalog data into book_rec.db.

This is the SAFE alternative to `sync_db.py --refresh` (which blanket-overwrites
all 96k rows from the legacy catalog and reverts Phase 1 + every promotion).

Rules:
  * Only touches books whose catalog entry has verifiedSource contains MoodReads.
  * UNION-ONLY: never removes or overwrites an existing trope/tag/warning.
  * Every incoming term is normalised to a CANONICAL ACTIVE taxonomy slug via
    slugify() + the alias table. Terms that don't map are NEVER injected raw —
    they are parked in `taxonomy` as status='proposed', source='moodreads' for
    Phase 6 to decide. This preserves "0 raw non-slug terms".
  * Routing follows the vocab-apply philosophy: a term whose canonical kind is
    'trope' lands in tropes, everything else lands in tags — regardless of which
    catalog list it came from.
  * content_warnings are free text in this DB (mixed case), so they are merged
    with CASE-INSENSITIVE dedup: existing spelling wins, only genuinely new
    warnings are appended.
  * spice_level is filled ONLY when the DB value is NULL/''/'N/A' — community
    spice (e.g. The Lesbian Review) is never overwritten.

Usage:  python _merge_moodreads.py --dry-run
        python _merge_moodreads.py
Reversal: python _merge_moodreads.py --rollback <backup_file.json>
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C
from enrich_taxonomy import slugify, normalize_raw

DRY = "--dry-run" in sys.argv
NA_SPICE = (None, "", "N/A")


def rollback(path):
    data = json.loads(open(path, encoding="utf-8").read())
    conn = sqlite3.connect(C.DB_PATH, timeout=30)
    for b in data["books"]:
        conn.execute("""UPDATE books SET tropes=?, tags=?, content_warnings=?,
                          spice_level=? WHERE id=?""",
                     (b["tropes"], b["tags"], b["content_warnings"],
                      b["spice_level"], b["id"]))
    conn.commit()
    print(f"rolled back {len(data['books'])} books from {path}")
    conn.close()


if "--rollback" in sys.argv:
    rollback(sys.argv[sys.argv.index("--rollback") + 1])
    sys.exit()

conn = sqlite3.connect(C.DB_PATH, timeout=30)
conn.row_factory = sqlite3.Row
active = {r["slug"]: r["kind"] for r in
          conn.execute("SELECT slug, kind FROM taxonomy WHERE status='active'")}
alias = {r["alias"]: r["slug"] for r in
         conn.execute("SELECT alias, slug FROM taxonomy_alias")}


def canon(term):
    """raw MoodReads term -> canonical ACTIVE slug, or None."""
    s = slugify(term)
    if s in active:
        return s
    a = alias.get(normalize_raw(term)) or alias.get(s)
    if a and a in active:
        return a
    return None


# reviewed content-warning normalisation (raw catalog spelling -> canonical).
# Applied on ingest so a re-run can't resurrect the variants we consolidated.
try:
    _cw = json.loads((C.ROOT / "moodreads_cw_normalise.json").read_text(encoding="utf-8"))
    CW_MAP, CW_DROP = _cw.get("merge", {}), set(_cw.get("drop", []))
except FileNotFoundError:
    CW_MAP, CW_DROP = {}, set()

catalog = [b for b in json.load(open("bookCatalog.json", encoding="utf-8"))
           if "MoodReads" in (b.get("verifiedSource") or "")]

stats = Counter()
unmapped = Counter()
backup = []
now = datetime.now().strftime("%Y%m%d_%H%M%S")

for b in catalog:
    bid = b.get("id")
    row = conn.execute("""SELECT tropes, tags, content_warnings, spice_level
                          FROM books WHERE id=?""", (bid,)).fetchone()
    if row is None:
        stats["not_in_db"] += 1
        continue

    cur_tropes = json.loads(row["tropes"] or "[]")
    cur_tags = json.loads(row["tags"] or "[]")
    cur_cw = json.loads(row["content_warnings"] or "[]")

    add_tropes, add_tags = [], []
    for field in ("tropes", "tags"):
        for term in (b.get(field) or []):
            s = canon(term)
            if not s:
                unmapped[str(term)] += 1
                continue
            target = add_tropes if active.get(s) == "trope" else add_tags
            if s not in target:
                target.append(s)

    new_tropes = cur_tropes + [s for s in add_tropes if s not in cur_tropes]
    new_tags = cur_tags + [s for s in add_tags if s not in cur_tags]

    # content warnings: normalise through the reviewed map FIRST (otherwise the
    # raw catalog spellings get re-injected on every run and undo the tidy-up),
    # then case-insensitive dedup with the existing spelling winning.
    seen_cw = {str(x).strip().lower() for x in cur_cw}
    new_cw = list(cur_cw)
    for w in (b.get("contentWarnings") or []):
        k = str(w).strip().lower()
        if k in CW_DROP:
            continue
        if k in CW_MAP:
            w = CW_MAP[k]
            k = w.strip().lower()
        if k and k not in seen_cw:
            new_cw.append(str(w).strip())
            seen_cw.add(k)

    new_spice = row["spice_level"]
    if row["spice_level"] in NA_SPICE and b.get("spiceLevel"):
        new_spice = b["spiceLevel"]
        stats["spice_filled"] += 1

    changed = (len(new_tropes) != len(cur_tropes) or len(new_tags) != len(cur_tags)
               or len(new_cw) != len(cur_cw) or new_spice != row["spice_level"])
    if not changed:
        stats["unchanged"] += 1
        continue

    stats["books_changed"] += 1
    stats["tropes_added"] += len(new_tropes) - len(cur_tropes)
    stats["tags_added"] += len(new_tags) - len(cur_tags)
    stats["warnings_added"] += len(new_cw) - len(cur_cw)

    backup.append({"id": bid, "tropes": row["tropes"], "tags": row["tags"],
                   "content_warnings": row["content_warnings"],
                   "spice_level": row["spice_level"]})
    if not DRY:
        conn.execute("""UPDATE books SET tropes=?, tags=?, content_warnings=?,
                          spice_level=? WHERE id=?""",
                     (json.dumps(new_tropes, ensure_ascii=False),
                      json.dumps(new_tags, ensure_ascii=False),
                      json.dumps(new_cw, ensure_ascii=False), new_spice, bid))

# park unmapped vocabulary for Phase 6 rather than dropping it
if not DRY:
    for term, n in unmapped.items():
        # applies_to is NOT NULL - omitting it made every INSERT OR IGNORE fail
        # silently, because OR IGNORE swallows constraint violations too.
        conn.execute("""INSERT OR IGNORE INTO taxonomy
                          (slug, display, kind, applies_to, status, source, created_at)
                        VALUES (?,?,?, 'both','proposed','moodreads',?)""",
                     (slugify(term), str(term), "tag",
                      datetime.now().isoformat(timespec="seconds")))
    bpath = C.ROOT / f"moodreads_merge_backup_{now}.json"
    bpath.write_text(json.dumps({"run": now, "books": backup},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    conn.commit()

print(f"{'DRY RUN - ' if DRY else ''}MoodReads scoped merge over {len(catalog)} catalog entries")
for k, v in stats.most_common():
    print(f"  {k:<18} {v:>6,}")
print(f"\n  distinct terms parked as 'proposed' (unmapped): {len(unmapped):,}"
      f"  ({sum(unmapped.values()):,} occurrences)")
print("  examples:", ", ".join(t for t, _ in unmapped.most_common(10)))
if not DRY:
    print(f"\n  backup -> moodreads_merge_backup_{now}.json")
    print(f"  rollback with: python _merge_moodreads.py --rollback moodreads_merge_backup_{now}.json")
conn.close()
