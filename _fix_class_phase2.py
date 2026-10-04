"""Correct the overnight phase-2 class pass, which was too aggressive in the
fiction->non-fiction direction (~33% of trope-strips hit real novels).

  * restore EVERY stripped trope (undo all data loss);
  * revert EVERY ->non-fiction class change (the error-prone, strip-triggering
    direction) back to its original class;
  * KEEP the ->fiction changes (rescuing novels mis-shelved as non-fiction — a
    safe direction that deletes nothing).

Reads the phase-2 backup. Idempotent.
"""
import glob
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

bk = sorted(glob.glob("class_mark_backup_*.json"))[-1]
recs = json.load(open(bk, encoding="utf-8"))
conn = sqlite3.connect(C.DB_PATH, timeout=600)
stats = Counter()
for r in recs:
    if "old_tropes" in r:
        conn.execute("UPDATE books SET tropes=? WHERE id=?", (r["old_tropes"], r["id"]))
        stats["tropes_restored"] += 1
    if r["new_class"] == "nonfiction" and r.get("old_class") and r["old_class"] != "nonfiction":
        conn.execute("UPDATE enrichment_state SET book_class=? WHERE book_id=?",
                     (r["old_class"], r["id"]))
        stats["nonfiction_flip_reverted"] += 1
    elif r["new_class"] == "fiction" and r.get("old_class") != "fiction":
        stats["fiction_rescue_kept"] += 1
conn.commit()
conn.close()
print(f"from {bk}: {dict(stats)}")
