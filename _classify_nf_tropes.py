"""Classify the 532 nonfiction-classed books that carry tropes as genuinely
non-fiction (-> strip tropes) vs actually fiction (-> reclassify to fiction,
keep tropes). Writes a review CSV with the call + the signals behind it, so the
decisions can be audited before anything is written. Read-only."""
import csv
import json
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

# Expository / nonfiction fingerprints (title or description).
NF = re.compile(
    r"\bthis (book|volume|study|biography|memoir|guide|history|work|collection)\b|"
    r"\ba (history|biography|memoir|study|guide|celebration|portrait|survey|"
    r"chronicle|history) of\b|\bthe (history|biography|life|making|science|art|"
    r"story) of\b|\btrue story\b|\breal[- ]life\b|\bnonfiction\b|\bnon-fiction\b|"
    r"\bhow to\b|\bguide to\b|\bhandbook\b|\bintroduction to\b|\bexamines?\b|"
    r"\bexplores? (the|how|why)\b|\bargues that\b|\bthe author\b|\bdraws? on\b|"
    r"\bfully illustrated\b|\bphotographs?\b|\brecipes?\b|\bessays\b|"
    r"\bchapters\b|\bscholar|\bacademic\b|\breaders?\b|\banthology\b|"
    r"\bfirst published in \d{4}\b|\bmemoir\b|\breal(-| )world\b|"
    r"\bpractical (guide|advice|tips)\b|\bstep[- ]by[- ]step\b|\bself[- ]help\b|"
    r"\blessons (from|in|of)\b|\bwhat we can learn\b|\bcase stud|"
    r"\baccount of\b|\bthe true story\b|\bresearch\b|\btextbook\b|\bdigitized by\b|"
    r"\bannotated\b|\btranslation\b|\bgeography of\b|\bbiograph|\bautobiograph|"
    r"\bthis (revelatory|definitive|comprehensive|groundbreaking) (book|history|study|account)\b|"
    r"\breport(s)? (the|on|that)\b|\banalyzes?\b|\binvestigat(es|ion)\b|\bnarrative history\b|"
    r"\bthe (definitive|inside|untold|secret|true) (history|story|account)\b",
    re.I)
# Narrative / fiction fingerprints. \bnovel\b is the single strongest tell.
FIC_STRONG = re.compile(
    r"\bnovels?\b|\bnovella\b|\bnovelist\b|\bwork of fiction\b|\bpicture book\b|"
    r"\bshort stor(y|ies)\b|\ba (fairy )?tale of\b", re.I)
FIC = re.compile(
    r"\ba (thrilling|gripping|sweeping|heartwarming|haunting) (tale|story|saga|debut)\b|"
    r"\ba story of\b|\bfairy tale\b|\bfantasy (adventure|world|epic)\b|"
    r"\bwhen (a|an|the|her|his|young|she|he)\b.{0,40}\b(must|discovers?|finds?|meets?|"
    r"falls?|realizes?|sets? (out|off)|embarks?)\b|\bmust (save|find|stop|escape|"
    r"choose|protect|fight|survive|uncover|defeat)\b|\b(magical|enchanted|mythical) "
    r"(world|kingdom|land|realm)\b|\bcoming[- ]of[- ]age (story|tale)\b",
    re.I)
FICTION_GENRES = {"romance", "Romantasy", "Mystery", "crime", "Thriller",
                  "General Fiction", "romantic suspense", "Adventure",
                  "Young Adult", "Fantasy", "Sci-Fi", "Science Fiction",
                  "Horror", "Historical Fiction", "Literary Fiction"}

conn = sqlite3.connect(C.DB_PATH, timeout=600)
conn.row_factory = sqlite3.Row
rows = conn.execute("""SELECT b.id,b.title,b.author,b.genres,b.tropes,
     COALESCE(w.description,o.description) AS descr
   FROM books b JOIN enrichment_state s ON s.book_id=b.id
   LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
   LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
   WHERE s.book_class='nonfiction' AND b.tropes NOT IN ('[]','')
     AND b.tropes IS NOT NULL""").fetchall()
conn.close()

out, tally = [], {"fiction": 0, "nonfiction": 0, "uncertain": 0}
for r in rows:
    txt = f"{r['title']}. {r['descr'] or ''}"
    genres = json.loads(r["genres"] or "[]")
    fic_strong = len(FIC_STRONG.findall(txt))
    fic_hits = len(FIC.findall(txt))
    nf_hits = len(NF.findall(txt))
    fic_genre = bool(set(genres) & FICTION_GENRES)
    score = 2 * fic_strong + fic_hits + (1 if fic_genre else 0) - nf_hits
    if score >= 1:
        call = "fiction"
    elif score <= -1:
        call = "nonfiction"
    else:
        call = "uncertain"
    tally[call] += 1
    signals = f"ficS={fic_strong} fic={fic_hits} nf={nf_hits} ficGenre={fic_genre}"
    out.append({"call": call, "signals": signals, "book_id": r["id"],
                "title": r["title"], "author": r["author"] or "",
                "genres": ",".join(genres), "tropes": r["tropes"],
                "has_desc": bool((r["descr"] or "").strip()),
                "desc": " ".join((r["descr"] or "")[:300].split())})

out.sort(key=lambda x: (x["call"], x["title"]))
with open("nf_trope_review.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(out)
print("classification tally:", tally)
print(f"-> nf_trope_review.csv ({len(out)} books)")
