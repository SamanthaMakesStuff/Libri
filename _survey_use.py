"""Read-only: full trope usage counts, plus active slugs never used. Reference
for choosing which slug a pattern should target."""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

conn = sqlite3.connect(C.DB_PATH, timeout=600)
use = Counter()
for (t,) in conn.execute("SELECT tropes FROM books WHERE tropes IS NOT NULL AND tropes!='[]'"):
    try:
        for s in json.loads(t):
            use[s] += 1
    except Exception:
        pass
active = [r[0] for r in conn.execute(
    "SELECT slug FROM taxonomy WHERE kind='trope' AND status='active' ORDER BY slug")]
conn.close()

with open("logs/trope_usage.txt", "w", encoding="utf-8") as f:
    f.write("USED:\n")
    for s, n in use.most_common():
        f.write(f"{n:>5}  {s}{'' if s in active else '   <-- NOT ACTIVE IN TAXONOMY'}\n")
    unused = [s for s in active if s not in use]
    f.write(f"\nACTIVE BUT NEVER USED ({len(unused)}):\n")
    for s in unused:
        f.write(f"    0  {s}\n")
print(f"used={len(use)} active={len(active)} -> logs/trope_usage.txt")
print("used-but-not-active:", [s for s in use if s not in active][:40])
