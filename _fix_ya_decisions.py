"""Preserve YA as a real audience signal (user ruling).

`ya-fantasy` -> `fantasy` would have flattened YA fantasy into adult fantasy.
The active taxonomy already models the right shape: `young-adult` is a genre and
`ya-dystopian` is a subgenre under it. So YA-specific forms become subgenres,
and YA audience markers merge UP into `young-adult` rather than being dropped.

Also reverses my earlier drops of the juvenile/children audience markers: the
same principle (audience granularity matters) applies, and dropping 3,371 books'
audience signal is not my call to make. Those go back to blank for review.
"""
import csv
import glob

# YA-specific forms -> their own subgenre, mirroring ya-dystopian
ACTIVATE_SUBGENRE = {"ya-fantasy", "ya-romance", "ya-horror", "ya-mystery"}
# YA lead-age marker, consistent with the active tag `new-adult-18-24-lead`
ACTIVATE_TAG = {"young-adult-15-18-lead"}

# variants that must keep their YA-ness by merging into the YA form
MERGE = {
    "young-adult-fantasy": "ya-fantasy",
    "young-adult-romance": "ya-romance",
    "romance-young-adult": "ya-romance",
    # audience markers -> the YA genre (previously drop / flatten)
    "jeune-adulte": "young-adult",
    "fiction-young-adult": "young-adult",
    "teen": "young-adult",
    "teens": "young-adult",
    "teenagers": "young-adult",
}

# my earlier drops that removed audience signal -> hand back for review
UNSET = {"juvenile-fiction", "juvenile-nonfiction", "children-s-stories",
         "childrens-and-young-adult"}

changed = 0
for path in ["proposed_terms_review.csv"] + sorted(glob.glob("canon_*.csv")):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if not rows:
        continue
    n = 0
    for r in rows:
        t = r["term"]
        if t in ACTIVATE_SUBGENRE:
            r["decision"], r["kind"], n = "activate", "subgenre", n + 1
        elif t in ACTIVATE_TAG:
            r["decision"], r["kind"], n = "activate", "tag", n + 1
        elif t in MERGE:
            r["decision"], n = f"merge:{MERGE[t]}", n + 1
        elif t in UNSET and (r.get("decision") or "").strip():
            r["decision"], n = "", n + 1
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    if n:
        print(f"  {path:<34} adjusted {n}")
        if path == "proposed_terms_review.csv":
            changed = n

print(f"\nmaster: {changed} rows adjusted")
print(f"  {len(ACTIVATE_SUBGENRE)} YA subgenres activated (ya-fantasy/romance/horror/mystery)")
print(f"  {len(MERGE)} variants merged so YA survives")
print(f"  {len(UNSET)} juvenile/children drops reverted to blank for your call")
