"""Phase 2 (overnight): determine fiction vs non-fiction per book and mark
enrichment_state.book_class. Conservative — only confident calls are written;
everything else goes to class_uncertain.csv for the step-4 external check.

Per the user's choices:
  * a confident call OVERRIDES the existing triage class when they conflict
    (novels mis-shelved as non-fiction get flipped back);
  * a book confirmed NON-fiction has its tropes stripped (they don't belong);
    a book reclassified TO fiction keeps its tropes.

All prior book_class values and all stripped tropes are backed up first;
--rollback restores both.

  python _class_mark.py [--dry]
  python _class_mark.py --rollback class_mark_backup_<ts>.json
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C

FIC_STRONG = re.compile(
    r"\bnovels?\b|\bnovella\b|\bnovelist\b|\bwork of fiction\b|\bpicture book\b|"
    r"\bshort stor(y|ies)\b|\ba (fairy )?tale of\b|\bpicture[- ]book\b", re.I)
FIC = re.compile(
    r"\ba (thrilling|gripping|sweeping|heartwarming|haunting|charming|poignant) "
    r"(tale|story|saga|debut|read)\b|\ba story of\b|\bfairy tale\b|"
    r"\bfantasy (adventure|world|epic)\b|\bwhen (a|an|the|her|his|young|she|he)\b"
    r".{0,40}\b(must|discovers?|finds?|meets?|falls?|realizes?|sets? (out|off)|"
    r"embarks?)\b|\bmust (save|find|stop|escape|choose|protect|fight|survive|"
    r"uncover|defeat)\b|\b(magical|enchanted|mythical) (world|kingdom|land|realm)\b|"
    r"\bcoming[- ]of[- ]age (story|tale|novel)\b", re.I)
NF = re.compile(
    r"\bthis (book|volume|study|biography|memoir|guide|history|work|collection) \b|"
    r"\ba (history|biography|memoir|study|guide|celebration|portrait|survey|"
    r"chronicle) of\b|\bthe (history|biography|life|making|science) of\b|"
    r"\btrue story\b|\breal[- ]life\b|\bnonfiction\b|\bnon-fiction\b|\bhow to\b|"
    r"\bguide to\b|\bhandbook\b|\bintroduction to\b|\bexamin(e|es|ing) (the|how|"
    r"various)\b|\bexplores? (the|how|why)\b|\bargues that\b|"
    r"\bdraws? on\b|\bfully illustrated\b|\bphotographs?\b|\brecipes?\b|\bessays\b|"
    r"\bchapters\b|\bscholar|\bacademic\b|\banthology\b|\bmemoir\b|"
    r"\baccount of\b|\bresearch\b|\btextbook\b|\bdigitized by\b|\bannotated\b|"
    r"\btranslation\b|\bgeography of\b|\bbiograph|\bautobiograph|\breport(s)? (the|on|that)\b|"
    r"\banalyzes?\b|\binvestigat(es|ion)\b|\bnarrative history\b|\bself[- ]help\b|"
    r"\bthe (definitive|inside|untold|secret|true) (history|story|account)\b", re.I)

FICTION_GENRES = {"romance", "Romantasy", "Mystery", "crime", "Thriller",
                  "General Fiction", "romantic suspense", "Adventure",
                  "Young Adult", "Fantasy", "Sci-Fi", "Science Fiction",
                  "Horror", "Historical Fiction", "Literary Fiction"}
NONFIC_GENRES = {"History", "Biography & Memoir", "Psychology",
                 "Business & Economics", "Health & Fitness", "Politics", "Art",
                 "Science & Nature", "Cooking", "Religion & Spirituality",
                 "Philosophy", "Music", "Travel", "Self-Help"}


def classify(title, desc, genres):
    """Return 'fiction' | 'nonfiction' | None(uncertain).

    Decisive on explicit textual signals (an explicit 'novel' outweighs a noisy
    catalogue genre; multiple non-fiction markers outweigh a lone narrative
    hint); everything genuinely mixed stays uncertain for step 4.
    """
    txt = f"{title}. {desc or ''}"
    fs = len(FIC_STRONG.findall(txt))       # explicit 'novel', 'short stories'…
    fh = len(FIC.findall(txt))              # narrative hints
    nf = len(NF.findall(txt))               # expository / scholarly markers
    gset = set(genres)
    fic_g = bool(gset & FICTION_GENRES)
    nf_g = bool(gset & NONFIC_GENRES) and not fic_g

    # explicit, near-unambiguous cases first
    if fs >= 1 and nf == 0:
        return "fiction"
    if nf >= 2 and fs == 0 and fh == 0:
        return "nonfiction"
    # otherwise combine with genre and require a clear margin
    fic_score = 2 * fs + fh + (1 if fic_g else 0)
    nf_score = nf + (1 if nf_g else 0)
    if fic_score - nf_score >= 2:
        return "fiction"
    if nf_score - fic_score >= 2:
        return "nonfiction"
    return None


def rollback(path):
    data = json.load(open(path, encoding="utf-8"))
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    for r in data:
        conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?",
                     (r["old_class"], r["id"]))
        if "old_tropes" in r:
            conn.execute("UPDATE books SET tropes=? WHERE id=?",
                         (r["old_tropes"], r["id"]))
    conn.commit()
    conn.close()
    print(f"restored class/tropes on {len(data)} books from {path}")


def run(dry=False, chunk=3000):
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    # skip books already archived as non-English
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM books WHERE status IS NULL OR status NOT LIKE 'archived%'")]
    total = len(ids)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[class] scanning {total:,} books (dry={dry})", flush=True)

    tally = Counter()
    changes, strip_backup, uncertain = [], [], []
    for i in range(0, total, chunk):
        batch = ids[i:i + chunk]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""SELECT b.id,b.title,b.genres,b.tropes,es.book_class,
                    COALESCE(w.description,o.description) AS descr
                FROM books b
                JOIN enrichment_state es ON es.book_id=b.id
                LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
                LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
                WHERE b.id IN ({ph})""", batch).fetchall()
        for r in rows:
            genres = json.loads(r["genres"] or "[]")
            call = classify(r["title"], r["descr"], genres)
            if call is None:
                tally["uncertain"] += 1
                # only log if the current class is missing/ambiguous or conflicts weakly
                if r["book_class"] in (None, "ambiguous"):
                    uncertain.append({"book_id": r["id"], "title": r["title"] or "",
                                      "genres": r["genres"] or "[]",
                                      "current_class": r["book_class"] or ""})
                continue
            cur = r["book_class"]
            has_tropes = r["tropes"] not in (None, "", "[]")
            rec = {"id": r["id"], "old_class": cur, "new_class": call}
            changed = (cur != call)
            # strip tropes when CONFIRMED nonfiction (whether newly or already)
            if call == "nonfiction" and has_tropes:
                rec["old_tropes"] = r["tropes"]
                strip_backup.append(rec)
            if changed:
                tally[f"{cur}->{call}"] += 1
                changes.append(rec)
            else:
                tally["unchanged"] += 1
                if "old_tropes" in rec and rec not in changes:
                    changes.append(rec)   # need to record for trope strip even if class same
        print(f"  ...{min(i+chunk,total):,}/{total:,}", flush=True)

    with open("class_uncertain.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["book_id", "title", "genres", "current_class"])
        w.writeheader()
        w.writerows(uncertain)

    if not dry and (changes or strip_backup):
        backup = f"class_mark_backup_{ts}.json"
        allrecs = {r["id"]: r for r in changes}
        for r in strip_backup:
            allrecs.setdefault(r["id"], r).update(r)
        recs = list(allrecs.values())
        json.dump(recs, open(backup, "w", encoding="utf-8"), ensure_ascii=False)
        for r in recs:
            if r.get("old_class") != r["new_class"]:
                conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?",
                             (r["new_class"], r["id"]))
            if "old_tropes" in r:
                conn.execute("UPDATE books SET tropes='[]' WHERE id=?", (r["id"],))
        conn.commit()
        print(f"[class] class changes={len(changes):,} trope-strips={len(strip_backup):,} "
              f"-> backup {backup}")
    conn.close()
    print(f"[class] DONE {dict(tally)} uncertain-logged={len(uncertain):,} "
          f"-> class_uncertain.csv", flush=True)
    return tally


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        rollback(sys.argv[sys.argv.index("--rollback") + 1])
    else:
        run(dry="--dry" in sys.argv)
