"""Export pending enrichment_review rows to a CSV for human review.

  python export_review.py                 # all pending rows
  python export_review.py --model inline-claude
  python export_review.py --out foo.csv

The CSV carries before -> after side by side plus a `decision` column you can
edit (approve / reject / edit). `enrich promote --decisions <csv>` will honour it.
"""
import csv
import json
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

args = sys.argv[1:]
model = args[args.index("--model") + 1] if "--model" in args else None
out = args[args.index("--out") + 1] if "--out" in args else "enrichment_review.csv"
status = args[args.index("--status") + 1] if "--status" in args else "pending"
# --batch inline_batch_NNN.json : restrict to just that batch's book ids
batch_ids = None
if "--batch" in args:
    bf = args[args.index("--batch") + 1]
    batch_ids = [b["id"] for b in json.load(open(bf, encoding="utf-8")) if b.get("id")]

conn = sqlite3.connect(C.DB_PATH)
conn.row_factory = sqlite3.Row
q = """SELECT r.book_id, r.enriched_data, r.confidence, r.model, r.before_image,
              r.status, r.promote_run,
              b.title, b.author, b.genres, b.pacing, b.spice_level, b.focus,
              m.description
       FROM enrichment_review r
       JOIN books b ON b.id = r.book_id
       LEFT JOIN book_metadata m ON m.book_id = r.book_id AND m.source='ol_dump'
       WHERE r.status = ?"""
params = [status]
if model:
    q += " AND r.model = ?"
    params.append(model)
if batch_ids:
    q += f" AND r.book_id IN ({','.join('?' * len(batch_ids))})"
    params.extend(batch_ids)
q += " ORDER BY r.model, b.title"
rows = conn.execute(q, params).fetchall()

def j(x, k):
    try:
        return ", ".join(json.loads(x or "[]") if k is None else (json.loads(x or "{}").get(k) or []))
    except Exception:
        return ""

with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["decision", "status", "promote_run",
                "book_id", "title", "author", "model", "confidence",
                "known", "book_class",
                "genres_before", "tropes_before", "tags_before",
                "TROPES_new", "TAGS_new", "pacing_new", "focus_new", "spice_new",
                "content_warnings_new", "proposed_new",
                "grounded_on_description", "description_snippet"])
    n = 0
    for r in rows:
        d = json.loads(r["enriched_data"] or "{}")
        before = json.loads(r["before_image"] or "{}")
        desc = (r["description"] or "").replace("\n", " ").strip()
        w.writerow([
            "", r["status"], r["promote_run"] or "",
            r["book_id"], r["title"], r["author"], r["model"], r["confidence"],
            "yes" if d.get("known", True) else "NO",
            d.get("book_class", ""),
            ", ".join(json.loads(r["genres"] or "[]")),
            ", ".join(json.loads(before.get("tropes") or "[]")),
            ", ".join(json.loads(before.get("tags") or "[]")),
            ", ".join(d.get("tropes") or []),
            ", ".join(d.get("tags") or []),
            d.get("pacing") or "", d.get("focus") or "", d.get("spice_level") or "",
            ", ".join(d.get("content_warnings") or []),
            "; ".join(p.get("term", "") for p in (d.get("proposed_new") or [])),
            "yes" if desc else "no",
            desc[:300],
        ])
        n += 1
print(f"wrote {out} ({n} rows)")
print("Edit the `decision` column: approve | reject | (blank = undecided)")
conn.close()
