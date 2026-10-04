"""Flag inline enrichments I have doubts about, for manual review.

Doubt signals: known=false / medium confidence, enriched from a wrong or junk
description or none at all (memory-only), a metadata problem in the record, or a
proposed_new term. Outputs doubts_review.csv most-doubtful first, with the
reason and the description snippet so each can be checked against the source.
"""
import csv
import json
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

JUNK_DESC = ("large print", "see https", "drama critics", "presents ",
             "winter garden", "directed by", "an evening with",
             "book review of", "companion website", "about the significance")


def assess(d, note, desc, author, year):
    reasons, score = [], 0
    if not d.get("known", True):
        reasons.append("known=false"); score += 2
    if d.get("confidence") == "medium":
        reasons.append("medium confidence"); score += 1
    if re.search(r"wrong match|junk|not grounded|contradict|may be wrong", note, re.I):
        reasons.append("bad/absent description — enriched anyway"); score += 3
    elif "from knowledge" in note.lower():
        reasons.append("from memory, not description"); score += 2
    if not desc:
        reasons.append("no description"); score += 1
    elif any(j in desc.lower() for j in JUNK_DESC):
        reasons.append("description is junk/wrong-book metadata"); score += 2
    if d.get("proposed_new"):
        reasons.append("proposed new term: " +
                       ", ".join(p.get("term", "") for p in d["proposed_new"])); score += 1
    if (author or "").count(",") >= 2:
        reasons.append("author field polluted"); score += 1
    if year and (year > 2025 or year < 1000):
        reasons.append(f"suspect year {year}"); score += 1
    return score, reasons


def main():
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT r.book_id, r.enriched_data, r.status,
                                  b.title, b.author, b.published_year, m.description
                           FROM enrichment_review r JOIN books b ON b.id=r.book_id
                           LEFT JOIN book_metadata m
                             ON m.book_id=r.book_id AND m.source='ol_dump'
                           WHERE r.model='inline-claude'""").fetchall()
    flagged = []
    for r in rows:
        d = json.loads(r["enriched_data"] or "{}")
        note = d.get("_note", "")
        desc = (r["description"] or "").strip()
        score, reasons = assess(d, note, desc, r["author"], r["published_year"])
        if reasons:
            flagged.append((score, r, d, note, desc, reasons))
    flagged.sort(key=lambda x: -x[0])

    with open("doubts_review.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["doubt_score", "decision", "book_id", "title", "author",
                    "confidence", "known", "status", "TROPES", "TAGS",
                    "why_flagged", "my_note", "description_snippet"])
        for score, r, d, note, desc, reasons in flagged:
            w.writerow([score, "", r["book_id"], r["title"], r["author"],
                        d.get("confidence"), "yes" if d.get("known", True) else "NO",
                        r["status"], ", ".join(d.get("tropes") or []),
                        ", ".join(d.get("tags") or []), " | ".join(reasons),
                        note, desc[:220]])

    print(f"flagged {len(flagged)} of {len(rows)} enrichments -> doubts_review.csv\n")
    print("=== most doubtful (score >= 3) ===")
    for score, r, d, note, desc, reasons in flagged:
        if score < 3:
            break
        print(f"  [{score}] {r['title'][:40]:<40} {' | '.join(reasons)[:70]}")


if __name__ == "__main__":
    main()
