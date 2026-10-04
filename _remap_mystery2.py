"""Rewrite trope_review_mystery_2.csv so it only contains valid trope slugs.

The CSV was produced by the OLD _trope_match_mystery.py, which emitted four
subgenre slugs into the trope column. Remap the two with a clean trope
equivalent and drop the two without one; also split the spy rows out to a
`spies` tag review so that signal isn't lost.

  legal-thriller        -> court-case-as-backbone-of-plot   (trope, keep)
  locked-room-mystery   -> closed-circle-of-suspects        (trope, keep)
  spy-espionage-thriller-> spies                            (moved to tag CSV)
  heist                 -> dropped (no accurate trope)
"""
import csv
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC = "trope_review_mystery_2.csv"

REMAP = {"legal-thriller": "court-case-as-backbone-of-plot",
         "locked-room-mystery": "closed-circle-of-suspects"}
TO_TAG = {"spy-espionage-thriller": "spies"}
DROP = {"heist"}

rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
trope_rows, tag_rows = [], []
stats = {"kept": 0, "remapped": 0, "to_tag": 0, "dropped": 0}
for r in rows:
    t = r["trope"]
    if t in DROP:
        stats["dropped"] += 1
        continue
    if t in TO_TAG:
        stats["to_tag"] += 1
        tag_rows.append({"decision(keep/blank)": r.get("decision(keep/blank)", ""),
                         "tier": r["tier"], "tag": TO_TAG[t],
                         "matched_phrase": r["matched_phrase"], "book_id": r["book_id"],
                         "title": r["title"], "author": r.get("author", ""),
                         "context": r["context"]})
        continue
    if t in REMAP:
        r["trope"] = REMAP[t]
        stats["remapped"] += 1
    else:
        stats["kept"] += 1
    trope_rows.append(r)

with open(SRC, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(trope_rows[0].keys()))
    w.writeheader()
    w.writerows(trope_rows)

if tag_rows:
    with open("tag_review_mystery2_spies.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(tag_rows[0].keys()))
        w.writeheader()
        w.writerows(tag_rows)

print(f"trope rows: {len(trope_rows)}  {stats}")
print(f"spy rows moved to tag_review_mystery2_spies.csv: {len(tag_rows)}")
